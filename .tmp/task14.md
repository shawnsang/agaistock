## Task 14: Mini App 后端 API

**Files:**
- Modify: `miniapps/agaistock/miniapp/node/server.mjs`
- Create: `miniapps/agaistock/test/api.test.mjs`

**Interfaces:**
- Consumes: Task 13 的 CLI（Node 侧 spawn `python -m agaistock.cli`）
- Produces:
  - `export async function handleRoute(request, response, options = {}) -> Promise<void>`
    - `options.kernel` —— 可注入的内核调用函数，签名 `(args: string[]) => Promise<{code: number, stdout: string, stderr: string}>`。
      缺省时使用真实的 `runKernel`。**测试注入 fake kernel**，因此本任务不依赖真实数据库与网络。
    - `options.dbPath` —— 传给内核的数据库路径（缺省用工作区 `data/agaistock.db`）。
  - 路由：
    - `GET    /api/observations` —— 列出观察（已过滤软删）
    - `POST   /api/review` —— body `{ symbol, name, text }` → `200 {observation_id, reviews, score, horizon}`；缺 text → `400`
    - `GET    /api/observations/:id/reviews` → `200 {observation_id, items:[...]}`
    - `DELETE /api/observations/:id` → `200 {ok:true, id}`；内核返回非 0 → `404 {ok:false, error:'not_found'}`

**设计要点**：Node 侧**不引入 sqlite 依赖**，所有数据库操作一律通过 Python 内核 CLI 完成 —— 这保持了「接入层是唯一接口」这条不变（主规格 D3），也避免 Node 与 Python 两套 schema 定义漂移。

- [ ] **Step 1: 写失败的测试**

`miniapps/agaistock/test/api.test.mjs`：

```javascript
import assert from 'node:assert/strict';
import test from 'node:test';

import { handleRoute } from '../miniapp/node/server.mjs';

function makeRequest(method, url, body) {
  return {
    method,
    url,
    headers: { 'content-type': 'application/json' },
    async *[Symbol.asyncIterator]() {
      if (body !== undefined) yield Buffer.from(JSON.stringify(body));
    },
  };
}

class FakeResponse {
  constructor() {
    this.statusCode = 0;
    this.headers = {};
    this.body = '';
  }
  writeHead(status, headers) {
    this.statusCode = status;
    this.headers = headers;
  }
  end(chunk) {
    this.body += chunk ?? '';
  }
  json() {
    return JSON.parse(this.body);
  }
}

function fakeKernel(result) {
  const calls = [];
  const kernel = async (args) => {
    calls.push(args);
    return { code: 0, stdout: JSON.stringify(result), stderr: '' };
  };
  kernel.calls = calls;
  return kernel;
}

test('DELETE /api/observations/:id returns 200 when kernel succeeds', async () => {
  const response = new FakeResponse();
  const kernel = fakeKernel({ ok: true, id: 'obs_123' });
  await handleRoute(
    makeRequest('DELETE', '/api/observations/obs_123'),
    response,
    { kernel, dbPath: 'test.db' },
  );
  assert.equal(response.statusCode, 200);
  assert.equal(response.json().ok, true);
  assert.ok(kernel.calls[0].includes('delete'));
  assert.ok(kernel.calls[0].includes('obs_123'));
});

test('DELETE /api/observations/:id returns 404 when kernel reports missing', async () => {
  const response = new FakeResponse();
  const kernel = async () => ({ code: 1, stdout: '', stderr: '未找到' });
  await handleRoute(
    makeRequest('DELETE', '/api/observations/obs_missing'),
    response,
    { kernel, dbPath: 'test.db' },
  );
  assert.equal(response.statusCode, 404);
  assert.equal(response.json().ok, false);
});

test('GET /api/observations/:id/reviews returns items array', async () => {
  const response = new FakeResponse();
  const kernel = fakeKernel({ observation_id: 'obs_123', items: [{ reviewer_id: 'anchor-chanlun' }] });
  await handleRoute(
    makeRequest('GET', '/api/observations/obs_123/reviews'),
    response,
    { kernel, dbPath: 'test.db' },
  );
  assert.equal(response.statusCode, 200);
  assert.ok(Array.isArray(response.json().items));
});

test('POST /api/review without text returns 400 and does not call kernel', async () => {
  const response = new FakeResponse();
  const kernel = fakeKernel({});
  await handleRoute(
    makeRequest('POST', '/api/review', {}),
    response,
    { kernel, dbPath: 'test.db' },
  );
  assert.equal(response.statusCode, 400);
  assert.equal(kernel.calls.length, 0);
});

test('POST /api/review forwards symbol, name and text to kernel', async () => {
  const response = new FakeResponse();
  const kernel = fakeKernel({ observation_id: 'obs_9', reviews: [], score: {}, horizon: {} });
  await handleRoute(
    makeRequest('POST', '/api/review', { symbol: '002378', name: '章源钨业', text: '还能拿半年' }),
    response,
    { kernel, dbPath: 'test.db' },
  );
  assert.equal(response.statusCode, 200);
  assert.equal(response.json().observation_id, 'obs_9');
  const args = kernel.calls[0];
  assert.ok(args.includes('review'));
  assert.ok(args.includes('002378'));
  assert.ok(args.includes('章源钨业'));
  assert.ok(args.includes('还能拿半年'));
});

test('POST /api/review returns 422 when kernel fails', async () => {
  const response = new FakeResponse();
  const kernel = async () => ({ code: 1, stdout: '', stderr: 'boom' });
  await handleRoute(
    makeRequest('POST', '/api/review', { symbol: '002378', name: 'x', text: 't' }),
    response,
    { kernel, dbPath: 'test.db' },
  );
  assert.equal(response.statusCode, 422);
  assert.equal(response.json().ok, false);
});
```

