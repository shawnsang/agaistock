/**
 * 数据源覆盖度探测（Provider Coverage Probe）
 *
 * 逐条调用已验证的连接器取数，校验「拿到的是不是对题的数据」，并输出一份覆盖度报告。
 * 这是 §6.7 取数可行性验证结论的可复现版本 —— 换标的、改参数后重跑即可。
 *
 * 用法：
 *   node tools/probe/run-probe.mjs                 # 用默认标的 002378 章源钨业
 *   node tools/probe/run-probe.mjs --symbol 600519 --name 贵州茅台 --setcode 1
 *   node tools/probe/run-probe.mjs --out report.json
 *
 * 退出码：0 = 全部探针命中；1 = 有探针未命中（需人工判读）。
 */
import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

const argv = process.argv.slice(2);
const argOf = (flag, fallback) => {
  const index = argv.indexOf(flag);
  return index >= 0 && argv[index + 1] ? argv[index + 1] : fallback;
};

const SYMBOL = argOf('--symbol', '002378');
const NAME = argOf('--name', '章源钨业');
const SETCODE = argOf('--setcode', '0');
const OUT = argOf('--out', null);
const ONLY = argOf('--only', null);

/**
 * 每条探针：
 *   id       唯一标识
 *   label    人类可读说明
 *   tool     连接器工具名
 *   args     调用参数
 *   expect   正则。必须在返回文本中命中，否则判定为「未命中」。
 *   note     命中含义 / 已知限制
 */
const PROBES = [
  {
    id: 'quotes',
    label: '实时行情 + 估值快照',
    tool: 'connector__tdx-finance__tdx_quotes',
    args: { code: SYMBOL, setcode: SETCODE },
    expect: /"Now"|现价/,
    note: 'ExtInfo 内含 PE/EPS/BVPS/股息率/总市值/总股本/流通股本/换手率',
  },
  {
    id: 'kline-hfq',
    label: '日K线（后复权）',
    tool: 'connector__tdx-finance__tdx_kline',
    args: { code: SYMBOL, setcode: SETCODE, period: '4', tqFlag: '2', wantNum: 30 },
    expect: /Close|收盘/,
    note: 'D6 口径：后复权序列；tqFlag=2',
  },
  {
    id: 'capital-flow',
    label: '⑥资金流 + 复权因子',
    tool: 'connector__tdx-finance__tdx_api_data',
    args: { entry: 'TdxSharePCCW.tdxf10_gg_jyds', fixedTag: 'zjlx', code: SYMBOL },
    expect: /主力净额|超大单/,
    note: '同时返回 adjustment_factor 表 —— D6 复权因子落库的来源',
  },
  {
    id: 'holder-count',
    label: '⑦股东人数 / 人均流通股',
    tool: 'connector__tdx-finance__tdx_api_data',
    args: { entry: 'TdxSharePCCW.tdxf10_gg_gdyj', fixedTag: 'gdrs', code: SYMBOL, pageNo: '1', pageSize: '20' },
    expect: /股东人数/,
    note: '季度披露，可回溯多期',
  },
  {
    id: 'top-float',
    label: '十大流通股东',
    tool: 'connector__tdx-finance__tdx_api_data',
    args: { entry: 'TdxSharePCCW.tdxf10_gg_gdyj', fixedTag: 'ltgd', code: SYMBOL, pageNo: '1', pageSize: '10' },
    expect: /流通/,
    note: '含「实际流通A股」分母，可算十大流通合计占比',
  },
  {
    id: 'margin',
    label: '融资融券余额',
    tool: 'connector__tdx-finance__tdx_security_deep_info',
    args: { query: `查询 ${SYMBOL} ${NAME} 的融资融券余额近 60 个交易日序列`, entity_type: 'A股代码' },
    expect: /融资余额/,
    note: '⚠ 月度频率（披露制度决定），非日频',
  },
  {
    id: 'concept',
    label: '所属概念板块',
    tool: 'connector__tdx-finance__tdx_security_deep_info',
    args: { query: `查询 ${SYMBOL} ${NAME} 的所属概念板块完整列表`, entity_type: 'A股代码' },
    expect: /所属概念板块/,
    note: '⚠ deep_info 自然语言入口仅限已验证映射使用',
  },
  {
    id: 'ifind-valuation',
    label: '⑤估值现值 + 近三年分位',
    tool: 'connector__thsifind__get_security_indicators',
    args: { market: 'A股', query: `${SYMBOL} ${NAME} 最新一期PE(TTM)、PB、PS(TTM)、PCF(TTM)以及各自近三年百分位` },
    expect: /市盈率|PE/i,
    note: '⚠ 单次请求指标数 ≤ 5，超限会静默降级',
  },
  {
    id: 'ifind-financial',
    label: '⑤财务分析指标',
    tool: 'connector__thsifind__get_security_indicators',
    args: { market: 'A股', query: `${SYMBOL} ${NAME} 最新一期报告期的ROE(加权)、销售毛利率、销售净利率、资产负债率、归母净利润同比增长率、每股收益EPS` },
    expect: /净资产收益率|ROE/,
    note: '⚠ 同上，≤5 指标/次',
  },
  {
    id: 'ifind-ddx',
    label: '⑥DDX 家族（DDE 大单净量/净额 + 5日/10日）',
    tool: 'connector__thsifind__get_security_indicators',
    args: { market: 'A股', query: `${SYMBOL} ${NAME} 最近45个交易日的DDX大单动向指标、DDY大单_diff、DDZ大单_z值，以及主力净流入占比、换手率` },
    expect: /DDE|大单/,
    note: '⚠ 实返 DDE大单净量/DDE大单净额/5日DDE/10日DDE；3日窗口与DDY需自建',
  },
];

