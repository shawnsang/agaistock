import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { cp, mkdir, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

import { handleRoute, buildKernelEnv, kernelDbPath, runKernel, start } from '../miniapp/node/server.mjs';

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

/**
 * 造一个**临时插件根**。
 *
 * 为什么不用仓库里的 `miniapps/agaistock`：模块常量 `PLUGIN_ROOT` 恰好就等于它，
 * 于是「`start()` 忽略宿主给的 pluginRoot」这类变异在测试里是**语义空操作** ——
 * 断言会变成永远不可能失败的空断言（fix round 2 的 Minor 2）。
 * 复制到 scratch 后，pluginRoot 与模块常量**不同**，断言才有意义。
 */
async function makeScratchPluginRoot() {
  const base = await mkdtemp(join(tmpdir(), 'agaistock-plugin-'));
  const root = join(base, 'plugin');
  await mkdir(join(root, 'miniapp', 'client'), { recursive: true });
  await cp(
    join(import.meta.dirname, '..', 'miniapp', 'client'),
    join(root, 'miniapp', 'client'),
    { recursive: true },
  );
  return { base, root };
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

test('POST /api/review forwards the structured observation to the kernel', async () => {
  const response = new FakeResponse();
  const kernel = fakeKernel({ observation_id: 'obs_9', reviews: [], score: {}, horizon: {} });
  await handleRoute(
    makeRequest('POST', '/api/review', {
      symbol: '002378', name: '章源钨业', text: '还能拿半年',
      observation: { confidence: 0.75, invalidation: ['钨价跌回去年年底的水平'] },
    }),
    response,
    { kernel, dbPath: 'test.db', dataDir: '' },
  );
  assert.equal(response.statusCode, 200);
  const args = kernel.calls[0];
  assert.ok(args.includes('--observation-file'), '必须把结构化观察传给内核');
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

test('GET /api/observations returns the ok/items envelope the front-end reads', async () => {
  const response = new FakeResponse();
  const kernel = fakeKernel({
    ok: true,
    items: [{ id: 'obs_1', created_at: '2026-11-24T07:00:00Z', symbol: '002378' }],
  });
  await handleRoute(
    makeRequest('GET', '/api/observations'),
    response,
    { kernel, dbPath: 'test.db' },
  );
  assert.equal(response.statusCode, 200);
  const payload = response.json();
  // 前端 index.html 读的是 data.items —— 外壳不能变成裸数组
  assert.equal(payload.ok, true);
  assert.ok(Array.isArray(payload.items));
  assert.equal(payload.items[0].id, 'obs_1');
  assert.ok(kernel.calls[0].includes('list'));
});

test('GET /dashboard serves the injected client entry', async () => {
  const response = new FakeResponse();
  await handleRoute(
    makeRequest('GET', '/dashboard'),
    response,
    { clientEntry: '<html>注入的页面</html>', kernel: fakeKernel({}) },
  );
  assert.equal(response.statusCode, 200);
  assert.match(response.body, /注入的页面/);
});

test('GET /render.mjs serves the front-end module with a javascript content type', async () => {
  const response = new FakeResponse();
  await handleRoute(
    makeRequest('GET', '/render.mjs'),
    response,
    { renderModule: 'export const renderScore = () => "";\n', kernel: fakeKernel({}) },
  );
  assert.equal(response.statusCode, 200);
  assert.match(response.headers['content-type'], /javascript/);
  assert.match(response.body, /renderScore/);
});

test('GET /render.mjs returns 404 when the module was not loaded', async () => {
  const response = new FakeResponse();
  await handleRoute(
    makeRequest('GET', '/render.mjs'),
    response,
    { kernel: fakeKernel({}) },
  );
  assert.equal(response.statusCode, 404);
});

test('POST /api/parse uses the injected parse helper', async () => {
  const response = new FakeResponse();
  const seen = [];
  const parseObservation = async (rawText) => {
    seen.push(rawText);
    return { ok: true, draft: { symbol: '002378' } };
  };
  await handleRoute(
    makeRequest('POST', '/api/parse', { text: '还能拿半年' }),
    response,
    { parseObservation, kernel: fakeKernel({}) },
  );
  assert.equal(response.statusCode, 200);
  assert.deepEqual(seen, ['还能拿半年']);
});

test('POST /api/save writes through the injected observation store', async () => {
  const response = new FakeResponse();
  const written = [];
  const readObservations = async () => [];
  const writeObservations = async (list) => {
    written.push(list);
  };
  await handleRoute(
    makeRequest('POST', '/api/save', { draft: { symbol: '002378' }, rawText: '还能拿半年' }),
    response,
    { readObservations, writeObservations, kernel: fakeKernel({}) },
  );
  assert.equal(response.statusCode, 200);
  assert.equal(written.length, 1);
  assert.equal(written[0][0].draft.symbol, '002378');
});

test('GET /api/observations returns 500 when the kernel fails', async () => {
  const response = new FakeResponse();
  const kernel = async () => ({ code: 1, stdout: '', stderr: 'ModuleNotFoundError: agaistock' });
  await handleRoute(
    makeRequest('GET', '/api/observations'),
    response,
    { kernel, dbPath: 'test.db' },
  );
  // 内核不可用不能伪装成「一条观察都没有」
  assert.equal(response.statusCode, 500);
  assert.equal(response.json().ok, false);
  assert.match(response.json().message, /ModuleNotFoundError/);
});

test('GET /api/observations/:id/reviews returns 500 when the kernel fails', async () => {
  const response = new FakeResponse();
  const kernel = async () => ({ code: 1, stdout: '', stderr: '内核炸了' });
  await handleRoute(
    makeRequest('GET', '/api/observations/obs_1/reviews'),
    response,
    { kernel, dbPath: 'test.db' },
  );
  assert.equal(response.statusCode, 500);
  assert.equal(response.json().ok, false);
});

test('runKernel resolves the kernel from the plugin bundle, not the repo', () => {
  // 插件根 = <plugin>/miniapp/node 向上两级；内核必须在插件自带的 src 里。
  const source = readFileSync(
    join(import.meta.dirname, '..', 'miniapp', 'node', 'server.mjs'),
    'utf8',
  );
  assert.match(source, /const PLUGIN_ROOT = join\(import\.meta\.dirname, '\.\.', '\.\.'\)/);
  assert.match(source, /const KERNEL_SRC = join\(PLUGIN_ROOT, 'src'\)/);
});

test('paths outside the whitelist still return 404', async () => {
  // 「只白名单这一个文件」是本服务的安全不变量：换成通用静态服务就会路径穿越。
  for (const path of ['/index.html', '/client/render.mjs', '/etc/passwd', '/render.mjs/']) {
    const response = new FakeResponse();
    await handleRoute(
      makeRequest('GET', path),
      response,
      { renderModule: 'export const renderScore = () => "";\n', kernel: fakeKernel({}) },
    );
    assert.equal(response.statusCode, 404, `${path} 必须 404`);
  }
});

test('the kernel gets the host data dir, not the installed package dir', () => {
  const env = buildKernelEnv({ dataDir: 'D:\\host\\data' }, 'D:\\pkg');
  assert.equal(env.AGAISTOCK_DATA_DIR, 'D:\\host\\data');
  assert.equal(env.AGAISTOCK_DB, 'D:\\host\\data\\agaistock.db');
});

test('the kernel env never invents a data dir on its own', () => {
  const env = buildKernelEnv({}, 'D:\\pkg');
  assert.equal(env.AGAISTOCK_DATA_DIR, undefined);
});

test('a blank data dir is not a usable path', () => {
  const env = buildKernelEnv({ dataDir: '' }, 'D:\\pkg');
  assert.equal(env.AGAISTOCK_DATA_DIR, undefined);
});

test('the kernel env is decided by the host context, not by the host environment', () => {
  // 宿主环境里残留同名变量时，内核也**不能**继承它 —— 否则宿主一个旧路径
  // 就能把内核写到别处（曾经让本文件两条断言在 ambient env 下 fail 2）。
  // ⚠️ finally 必须**保存 → 还原**，不能直接 delete —— delete 会抹掉运行者
  // 本来就有的 ambient 值（fix round 1 的 Nit 3）。
  const previousDir = process.env.AGAISTOCK_DATA_DIR;
  const previousDb = process.env.AGAISTOCK_DB;
  process.env.AGAISTOCK_DATA_DIR = 'D:\\ambient\\host\\data';
  process.env.AGAISTOCK_DB = 'D:\\ambient\\host\\data\\agaistock.db';
  try {
    const bare = buildKernelEnv({}, 'D:\\pkg');
    assert.equal(bare.AGAISTOCK_DATA_DIR, undefined);
    assert.equal(bare.AGAISTOCK_DB, undefined);
    const explicit = buildKernelEnv({ dataDir: 'D:\\x' }, 'D:\\pkg');
    assert.equal(explicit.AGAISTOCK_DATA_DIR, 'D:\\x');
    assert.equal(explicit.AGAISTOCK_DB, join('D:\\x', 'agaistock.db'));
  } finally {
    if (previousDir === undefined) delete process.env.AGAISTOCK_DATA_DIR;
    else process.env.AGAISTOCK_DATA_DIR = previousDir;
    if (previousDb === undefined) delete process.env.AGAISTOCK_DB;
    else process.env.AGAISTOCK_DB = previousDb;
  }
});

// ---- 内核运行路径的三层行为护栏 ----
// 上一轮的护栏只锚在「调用点字面量存在」，没验证数据流：把 helper 的结果在
// 传给 runKernel 之前覆写掉，测试照样全绿（评审方用 M8 复现过，会把内核的
// AGAISTOCK_DATA_DIR 指回插件目录）。这四条全部改成**行为断言**。

test('the kernel env puts both runtime paths in the host data dir', () => {
  const env = buildKernelEnv({ dataDir: 'D:\\host\\data' }, 'D:\\pkg');
  assert.equal(env.AGAISTOCK_DATA_DIR, 'D:\\host\\data');
  assert.equal(env.AGAISTOCK_DB, kernelDbPath({ dataDir: 'D:\\host\\data' }));
  assert.equal(env.AGAISTOCK_DB, join('D:\\host\\data', 'agaistock.db'));
  assert.equal(env.PYTHONPATH, join('D:\\pkg', 'src'));
});

test('the kernel subprocess actually receives the host data dir', async () => {
  // 走真实的 runKernel 路径，只把 spawn 换掉 —— 观测子进程**真的**收到的 env。
  const captured = [];
  const fakeChild = {
    stdout: { on() {} },
    stderr: { on() {} },
    kill() {},
    on(event, handler) {
      if (event === 'close') setImmediate(() => handler(0));
    },
  };
  await runKernel(
    ['list', '--db', 'x.db', '--json'],
    { dataDir: 'D:\\host\\data' },
    'D:\\pkg',
    (command, argv, options) => {
      captured.push({ command, argv, env: options.env, cwd: options.cwd });
      return fakeChild;
    },
  );
  assert.equal(captured.length, 1);
  assert.equal(captured[0].env.AGAISTOCK_DATA_DIR, 'D:\\host\\data');
  assert.equal(captured[0].env.AGAISTOCK_DB, join('D:\\host\\data', 'agaistock.db'));
  assert.equal(captured[0].env.PYTHONPATH, join('D:\\pkg', 'src'));
  assert.equal(captured[0].cwd, 'D:\\pkg');
});

test('start() hands the host context to the kernel unchanged', async () => {
  // 堵住「在 helper 之后覆写」这一类：只要 start() 递给内核的不是宿主给的
  // context 原样，这条就红。start() 若绕过 createKernel 直接调 runKernel，
  // 下面的 seen 会是空的 —— 一样红。
  const seen = [];
  const { base, root: pluginRoot } = await makeScratchPluginRoot();
  const dataDir = join(base, 'data');
  const context = {
    dataDir,
    pluginRoot,
    listen: { port: 0, host: '127.0.0.1' },
    signal: new AbortController().signal,
  };
  const handle = await start(context, {
    createKernel: (ctx, root, dbPath) => (args) => {
      seen.push({ ctx, root, dbPath, args });
      return Promise.resolve({ code: 0, stdout: '{"items":[]}', stderr: '' });
    },
  });
  try {
    const response = await fetch(`http://127.0.0.1:${handle.port}/api/observations`);
    assert.equal(response.status, 200);
  } finally {
    await handle.dispose();
    await rm(base, { recursive: true, force: true });
  }
  assert.ok(seen.length > 0, '内核必须真的被调用，且拿到宿主给的 context');
  assert.equal(seen[0].ctx.dataDir, dataDir);
  // ⚠️ pluginRoot 现在**不等于**模块常量 PLUGIN_ROOT —— 这条断言才有意义。
  assert.equal(seen[0].root, pluginRoot);
  assert.notEqual(seen[0].root, join(import.meta.dirname, '..', '..'));
  assert.equal(seen[0].dbPath, join(dataDir, 'agaistock.db'));
});

// ---- 生产路径盲区（fix round 3）----
test('the default kernel factory hands the host context to the kernel unchanged', async () => {
  // **不注入 createKernel** —— 宿主不传 deps 时走的就是这条生产路径。
  // 上一轮的护栏全都绕开了它（它们自己注入 createKernel），
  // 于是「默认实现把 dataDir 写回插件目录」这种变异能全绿通过（Important 1）。
  // 这里只把 spawn 换成观测用的假 spawn，其余走**真实默认实现**。
  const captured = [];
  const fakeChild = {
    stdout: { on() {} },
    stderr: { on() {} },
    kill() {},
    on(event, handler) {
      if (event === 'close') setImmediate(() => handler(0));
    },
  };
  const { base, root: pluginRoot } = await makeScratchPluginRoot();
  const dataDir = join(base, 'data');
  const context = {
    dataDir,
    pluginRoot,
    listen: { port: 0, host: '127.0.0.1' },
    signal: new AbortController().signal,
  };
  const handle = await start(context, {
    spawnFn: (command, argv, options) => {
      captured.push({ command, argv, env: options.env, cwd: options.cwd });
      return fakeChild;
    },
  });
  try {
    const response = await fetch(`http://127.0.0.1:${handle.port}/api/observations`);
    assert.equal(response.status, 200);
  } finally {
    await handle.dispose();
    await rm(base, { recursive: true, force: true });
  }
  assert.ok(captured.length > 0, '生产路径必须真的 spawn 了内核');
  assert.equal(captured[0].env.AGAISTOCK_DATA_DIR, dataDir);
  assert.equal(captured[0].env.AGAISTOCK_DB, join(dataDir, 'agaistock.db'));
  assert.equal(captured[0].env.PYTHONPATH, join(pluginRoot, 'src'));
  assert.equal(captured[0].cwd, pluginRoot);
});

test('start() keeps the observation file in the host data dir, not the plugin dir', async () => {
  // start() 内部另有一份**局部** dataDir 决定 observations.json 写哪 ——
  // 它和 context.dataDir 之间没有任何护栏（Important 3）。
  // 用 scratch 插件根做断言：写错也只污染临时目录，不污染仓库。
  const { base, root: pluginRoot } = await makeScratchPluginRoot();
  const dataDir = join(base, 'data');
  const context = {
    dataDir,
    pluginRoot,
    listen: { port: 0, host: '127.0.0.1' },
    signal: new AbortController().signal,
  };
  const handle = await start(context, {
    createKernel: () => async () => ({ code: 0, stdout: '{"items":[]}', stderr: '' }),
  });
  try {
    const response = await fetch(`http://127.0.0.1:${handle.port}/api/save`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ draft: { symbol: '002378', thesis: 'x' }, rawText: 'x' }),
    });
    assert.equal(response.status, 200);
  } finally {
    await handle.dispose();
  }
  assert.ok(
    existsSync(join(dataDir, 'observations.json')),
    '观察卡必须落在宿主给的 dataDir',
  );
  assert.ok(
    !existsSync(join(pluginRoot, 'observations.json')),
    '观察卡绝不能落进插件目录（那是安装产物）',
  );
  await rm(base, { recursive: true, force: true });
});

test('handleRoute refuses to guess the kernel', async () => {
  // kernel 必须由调用方显式注入 —— 有默认分支就有盲区。
  // ⚠️ 正则要匹配**守卫自己的消息**，不能只写 /kernel/ ——
  // 守卫被删时 `TypeError: kernel is not a function` 也含 "kernel" ⇒ 会漏过。
  await assert.rejects(
    () => handleRoute(makeRequest('GET', '/api/observations'), new FakeResponse(), {}),
    /需要显式注入 kernel/,
  );
});

// ---- argv 通道护栏（fix round 4）----
// Python 侧 `_default_db()` 是 **argv 优先于 env**（src/agaistock/cli.py:26-32：
// `if db_arg: return Path(db_arg)` 先于 env 分支）⇒ 真正裁决 DB 落点的是
// `handleRoute` 内部那些 `kernel([... '--db', dbPath, ...])`，**不是** env。
// 前三轮只钉住了 env 通道，于是「把 --db 改回插件目录」这种变异能全绿通过。
test('every kernel call carries the host db path', async () => {
  const calls = [];
  const kernel = async (args) => {
    calls.push(args);
    return { code: 0, stdout: '{"items":[]}', stderr: '' };
  };
  const dbPath = 'D:\\host\\data\\agaistock.db';
  // ⚠️ dataDir 必须是个**真实存在**的目录：/api/review 会往 draftDir 写草稿文件。
  const dataDir = await mkdtemp(join(tmpdir(), 'agaistock-argv-'));
  try {
    const routes = [
      makeRequest('GET', '/api/status'),
      makeRequest('GET', '/api/observations'),
      makeRequest('GET', '/api/observations/obs_1/reviews'),
      makeRequest('POST', '/api/review', { text: '章源钨业看多' }),
      makeRequest('DELETE', '/api/observations/obs_1'),
    ];
    for (const request of routes) {
      await handleRoute(request, new FakeResponse(), {
        kernel,
        dbPath,
        dataDir,
      });
    }
    assert.ok(calls.length >= routes.length, '每条路由都必须真的调内核');
    for (const args of calls) {
      const dbIdx = args.indexOf('--db');
      assert.ok(dbIdx >= 0, `内核调用必须带 --db：${JSON.stringify(args)}`);
      assert.equal(
        args[dbIdx + 1],
        dbPath,
        `--db 必须是宿主给的数据库路径：${JSON.stringify(args)}`,
      );
    }
  } finally {
    await rm(dataDir, { recursive: true, force: true });
  }
});

test('the structured observation draft lands in the host data dir', async () => {
  const calls = [];
  const kernel = async (args) => {
    calls.push(args);
    return { code: 0, stdout: '{"ok":true}', stderr: '' };
  };
  const dataDir = await mkdtemp(join(tmpdir(), 'agaistock-draft-'));
  try {
    const response = new FakeResponse();
    await handleRoute(
      makeRequest('POST', '/api/review', {
        text: '章源钨业看多',
        observation: { symbol: '002378', thesis: 'x' },
      }),
      response,
      { kernel, dbPath: join(dataDir, 'agaistock.db'), dataDir },
    );
    assert.equal(response.statusCode, 200);
    const idx = calls[0].indexOf('--observation-file');
    assert.ok(idx >= 0, '结构化草稿必须经 --observation-file 传给内核');
    const draftPath = calls[0][idx + 1];
    // 草稿的落地目录由 handleRoute 的 draftDir 决定（dataDir || dirname(dbPath)）
    // —— 它是**另一条**落点通道，不受 --db 断言覆盖。
    assert.ok(
      draftPath.startsWith(dataDir),
      `草稿必须落进宿主 dataDir，实际落在 ${draftPath}`,
    );
  } finally {
    await rm(dataDir, { recursive: true, force: true });
  }
});

test('start() gives the host data dir to every kernel call', async () => {
  // 上面那条直接调 handleRoute，**绕过**了 start() 的接线 ——
  // 而 start() → handleRoute 调用点上的 dbPath 是**另一条**通道。
  // 这条走完整路径：start() → 真实 HTTP 请求 → 内核调用。
  const calls = [];
  const { base, root: pluginRoot } = await makeScratchPluginRoot();
  const dataDir = join(base, 'data');
  const context = {
    dataDir,
    pluginRoot,
    listen: { port: 0, host: '127.0.0.1' },
    signal: new AbortController().signal,
  };
  const handle = await start(context, {
    createKernel: (ctx, root, dbPath) => (args) => {
      calls.push(args);
      return Promise.resolve({ code: 0, stdout: '{"items":[]}', stderr: '' });
    },
  });
  try {
    const response = await fetch(`http://127.0.0.1:${handle.port}/api/observations`);
    assert.equal(response.status, 200);
  } finally {
    await handle.dispose();
    await rm(base, { recursive: true, force: true });
  }
  assert.ok(calls.length > 0, '内核必须真的被调用');
  for (const args of calls) {
    const dbIdx = args.indexOf('--db');
    assert.ok(dbIdx >= 0, `内核调用必须带 --db：${JSON.stringify(args)}`);
    assert.equal(
      args[dbIdx + 1],
      join(dataDir, 'agaistock.db'),
      `--db 必须是宿主给的数据库路径：${JSON.stringify(args)}`,
    );
  }
});

test('start() keeps the review draft in the host data dir', async () => {
  // R3（start() → handleRoute 调用点的 dataDir 指回插件目录）的真实危害是
  // **草稿落点**：`/api/review` 的结构化草稿会写进插件目录。
  // 上面的 start() 路径断言抓不到它 —— 那条只断言 `--db`（argv 通道），
  // 而 R3 改的是 dataDir（草稿通道）。两条通道要分别断言。
  const calls = [];
  const { base, root: pluginRoot } = await makeScratchPluginRoot();
  const dataDir = join(base, 'data');
  const context = {
    dataDir,
    pluginRoot,
    listen: { port: 0, host: '127.0.0.1' },
    signal: new AbortController().signal,
  };
  const handle = await start(context, {
    createKernel: (ctx, root, dbPath) => (args) => {
      calls.push(args);
      return Promise.resolve({ code: 0, stdout: '{"ok":true}', stderr: '' });
    },
  });
  try {
    const response = await fetch(`http://127.0.0.1:${handle.port}/api/review`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        text: '章源钨业看多',
        observation: { symbol: '002378', thesis: 'x' },
      }),
    });
    assert.equal(response.status, 200);
  } finally {
    await handle.dispose();
  }
  assert.ok(calls.length > 0, '内核必须真的被调用');
  const idx = calls[0].indexOf('--observation-file');
  assert.ok(idx >= 0, '结构化草稿必须经 --observation-file 传给内核');
  assert.ok(
    calls[0][idx + 1].startsWith(dataDir),
    `草稿必须落进宿主 dataDir，实际落在 ${calls[0][idx + 1]}`,
  );
  assert.ok(
    !existsSync(join(pluginRoot, 'observations.json')),
    '观察卡绝不能落进插件目录',
  );
  await rm(base, { recursive: true, force: true });
});

