/**
 * 临时：把 mcode-tools 的 tdx_kline 返回落到本地 JSON，并抽出 Rows。
 * 仅用于验证上游缠论脚本能否在当前环境下跑通。
 */
import { spawnSync } from 'node:child_process';
import { writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const argDir = mkdtempSync(join(tmpdir(), 'agaistock-verify-'));
const argsFile = join(argDir, 'args.json');
writeFileSync(argsFile, JSON.stringify({ code: '002378', setcode: '0', period: '4', wantNum: 500 }), 'utf8');

const res = spawnSync('mcode-tools', ['connector', 'call', 'connector__tdx-finance__tdx_kline', '--args-file', argsFile], {
  shell: true,
  encoding: 'utf8',
  maxBuffer: 64 * 1024 * 1024,
});
if (res.status !== 0) {
  console.error('调用失败:', res.stderr?.slice(0, 500));
  process.exit(1);
}
const wrapper = JSON.parse(res.stdout.trim());
const text = wrapper[0].text;
const start = text.indexOf('{');
const payload = JSON.parse(text.slice(start));

writeFileSync('D:/workroom/agaistock/.tmp/tdx_day.json', JSON.stringify(payload, null, 2), 'utf8');
console.log('Rows 根数:', payload.Rows?.length);
console.log('首行:', JSON.stringify(payload.Rows?.[0]));
console.log('末行:', JSON.stringify(payload.Rows?.[payload.Rows.length - 1]));
console.log('ListHead:', JSON.stringify(payload.ListHead));