- [ ] **Step 2: 运行测试确认失败**

```bash
node --test miniapps/agaistock/test/api.test.mjs
```

Expected: FAIL —— `handleRoute` 未导出（当前 server.mjs 只有内联的 `handle`）

- [ ] **Step 3: 在 server.mjs 中加入内核调用与新路由**

在 `server.mjs` 顶部补充 import：

```javascript
import { spawn } from 'node:child_process';
import { join } from 'node:path';
```

在 `start()` 之前新增：

```javascript
const REPO_ROOT = join(import.meta.dirname, '..', '..', '..', '..');
const DEFAULT_DB = join(REPO_ROOT, 'data', 'agaistock.db');

/**
 * 调用 Python 内核 CLI。
 *
 * Node 侧不碰 sqlite —— 数据库的唯一入口是内核（主规格 D3：接入层是唯一接口）。
 * 返回 {code, stdout, stderr}，不抛异常。
 */
export function runKernel(args) {
  return new Promise((resolve) => {
    const child = spawn('python', ['-m', 'agaistock.cli', ...args], {
      cwd: REPO_ROOT,
      env: {
        ...process.env,
        PYTHONPATH: join(REPO_ROOT, 'src'),
        AGAISTOCK_DB: DEFAULT_DB,
      },
    });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => { stdout += chunk; });
    child.stderr.on('data', (chunk) => { stderr += chunk; });
    child.on('error', (error) => resolve({ code: -1, stdout: '', stderr: String(error.message) }));
    child.on('close', (code) => resolve({ code: code ?? -1, stdout, stderr }));
  });
}

function parseKernelJson(stdout) {
  try {
    return JSON.parse(stdout);
  } catch {
    return null;
  }
}
```

把现有内联的 `async function handle(request, response) {...}` 改为导出的 `export async function handleRoute(request, response, options = {})`，并在其中：

- 用 `const kernel = options.kernel ?? runKernel;`
- 用 `const dbPath = options.dbPath ?? DEFAULT_DB;`
- 保留原有的 `/dashboard`、`/api/status`、`/api/observations`、`/api/parse`、`/api/save` 路由（`/api/observations` 改为走 kernel `list --json`）
- 新增路由（放在 `/api/save` 之后、`404` 兜底之前）：

```javascript
    if (request.method === 'POST' && url.pathname === '/api/review') {
      const body = await readBody(request);
      const text = typeof body.text === 'string' ? body.text.trim() : '';
      if (!text) {
        sendJson(response, 400, { ok: false, error: 'EMPTY_INPUT', message: '先说点什么。' });
        return;
      }
      const result = await kernel([
        'review',
        '--symbol', String(body.symbol ?? ''),
        '--name', String(body.name ?? ''),
        '--text', text,
        '--db', dbPath,
        '--json',
      ]);
      if (result.code !== 0) {
        sendJson(response, 422, {
          ok: false,
          error: 'KERNEL_FAILED',
          message: (result.stderr || '').slice(-500) || `exit=${result.code}`,
        });
        return;
      }
      const payload = parseKernelJson(result.stdout);
      if (!payload) {
        sendJson(response, 422, { ok: false, error: 'KERNEL_BAD_OUTPUT', message: result.stdout.slice(-300) });
        return;
      }
      sendJson(response, 200, payload);
      return;
    }

    if (request.method === 'GET' && url.pathname.endsWith('/reviews')) {
      const id = decodeURIComponent(url.pathname.slice('/api/observations/'.length, -'/reviews'.length));
      const result = await kernel(['reviews', id, '--db', dbPath, '--json']);
      const payload = parseKernelJson(result.stdout);
      sendJson(response, 200, payload ?? { observation_id: id, items: [] });
      return;
    }

    if (request.method === 'DELETE' && url.pathname.startsWith('/api/observations/')) {
      const id = decodeURIComponent(url.pathname.slice('/api/observations/'.length));
      const result = await kernel(['delete', id, '--db', dbPath, '--json']);
      if (result.code !== 0) {
        sendJson(response, 404, { ok: false, error: 'not_found', id });
        return;
      }
      sendJson(response, 200, { ok: true, id });
      return;
    }
```

**路由顺序注意**：`GET /api/observations/:id/reviews` 必须放在通用的 `GET /api/observations` 之前判断，否则会被先匹配掉。

- [ ] **Step 4: 运行测试确认通过**

```bash
node --test miniapps/agaistock/test/
```

Expected: 全部 PASS —— 既有 `pipeline.test.mjs` 23 条 + 新增 `api.test.mjs` 6 条

- [ ] **Step 5: toolAccess 保持不声明**

当前实现用 spawn CLI 调用内核，**不需要** `toolAccess`。因此 `miniapp/miniapp.json` **保持不变**：

```json
// miniapp/miniapp.json 保持不变 —— 不加 toolAccess
```

若后续改为 `context.tool` 方式调用，必须**先探测成功**再声明 `"toolAccess": ["call"]`，不得在探测前声明。

- [ ] **Step 6: Commit**

```bash
git add miniapps/agaistock/miniapp/node/server.mjs miniapps/agaistock/test/api.test.mjs
git commit -m "feat: mini app api for review, reviews and soft delete"
```

---

