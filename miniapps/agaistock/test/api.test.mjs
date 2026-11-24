import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
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
      captured.push({ command, argv, env: options.env });
      return fakeChild;
    },
  );
  assert.equal(captured.length, 1);
  assert.equal(captured[0].env.AGAISTOCK_DATA_DIR, 'D:\\host\\data');
  assert.equal(captured[0].env.AGAISTOCK_DB, join('D:\\host\\data', 'agaistock.db'));
  assert.equal(captured[0].env.PYTHONPATH, join('D:\\pkg', 'src'));
});

test('start() hands the host context to the kernel unchanged', async () => {
  // 堵住「在 helper 之后覆写」这一类：只要 start() 递给内核的不是宿主给的
  // context 原样，这条就红。start() 若绕过 createKernel 直接调 runKernel，
  // 下面的 seen 会是空的 —— 一样红。
  const seen = [];
  const pluginRoot = join(import.meta.dirname, '..');
  const dataDir = join(import.meta.dirname, '..', '..', '..', '.tmp', 'task20-fix2-test-data');
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
  }
  assert.ok(seen.length > 0, '内核必须真的被调用，且拿到宿主给的 context');
  assert.equal(seen[0].ctx.dataDir, dataDir);
  assert.equal(seen[0].root, pluginRoot);
  assert.equal(seen[0].dbPath, join(dataDir, 'agaistock.db'));
});