/**
 * 调用连接器。
 *
 * 两个 Windows 约束（实测，§6.7.5）：
 *   1. `mcode-tools` 是 .cmd 批处理包装 → spawnSync 必须开 shell，否则 ENOENT
 *   2. `--args '{...}'` 的双引号会被 shell 剥离 → 必须用 --args-file
 * 走临时文件而非 stdin，因为 stdin 穿 cmd.exe 链路不可靠。
 */
const argDir = mkdtempSync(join(tmpdir(), 'agaistock-probe-'));
let argSeq = 0;

function callConnector(tool, args) {
  const argFile = join(argDir, `args-${(argSeq += 1)}.json`);
  writeFileSync(argFile, JSON.stringify(args), 'utf8');

  const result = spawnSync('mcode-tools', ['connector', 'call', tool, '--args-file', argFile], {
    shell: true,
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
  });

  if (result.error) return { ok: false, text: '', error: String(result.error.message ?? result.error) };
  if (result.status !== 0) {
    const stderr = String(result.stderr ?? '');
    const tail = stderr
      .split('\n')
      .filter((line) => line.trim() && !line.includes('UNDICI-EHPA') && !line.includes('trace-warnings'))
      .join(' | ');
    return { ok: false, text: '', error: tail || `exit=${result.status}` };
  }
  const stdout = String(result.stdout ?? '').trim();
  let text = stdout;
  try {
    const parsed = JSON.parse(stdout);
    if (Array.isArray(parsed) && parsed[0]?.type === 'text') text = parsed[0].text;
    else if (typeof parsed === 'string') text = parsed;
  } catch {
    // 非 JSON，原样作为文本
  }
  return { ok: true, text };
}

const probes = ONLY ? PROBES.filter((p) => p.id === ONLY) : PROBES;
if (probes.length === 0) {
  console.error(`没有匹配 --only=${ONLY} 的探针。可用：${PROBES.map((p) => p.id).join(', ')}`);
  process.exit(1);
}

console.log(`数据源覆盖度探测 · ${SYMBOL} ${NAME} (setcode=${SETCODE})`);
console.log('='.repeat(72));

const results = [];
for (const probe of probes) {
  const started = Date.now();
  const call = callConnector(probe.tool, probe.args);
  const elapsed = Date.now() - started;
  const hit = call.ok && probe.expect.test(call.text);
  const status = !call.ok ? 'ERROR' : hit ? 'HIT' : 'MISS';
  results.push({ id: probe.id, label: probe.label, status, elapsed, note: probe.note, error: call.error ?? null });

  const mark = status === 'HIT' ? '✔' : status === 'MISS' ? '✖' : '!';
  console.log(`${mark} [${status.padEnd(5)}] ${probe.id.padEnd(18)} ${String(elapsed).padStart(5)}ms  ${probe.label}`);
  if (!call.ok) console.log(`      错误: ${call.error}`);
  else if (!hit) console.log(`      未命中预期模式 ${probe.expect} —— 返回前 300 字符:\n      ${call.text.slice(0, 300).replace(/\n/g, '\n      ')}`);
}

const hits = results.filter((r) => r.status === 'HIT').length;
console.log('='.repeat(72));
console.log(`命中 ${hits}/${results.length}`);

if (OUT) {
  const report = { symbol: SYMBOL, name: NAME, setcode: SETCODE, at: new Date().toISOString(), hits, total: results.length, results };
  writeFileSync(resolve(OUT), `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  console.log(`报告已写入: ${resolve(OUT)}`);
}

rmSync(argDir, { recursive: true, force: true });

process.exit(hits === results.length ? 0 : 1);
