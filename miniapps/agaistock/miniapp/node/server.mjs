import { readFile, writeFile, mkdir, rename } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { join } from 'node:path';

const OBSERVATIONS_FILE = 'observations.json';

/**
 * Parse prompt. Strict JSON only, and the two rules that matter for this product:
 * never invent a falsification condition, never invent evidence the user did not say.
 */
const PARSE_PROMPT = `你是股票复盘助手。把用户口述的一段话解析成一张结构化的「观察卡」。

只输出一个 JSON 对象。不要输出任何解释文字，不要用 markdown 代码块包裹。

字段定义：
{
  "symbol": "6 位 A 股代码；不知道就空字符串",
  "name": "股票简称；不知道就空字符串",
  "thesis": "一句话概括用户的核心主张，不超过 40 字",
  "direction": "bullish | bearish | neutral",
  "confidence": 0 到 1 之间的数字，
  "evidence": [ { "text": "一条依据", "type": "fact | assumption" } ],
  "invalidation": [ "在什么情况下这个判断就算错了" ],
  "invalidation_missing": true 或 false,
  "position": { "entry": "进场条件描述", "size": "仓位描述" },
  "timeframe": "用户口述的时间跨度",
  "trigger": "触发或催化剂；没有就空字符串"
}

必须遵守的规则：
1. 用户没有说「什么情况下我错」时，invalidation 必须是空数组，invalidation_missing 必须是 true。
   绝对不要替用户编造证伪条件。
2. evidence 的每一条都必须来自用户原话表达的意思，不要添加用户没有说过的信息。
3. 判断 type：价格、公告、财报、产量、储量等客观可查的内容标 fact；
   预期、未来计划、没有出处的判断、主观感受标 assumption。
4. 用户没有说的字段用空字符串、空数组或 0，不要瞎填。
5. confidence 反映用户自己表达的确信程度，不是你对他观点正确性的判断。
6. thesis 与 timeframe 必须忠实于用户的表述，不得推断、延长或改写时间跨度。
   用户说「还能拿半年」就只能写半年；说「明年上半年」就只能写明年上半年。
   概括可以更简洁，但不得添加用户没有说的时长、期限或确定性。`;

/** Pull the first JSON object out of a model reply, tolerating a fenced block. */
export function extractJson(text) {
  const source = String(text ?? '');
  const fenced = source.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const body = fenced ? fenced[1] : source;
  const start = body.indexOf('{');
  if (start < 0) return null;
  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let i = start; i < body.length; i += 1) {
    const ch = body[i];
    if (escaped) {
      escaped = false;
      continue;
    }
    if (ch === '\\') {
      escaped = true;
      continue;
    }
    if (ch === '"') {
      inString = !inString;
      continue;
    }
    if (inString) continue;
    if (ch === '{') depth += 1;
    else if (ch === '}') {
      depth -= 1;
      if (depth === 0) {
        try {
          return JSON.parse(body.slice(start, i + 1));
        } catch {
          return null;
        }
      }
    }
  }
  return null;
}

async function readBody(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  if (chunks.length === 0) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch {
    return {};
  }
}

function sendJson(response, status, payload) {
  response.writeHead(status, { 'content-type': 'application/json; charset=utf-8' });
  response.end(JSON.stringify(payload));
}

// 插件根：<plugin>/miniapp/node -> <plugin>/miniapp -> <plugin>
// **不能**用「向上 4 级」：那只在插件位于仓库内时成立。安装后插件根在
// ~/.minimax/plugins/<id>/，向上 4 级会落到插件目录之外，内核与配置全找不到。
const PLUGIN_ROOT = join(import.meta.dirname, '..', '..');
const KERNEL_SRC = join(PLUGIN_ROOT, 'src');
const KERNEL_TIMEOUT_MS = 180000;

/**
 * 调用 Python 内核 CLI。
 *
 * Node 侧不碰 sqlite —— 数据库的唯一入口是内核（主规格 D3：接入层是唯一接口）。
 * 返回 {code, stdout, stderr}，不抛异常。
 * 带超时：三级别取数 + 点评可能跑很久，超时按失败处理，避免请求永久挂住。
 */
