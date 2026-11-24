/**
 * Deterministic-layer tests for the observation-card pipeline.
 *
 * These cover the code that does NOT depend on a model: JSON extraction from a model reply
 * and the coercion of a loose model object into the fixed observation-card shape.
 *
 * Run:  node --test miniapps/agaistock/test/
 */
import assert from 'node:assert/strict';
import test from 'node:test';

import { extractJson, normalizeDraft } from '../miniapp/node/server.mjs';

/* ------------------------------------------------------------------ extractJson */

test('extractJson reads a bare JSON object', () => {
  assert.deepEqual(extractJson('{"a":1}'), { a: 1 });
});

test('extractJson reads a fenced JSON block', () => {
  assert.deepEqual(extractJson('```json\n{"a":1}\n```'), { a: 1 });
});

test('extractJson reads a fenced block without a language tag', () => {
  assert.deepEqual(extractJson('```\n{"a":1}\n```'), { a: 1 });
});

test('extractJson ignores prose around the object', () => {
  assert.deepEqual(extractJson('好的，结果如下：\n{"a":1}\n希望有帮助。'), { a: 1 });
});

test('extractJson keeps braces that live inside string values', () => {
  assert.deepEqual(extractJson('{"thesis":"还能拿{半年}"}'), { thesis: '还能拿{半年}' });
});

test('extractJson is not fooled by braces inside escaped strings', () => {
  assert.deepEqual(extractJson('{"thesis":"a \\" } b"}'), { thesis: 'a " } b' });
});

test('extractJson returns null when there is no object', () => {
  assert.equal(extractJson('我不知道这股票怎么样'), null);
});

test('extractJson returns null for malformed JSON rather than throwing', () => {
  assert.equal(extractJson('{"a": }'), null);
});

test('extractJson tolerates null and undefined input', () => {
  assert.equal(extractJson(null), null);
  assert.equal(extractJson(undefined), null);
});

/* --------------------------------------------------------------- normalizeDraft */

test('normalizeDraft keeps the model direction when it is valid', () => {
  assert.equal(normalizeDraft({ direction: 'bearish' }).direction, 'bearish');
});

test('normalizeDraft falls back to neutral for an unknown direction', () => {
  assert.equal(normalizeDraft({ direction: 'up' }).direction, 'neutral');
  assert.equal(normalizeDraft({ direction: undefined }).direction, 'neutral');
});

test('normalizeDraft clamps confidence into [0,1]', () => {
  assert.equal(normalizeDraft({ confidence: 1.7 }).confidence, 1);
  assert.equal(normalizeDraft({ confidence: -0.4 }).confidence, 0);
  assert.equal(normalizeDraft({ confidence: 0.72 }).confidence, 0.72);
});

test('normalizeDraft zeroes a non-numeric confidence', () => {
  assert.equal(normalizeDraft({ confidence: 'high' }).confidence, 0);
});

test('normalizeDraft trims string fields and blanks the absent ones', () => {
  const draft = normalizeDraft({ symbol: '  002378 ', name: ' 章源钨业 ', thesis: undefined });
  assert.equal(draft.symbol, '002378');
  assert.equal(draft.name, '章源钨业');
  assert.equal(draft.thesis, '');
});

test('normalizeDraft keeps only fact or assumption evidence types', () => {
  const draft = normalizeDraft({
    evidence: [
      { text: '钨价从去年就开始涨', type: 'fact' },
      { text: '明年上半年产量能翻倍', type: 'assumption' },
      { text: '主力在吸筹', type: 'rumor' },
      { text: '没有类型' },
    ],
  });
  assert.deepEqual(draft.evidence, [
    { text: '钨价从去年就开始涨', type: 'fact' },
    { text: '明年上半年产量能翻倍', type: 'assumption' },
    { text: '主力在吸筹', type: 'assumption' },
    { text: '没有类型', type: 'assumption' },
  ]);
});

test('normalizeDraft drops evidence entries with no text', () => {
  const draft = normalizeDraft({ evidence: [{ text: '   ' }, { text: '有效' }, null] });
  assert.equal(draft.evidence.length, 1);
  assert.equal(draft.evidence[0].text, '有效');
});

test('normalizeDraft marks a card with no invalidation condition as missing', () => {
  const draft = normalizeDraft({ invalidation: [] });
  assert.equal(draft.invalidation_missing, true);
});

test('normalizeDraft marks a card with invalidation conditions as complete', () => {
  const draft = normalizeDraft({ invalidation: ['跌破 MA20 即视为错误'], invalidation_missing: false });
  assert.equal(draft.invalidation_missing, false);
});

test('normalizeDraft does not leave a contradictory missing/present state', () => {
  // Conditions were supplied but the model omitted the flag: the array wins.
  const withFlagOmitted = normalizeDraft({ invalidation: ['跌破 MA20'] });
  assert.equal(withFlagOmitted.invalidation_missing, false);

  // Conditions were supplied but the model wrongly claimed they were missing: still the array wins.
  const withWrongFlag = normalizeDraft({ invalidation: ['跌破 MA20'], invalidation_missing: true });
  assert.equal(withWrongFlag.invalidation_missing, false);
});

test('normalizeDraft drops blank invalidation entries before deciding missingness', () => {
  const draft = normalizeDraft({ invalidation: ['', '   ', '跌破 MA20'] });
  assert.deepEqual(draft.invalidation, ['跌破 MA20']);
  assert.equal(draft.invalidation_missing, false);
});

test('normalizeDraft does not rewrite the timeframe the model produced', () => {
  // Timeframe fidelity is a prompt-level guarantee; normalization must not touch it.
  const draft = normalizeDraft({ timeframe: '半年' });
  assert.equal(draft.timeframe, '半年');
});

test('normalizeDraft keeps position sub-fields independent', () => {
  const draft = normalizeDraft({ position: { entry: '回踩 20 日线', size: '' } });
  assert.equal(draft.position.entry, '回踩 20 日线');
  assert.equal(draft.position.size, '');
});

test('normalizeDraft survives an empty model object', () => {
  const draft = normalizeDraft({});
  assert.equal(draft.symbol, '');
  assert.equal(draft.direction, 'neutral');
  assert.equal(draft.confidence, 0);
  assert.deepEqual(draft.evidence, []);
  assert.deepEqual(draft.invalidation, []);
  assert.equal(draft.invalidation_missing, true);
});
