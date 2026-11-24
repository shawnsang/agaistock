import { readFile, writeFile, mkdir, rename } from 'node:fs/promises';
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

export async function start(context) {
  const dataDir = context.dataDir;
  await mkdir(dataDir, { recursive: true });
  const observationsPath = join(dataDir, OBSERVATIONS_FILE);
  const clientEntry = await readFile(join(context.pluginRoot, 'miniapp/client/index.html'));

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

  const server = createServer((request, response) => {
    void handle(request, response).catch(() => {
      if (!response.headersSent) sendJson(response, 500, { error: 'internal_error' });
    });
  });

  async function handle(request, response) {
    const url = new URL(request.url ?? '/', 'http://miniapp.local');

    if (request.method === 'GET' && url.pathname === '/dashboard') {
      response.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
      response.end(clientEntry);
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
        observationCount: (await readObservations()).length,
      });
      return;
    }

    if (request.method === 'GET' && url.pathname === '/api/observations') {
      const items = await readObservations();
      sendJson(response, 200, { ok: true, items: items.slice().reverse() });
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

    sendJson(response, 404, { error: 'not_found' });
  }

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