export function runKernel(args, options = {}) {
  const cwd = options.cwd || PLUGIN_ROOT;
  const pythonPath = options.pythonPath || KERNEL_SRC;
  const dbPath = options.dbPath || '';
  return new Promise((resolve) => {
    const env = { ...process.env, PYTHONPATH: pythonPath, PYTHONIOENCODING: 'utf-8' };
    if (dbPath) env.AGAISTOCK_DB = dbPath;
    // **必须带 `-S`**：editable 安装（`pip install -e .`）注册的是 meta-path finder，
    // 优先级**高于** PYTHONPATH —— 实测开发机上不加 `-S` 时 `import agaistock`
    // 命中的是仓库里那份，不是插件自带的副本，自包含就成了空话。
    // `-S` 同时禁用 site-packages，正好把「业务内核零第三方依赖」（Global Constraint 2）
    // 从约定变成运行时硬约束：内核一旦依赖第三方包，Mini App 会立刻报错而不是
    // 悄悄依赖用户机器上的环境。
    const child = spawn('python', ['-S', '-m', 'agaistock.cli', ...args], {
      cwd,
      env,
      encoding: 'utf8',
    });
    let stdout = '';
    let stderr = '';
    let settled = false;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      resolve(result);
    };
    const timer = setTimeout(() => {
      child.kill();
      finish({ code: -1, stdout, stderr: `内核调用超时（${KERNEL_TIMEOUT_MS}ms）` });
    }, KERNEL_TIMEOUT_MS);
    child.stdout.on('data', (chunk) => { stdout += chunk; });
    child.stderr.on('data', (chunk) => { stderr += chunk; });
    child.on('error', (error) => {
      clearTimeout(timer);
      finish({ code: -1, stdout: '', stderr: String(error.message) });
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      finish({ code: code ?? -1, stdout, stderr });
    });
  });
}

function parseKernelJson(stdout) {
  try {
    return JSON.parse(stdout);
  } catch {
    return null;
  }
}

/**
 * 路由处理。
 *
 * 依赖全部由调用方显式注入：模块层级上没有任何宿主对象被捕获，
 * 因此它既能在 start() 里跑，也能在测试里用 fake 依赖跑。
 */
export async function handleRoute(request, response, options = {}) {
  const {
    context = {},
    clientEntry = '',
    renderModule = '',
    readObservations = async () => [],
    writeObservations = async () => {},
    parseObservation = async () => ({
      ok: false,
      error: 'UNAVAILABLE',
      message: '解析能力不可用。',
    }),
    kernel = runKernel,
    dbPath = '',
  } = options;

  const url = new URL(request.url ?? '/', 'http://miniapp.local');

  if (request.method === 'GET' && url.pathname === '/dashboard') {
    response.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
    response.end(clientEntry);
    return;
  }

  // 前端渲染模块是**第二个静态文件**（Task 15 把 render.mjs 从 index.html 里拆出来）。
  // 宿主只把 index.html 交给 Node 进程（surface.path 是页面入口，不是静态文件服务器），
  // server.mjs 也只路由 /dashboard 与 /api/*，其余一律 404 ——
  // 不显式提供这条路由，浏览器里的 `<script type="module" src="./render.mjs">`
  // 会拿到 404，window.agaistockRender 根本不存在，整页静默失效。
  // 只白名单这一个文件，不做通用静态服务（避免路径穿越）。
  if (request.method === 'GET' && url.pathname === '/render.mjs') {
    if (!renderModule) {
      sendJson(response, 404, { error: 'not_found' });
      return;
    }
    response.writeHead(200, { 'content-type': 'text/javascript; charset=utf-8' });
    response.end(renderModule);
    return;
  }

  if (request.method === 'GET' && url.pathname === '/api/status') {
    sendJson(response, 200, {
      ok: true,
      agent: Boolean(context.agent),
      capabilities: {
        agentRun: context.capabilities?.has?.('agent.run') ?? null,
        speechTranscribe: context.capabilities?.has?.('speech.transcribe') ?? null,
        tool: context.capabilities?.has?.('tool') ?? null,
        hostConnector: context.capabilities?.has?.('hostConnector') ?? null,
      },
      observationCount: await countObservations(kernel, dbPath),
    });
    return;
  }

  if (request.method === 'GET' && url.pathname === '/api/observations') {
    // 观察库以内核为准（删除也走内核，行 id 必须是内核行 id）
    const result = await kernel(['list', '--db', dbPath, '--json']);
    if (result.code !== 0) {
      // 内核不可用 ≠ 没有观察记录。返回空列表会让用户以为「一条都没有」，
      // 真实原因（Python 缺失 / 内核崩了 / 库打不开）被彻底吞掉。
      sendJson(response, 500, {
        ok: false,
        error: 'KERNEL_FAILED',
        message: (result.stderr || `exit=${result.code}`).slice(-500),
      });
      return;
    }
    const payload = parseKernelJson(result.stdout);
    const items = Array.isArray(payload)
      ? payload
      : (payload && Array.isArray(payload.items) ? payload.items : []);
    // 前端读的是 data.items —— 这里必须保持 {ok, items} 外壳
    sendJson(response, 200, { ok: true, items });
    return;
  }

  if (request.method === 'POST' && url.pathname === '/api/parse') {
    const body = await readBody(request);
    const rawText = typeof body.text === 'string' ? body.text.trim() : '';
    if (!rawText) {
      sendJson(response, 400, { ok: false, error: 'EMPTY_INPUT', message: '先说点什么，或直接输入文字。' });
      return;
    }
    const result = await parseObservation(rawText);
    sendJson(response, result.ok ? 200 : 422, result);
    return;
  }

  if (request.method === 'POST' && url.pathname === '/api/save') {
    const body = await readBody(request);
    const draft = body.draft && typeof body.draft === 'object' ? body.draft : null;
    if (!draft) {
      sendJson(response, 400, { ok: false, error: 'INVALID_DRAFT', message: '没有可保存的观察卡。' });
      return;
    }
    const items = await readObservations();
    const record = {
      id: `obs_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`,
      createdAt: new Date().toISOString(),
      rawText: typeof body.rawText === 'string' ? body.rawText : '',
      draft: normalizeDraft(draft),
    };
    items.push(record);
    await writeObservations(items);
    sendJson(response, 200, { ok: true, id: record.id, total: items.length });
    return;
  }

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
    if (result.code !== 0) {
      sendJson(response, 500, {
        ok: false,
        error: 'KERNEL_FAILED',
        message: (result.stderr || `exit=${result.code}`).slice(-500),
      });
      return;
    }
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

  sendJson(response, 404, { error: 'not_found' });
}