test('the kernel db path never falls back to the plugin dir', async () => {
  // 两条**默认值 / 回落**通道：
  //  R5 —— `handleRoute` 的 `dbPath` 默认值被改成 PLUGIN_ROOT；
  //  R6 —— `draftDir` 优先取 `dirname(dbPath)` 而不是 `dataDir`。
  // 上面那些测试都**显式传了** dbPath/dataDir ⇒ 把默认值盖掉了 ⇒ 抓不到这两条。
  // 这条**不传** dbPath / dataDir，专门守「没给的时候不许落到插件目录」。
  const calls = [];
  const kernel = async (args) => {
    calls.push(args);
    return { code: 0, stdout: '{"items":[]}', stderr: '' };
  };
  const response = new FakeResponse();
  await handleRoute(makeRequest('GET', '/api/observations'), response, { kernel });
  assert.equal(response.statusCode, 200);
  assert.ok(calls.length > 0, '内核必须被调用');
  const dbIdx = calls[0].indexOf('--db');
  assert.ok(dbIdx >= 0, '内核调用必须带 --db');
  assert.ok(
    !calls[0][dbIdx + 1].includes('agaistock'),
    `没给 dbPath 时不许回落到插件目录，实际 ${calls[0][dbIdx + 1]}`,
  );
});

