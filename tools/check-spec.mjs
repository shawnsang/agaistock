/**
 * Design-spec self-check.
 *
 * Catches the three failure modes that actually bit the spec during drafting:
 *   1. leftover placeholders (TODO / TBD / 待补 / <占位>)
 *   2. dangling section references (§N.M where no such heading exists)
 *   3. malformed tables (rows whose column count disagrees with the header)
 *
 * Run:
 *   node tools/check-spec.mjs [spec.md]
 *   node tools/check-spec.mjs spec.md --external other-spec.md   # 跨文档引用
 *
 * Exit: 0 = clean, 1 = problems found
 */
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const args = process.argv.slice(2);
const specPath = resolve(args.find((a) => !a.startsWith('--')) ?? 'docs/superpowers/specs/2026-11-24-stock-review-app-architecture.md');
const externalPaths = args
  .map((a, index) => (a === '--external' ? args[index + 1] : null))
  .filter(Boolean)
  .map((p) => resolve(p));

const text = await readFile(specPath, 'utf8');
const lines = text.split(/\r?\n/);

const problems = [];
const notes = [];

/* ------------------------------------------------------------- placeholders */

const placeholderRules = [
  { name: 'TODO', re: /\bTODO\b/i },
  { name: 'TBD', re: /\bTBD\b/i },
  { name: 'FIXME', re: /\bFIXME\b/i },
  { name: 'XXX', re: /\bXXX\b/ },
  { name: '待补', re: /待补|待填|待定/g },
  { name: '占位符', re: /占位符|占位/g },
  { name: 'angle placeholder', re: /<[^>\n]{0,40}(填|待补|TODO|placeholder)[^>\n]{0,40}>/i },
];

lines.forEach((line, index) => {
  for (const rule of placeholderRules) {
    const re = new RegExp(rule.re.source, rule.re.flags);
    if (re.test(line)) {
      problems.push(`[占位符] L${index + 1} 命中「${rule.name}」: ${line.trim().slice(0, 90)}`);
    }
  }
});

/* ------------------------------------------------- headings and section refs */

const headingRe = /^(#{2,4})\s+(\d+(?:\.\d+)*)\.?\s+/;
const knownSections = new Set();
lines.forEach((line) => {
  const match = headingRe.exec(line);
  if (match) knownSections.add(match[2]);
});

// Cross-document references: sections that live in an external spec are legal references.
const externalSections = new Set();
for (const externalPath of externalPaths) {
  const externalText = await readFile(externalPath, 'utf8');
  for (const line of externalText.split(/\r?\n/)) {
    const match = headingRe.exec(line);
    if (match) externalSections.add(match[2]);
  }
}

const refRe = /§\s*(\d+(?:\.\d+)*)/g;
lines.forEach((line, index) => {
  const stripped = line.replace(/`[^`]*`/g, '');
  let match;
  refRe.lastIndex = 0;
  while ((match = refRe.exec(stripped)) !== null) {
    const ref = match[1];
    // A reference to §N may point at a parent of a known N.M; accept either exact or prefix match.
    const exact = knownSections.has(ref);
    const asParent = [...knownSections].some((section) => section.startsWith(`${ref}.`));
    const externalExact = externalSections.has(ref);
    const externalAsParent = [...externalSections].some((section) => section.startsWith(`${ref}.`));
    if (!exact && !asParent && !externalExact && !externalAsParent) {
      const known = [...knownSections].sort().join(', ');
      const external = externalSections.size ? `；外部文档：${[...externalSections].sort().join(', ')}` : '';
      problems.push(`[悬空引用] L${index + 1} §${ref} 在本文档与外部文档中都不存在（本文档：${known}${external}）`);
    }
  }
});

/* ------------------------------------------------------------ table shapes */

let inFence = false;
let tableHeaderColumns = null;
let tableStartLine = 0;

lines.forEach((line, index) => {
  if (/^\s*```/.test(line)) {
    inFence = !inFence;
    tableHeaderColumns = null;
    return;
  }
  if (inFence) return;

  const isRow = /^\s*\|.*\|\s*$/.test(line);
  if (!isRow) {
    tableHeaderColumns = null;
    return;
  }

  const columns = line.split('|').length - 2;
  if (tableHeaderColumns === null) {
    tableHeaderColumns = columns;
    tableStartLine = index + 1;
    if (columns < 2) {
      problems.push(`[表格] L${index + 1} 表格只有 ${columns} 列，疑似缺少分隔行`);
    }
    return;
  }
  if (columns !== tableHeaderColumns) {
    problems.push(`[表格] L${index + 1} 列数 ${columns} ≠ 表头 ${tableHeaderColumns}（表格起于 L${tableStartLine}）`);
  }
});

/* ------------------------------------------------------------------ report */

notes.push(`文件：${specPath}`);
notes.push(`行数：${lines.length}`);
notes.push(`已知章节号：${[...knownSections].sort((a, b) => a.localeCompare(b, undefined, { numeric: true })).join(', ')}`);
if (externalPaths.length) {
  notes.push(`外部文档（跨文档引用来源）：${externalPaths.map((p) => p.replace(/^.*[\\/]/, '')).join(', ')}`);
  notes.push(`外部章节号：${[...externalSections].sort((a, b) => a.localeCompare(b, undefined, { numeric: true })).join(', ')}`);
}

console.log(notes.join('\n'));
console.log('---');
if (problems.length === 0) {
  console.log('自检通过：无占位符、无悬空章节引用、表格列数一致。');
  process.exit(0);
}
console.log(`自检发现 ${problems.length} 个问题：`);
for (const problem of problems) console.log(problem);
process.exit(1);