async function countObservations(kernel, dbPath) {
  const result = await kernel(['list', '--db', dbPath, '--json']);
  if (result.code !== 0) return null;
  const payload = parseKernelJson(result.stdout);
  if (payload && Array.isArray(payload.items)) return payload.items.length;
  return null;
}

export async function start(context) {
  const dataDir = context.dataDir;
  await mkdir(dataDir, { recursive: true });
  const observationsPath = join(dataDir, OBSERVATIONS_FILE);
  // 宿主给的 pluginRoot 才是权威；模块层级的推导只是兜底。
  const pluginRoot = context.pluginRoot || PLUGIN_ROOT;
  const clientEntry = await readFile(join(pluginRoot, 'miniapp/client/index.html'));

  // Task 15 把渲染逻辑拆到 render.mjs，页面用 <script type="module" src="./render.mjs"> 引入。
  // 宿主只把 index.html 交给 Node 进程（surface.path 是页面入口，不是静态文件服务器），
  // 所以 render.mjs 必须由本服务自己提供，否则页面里的 module 脚本 404、整页静默失效。
  // 读不到文件时降级成空字符串 —— 让 start() 抛错会把整个 Mini App 拖到起不来。
  let renderModule = '';
  try {
    renderModule = await readFile(join(pluginRoot, 'miniapp/client/render.mjs'), 'utf8');
  } catch {
    renderModule = '';
  }

  const readObservations = async () => {
    try {
      const parsed = JSON.parse(await readFile(observationsPath, 'utf8'));
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  };

  // Durable state is written as it changes; the Host may stop this process without a callback.
  const writeObservations = async (list) => {
    const temporary = `${observationsPath}.tmp`;
    await writeFile(temporary, JSON.stringify(list, null, 2), 'utf8');
    await rename(temporary, observationsPath);
  };

  const parseObservation = async (rawText) => {
    if (!context.agent) {
      return { ok: false, error: 'AGENT_UNAVAILABLE', message: '当前宿主未授权 Agent 能力（agentAccess: session.run）。' };
    }
    const prompt = `${PARSE_PROMPT}\n\n用户口述原文：\n---\n${rawText}\n---`;
    let streamed = '';
    try {
      const result = await context.agent.run(
        { text: prompt },
        {
          onEvent: (event) => {
            if (event.type === 'text.delta') streamed += event.text;
            if (event.type === 'permission.requested') {
              // Parsing needs no tools. Deny so the turn stays pure model work.
              void context.agent
                .reply({
                  sessionId: event.sessionId,
                  requestId: event.requestId,
                  decision: 'deny',
                })
                .catch(() => undefined);
            }
          },
        },
      );
      if (result.status === 'aborted') {
        return { ok: false, error: 'ABORTED', message: '解析被取消。' };
      }
      if (result.pendingQuestion) {
        return { ok: false, error: 'PENDING_QUESTION', message: '模型在解析过程中提出了问题，请在聊天里回答后重试。' };
      }
      if (result.status === 'error') {
        return { ok: false, error: 'AGENT_ERROR', message: result.error?.message ?? '模型运行出错。' };
      }
      const draft = extractJson(result.text ?? streamed);
      if (!draft) {
        return { ok: false, error: 'PARSE_FAILED', message: '模型没有返回可解析的 JSON。' };
      }
      return { ok: true, draft: normalizeDraft(draft), rawText };
    } catch (error) {
      const code = error && typeof error === 'object' && 'message' in error ? String(error.message) : 'UNKNOWN';
      return { ok: false, error: code, message: `解析失败：${code}` };
    }
  };

  // 运行数据落宿主给的数据目录，**不是**插件目录 ——
  // 插件目录是安装产物（可能被只读安装、也可能被 Host 重装覆盖），
  // dataDir 才是运行时可写、跨重启保留的数据位置。
  const dbPath = join(dataDir, 'agaistock.db');
  const kernel = (args) => runKernel(args, {
    cwd: pluginRoot,
    pythonPath: join(pluginRoot, 'src'),
    dbPath,
  });

  const server = createServer((request, response) => {
    void handleRoute(request, response, {
      context,
      clientEntry,
      renderModule,
      readObservations,
      writeObservations,
      parseObservation,
      kernel,
      dbPath,
    }).catch(() => {
      if (!response.headersSent) sendJson(response, 500, { error: 'internal_error' });
    });
  });

  await new Promise((resolve, reject) => {
    const onError = (error) => reject(error);
    server.once('error', onError);
    server.listen(context.listen.port, context.listen.host, () => {
      server.off('error', onError);
      resolve();
    });
  });

  let disposal;
  const dispose = () => {
    if (disposal) return disposal;
    context.signal.removeEventListener('abort', onAbort);
    disposal = new Promise((resolve, reject) => {
      server.close((error) => (error ? reject(error) : resolve()));
    });
    return disposal;
  };
  const onAbort = () => {
    void dispose().catch(() => undefined);
  };
  context.signal.addEventListener('abort', onAbort, { once: true });
  if (context.signal.aborted) await dispose();

  return { dispose };
}

/** Coerce the model output into the fixed observation-card shape. */
export function normalizeDraft(input) {
  const list = (value) => (Array.isArray(value) ? value.filter((v) => v !== null && v !== undefined) : []);
  const text = (value) => (typeof value === 'string' ? value.trim() : '');
  const direction = ['bullish', 'bearish', 'neutral'].includes(input.direction) ? input.direction : 'neutral';
  const rawConfidence = Number(input.confidence);
  const confidence = Number.isFinite(rawConfidence) ? Math.min(1, Math.max(0, rawConfidence)) : 0;
  const invalidation = list(input.invalidation).map(text).filter(Boolean);
  const evidence = list(input.evidence).map((item) => ({
    text: text(item?.text),
    type: item?.type === 'fact' ? 'fact' : 'assumption',
  })).filter((item) => item.text);

  return {
    symbol: text(input.symbol),
    name: text(input.name),
    thesis: text(input.thesis),
    direction,
    confidence,
    evidence,
    invalidation,
    // Single source of truth: the array itself. A model that supplies conditions but omits
    // the flag must not leave the card in the contradictory "has conditions AND missing" state.
    invalidation_missing: invalidation.length === 0,
    position: {
      entry: text(input.position?.entry),
      size: text(input.position?.size),
    },
    timeframe: text(input.timeframe),
    trigger: text(input.trigger),
  };
}