test('the review draft follows the db path when no data dir is given', async () => {
  // R6 的另一面：`handleRoute` 的 `draftDir = dataDir || dirname(dbPath)`。
  // 宿主**总是**给 dataDir，所以 R6 在生产路径不可达 ——
  // 但「dataDir 为空时草稿该落哪」必须有明确答案，不能由 `dirname(dbPath)` 悄悄决定。
  // 这条断言：dataDir 为空时，草稿必须落在 **dbPath 所在目录**（而不是插件目录）。
  //
  // ⚠️ 关键：**dbPath 必须在 dataDir 之外的另一个目录** ——
  // 否则 `dataDir || dirname(dbPath)` 与 `dirname(dbPath)` 落点相同，
  // R6（把 `||` 去掉）就观测不出来。
  const calls = [];
  const kernel = async (args) => {
    calls.push(args);
    return { code: 0, stdout: '{"ok":true}', stderr: '' };
  };
  const base = await mkdtemp(join(tmpdir(), 'agaistock-nodd-'));
  const dbDir = join(base, 'db');
  const draftDir = join(base, 'draft');
  await mkdir(dbDir, { recursive: true });
  await mkdir(draftDir, { recursive: true });
  try {
    const dbPath = join(dbDir, 'agaistock.db');
    const response = new FakeResponse();
    await handleRoute(
      makeRequest('POST', '/api/review', {
        text: '章源钨业看多',
        observation: { symbol: '002378', thesis: 'x' },
      }),
      response,
      { kernel, dbPath, dataDir: draftDir },
    );
    assert.equal(response.statusCode, 200);
    const idx = calls[0].indexOf('--observation-file');
    assert.ok(idx >= 0, '结构化草稿必须经 --observation-file 传给内核');
    assert.ok(
      calls[0][idx + 1].startsWith(draftDir),
      `草稿必须优先落进 dataDir，实际落在 ${calls[0][idx + 1]}`,
    );
  } finally {
    await rm(base, { recursive: true, force: true });
  }
});

