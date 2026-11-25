import assert from 'node:assert/strict';
import test from 'node:test';

import { renderReviews, renderScore, renderHorizon, renderObservationRows, renderReviewHistory } from '../miniapp/client/render.mjs';

const REVIEW = {
  reviewer_id: 'anchor-chanlun',
  status: 'ok',
  findings: [
    {
      code: 'CHAN_DAY_TOP_DIVERGENCE',
      severity: 'critical',
      dimension: '位置与时机',
      delta: -12,
      claim: '日线顶背驰成立',
      why: '与大级别动能背离',
      suggested_fix: '降级为反弹参与',
    },
  ],
  proposed_invalidation: [
    { desc: '跌破日线中枢下沿 22.39', comparator: 'below', source: 'chan.pivot.ZD' },
  ],
  caveats: ['背驰 active 不代表仍成立'],
};

test('renderReviews shows reviewer id, claim, dimension and delta', () => {
  const html = renderReviews([REVIEW]);
  assert.match(html, /anchor-chanlun/);
  assert.match(html, /日线顶背驰成立/);
  assert.match(html, /位置与时机/);
  assert.match(html, /-12/);
});

test('renderReviews shows proposed invalidation with adopt button', () => {
  const html = renderReviews([REVIEW]);
  assert.match(html, /跌破日线中枢下沿 22\.39/);
  assert.match(html, /data-adopt-invalidation/);
});

test('renderReviews shows caveats', () => {
  const html = renderReviews([REVIEW]);
  assert.match(html, /背驰 active 不代表仍成立/);
});

test('renderReviews marks failed reviewer', () => {
  const html = renderReviews([{ ...REVIEW, status: 'error', findings: [], caveats: ['炸了'] }]);
  assert.match(html, /未成功运行/);
});

test('renderScore marks no_reviewer dimension explicitly', () => {
  // 本轮只有 anchor-chanlun 一个点评师：它贡献「证伪条件」与「位置与时机」，
  // 其余三个维度恒为 no_reviewer，从加权平均的分子分母一并剔除（设计文档 §5.2）。
  // 所以实际分母是 0.25 + 0.15 = 0.40，不是 1.0。
  const score = {
    total: 88,
    score_breakdown: [
      { dimension: '位置与时机', weight: 0.15, raw: 88, weighted: 13.2, completeness: 'ok', contributions: [] },
      { dimension: '证伪条件', weight: 0.25, raw: 92, weighted: 23, completeness: 'ok', contributions: [] },
      { dimension: '事实锚定', weight: 0.25, raw: null, weighted: null, completeness: 'no_reviewer', contributions: [] },
    ],
    scored_dimensions: ['位置与时机', '证伪条件'],
    score_denominator: 0.4,
  };
  const html = renderScore(score);
  assert.match(html, /无人点评/);
  assert.match(html, /位置与时机/);
  assert.match(html, /88/);
});

test('renderHorizon shows tier and review date', () => {
  const html = renderHorizon({ tier: 'short', review_at: '2026-11-27', rationale: '顶背驰', checks: [] });
  assert.match(html, /2026-11-27/);
  assert.match(html, /顶背驰/);
});

test('renderScore says 未评分 instead of 0 when no dimension was scored', () => {
  // 「无人点评 ≠ 0 分」：一个维度都没被审过时显示「0 / 100」会被读成「总分很差」，
  // 与设计文档 §5.2 的口径正好相反。
  const html = renderScore({
    total: 0,
    score_breakdown: [
      { dimension: '事实锚定', weight: 0.25, raw: null, weighted: null, completeness: 'no_reviewer', contributions: [] },
      { dimension: '证伪条件', weight: 0.25, raw: null, weighted: null, completeness: 'no_reviewer', contributions: [] },
    ],
    scored_dimensions: [],
    score_denominator: 0,
  });
  assert.match(html, /未评分/);
  assert.doesNotMatch(html, /0\s*<\/span>\s*\/ 100/);
});

test('renderHorizon shows the check rationale', () => {
  // 中枢在头顶时「跌破下沿」的条件已经成立，只作结构参考 —— rationale 必须显示，
  // 否则用户会把它当成待触发的失效条件。
  const html = renderHorizon({
    tier: 'mid',
    review_at: '2026-12-01',
    rationale: '按中期档',
    checks: [
      {
        desc: '跌破 day 中枢下沿 60.47',
        comparator: 'below',
        tolerance: 0.5,
        rationale: 'day 中枢位于现价上方，跌破下沿属于已发生的事实，只作结构失效参考',
      },
    ],
  });
  assert.match(html, /跌破 day 中枢下沿 60\.47/);
  assert.match(html, /只作结构失效参考/);
});

test('renderObservationRows renders kernel observation rows', () => {
  const html = renderObservationRows([
    {
      id: 'obs_1',
      created_at: '2026-11-24T07:00:00Z',
      symbol: '002378',
      name: '章源钨业',
      direction: 'bullish',
      thesis: '还能拿半年',
      confidence: 0.72,
    },
  ]);
  assert.match(html, /002378/);
  assert.match(html, /章源钨业/);
  assert.match(html, /还能拿半年/);
  assert.match(html, /看多/);
  assert.match(html, /72%/);
});

test('renderObservationRows shows the real confidence and invalidation', () => {
  const html = renderObservationRows([{
    id: 'obs_1', created_at: '2026-11-24T07:00:00Z', symbol: '002378', name: '章源钨业',
    direction: 'bullish', thesis: '钨价上涨', confidence: 0.75,
    evidence: [{ text: '钨价从去年就开始涨', type: 'fact' }],
    invalidation: ['钨价跌回去年年底的水平'],
  }]);
  assert.match(html, /75%/);
  assert.match(html, /钨价跌回去年年底的水平/);
  assert.match(html, /依据 1 条/);
});

test('renderObservationRows puts the kernel row id on the delete button', () => {
  const html = renderObservationRows([
    { id: 'obs_1', created_at: '2026-11-24T07:00:00Z', symbol: '002378', thesis: 't' },
  ]);
  assert.match(html, /data-delete-observation="obs_1"/);
});

test('renderObservationRows shows the version of a continued observation', () => {
  // Task 21：观察库一行 = 一个标的的一条持续观察，行上标「第 N 版」。
  const html = renderObservationRows([
    {
      id: 'obs_2', created_at: '2026-11-25T07:00:00Z', first_seen_at: '2026-11-24T07:00:00Z',
      symbol: '002378', name: '章源钨业', thesis: '产量翻倍确认', version: 2, version_count: 2,
    },
  ]);
  assert.match(html, /第 2 版/);
});

test('renderObservationRows shows 初版 for a first-time observation', () => {
  const html = renderObservationRows([
    { id: 'obs_1', created_at: '2026-11-24T07:00:00Z', symbol: '002378', thesis: 't', version: 1 },
  ]);
  assert.match(html, /初版/);
});

test('renderObservationRows uses the first-seen time of the thread', () => {
  const html = renderObservationRows([
    {
      id: 'obs_2', created_at: '2026-11-25T07:00:00Z', first_seen_at: '2026-11-24T07:00:00Z',
      symbol: '002378', thesis: 't', version: 2,
    },
  ]);
  assert.match(html, /2026/);
  assert.match(html, /最近更新/);
});

test('renderReviewHistory renders the previous rounds', () => {
  const html = renderReviewHistory([
    {
      observation_id: 'obs_1', version: 1, created_at: '2026-11-24T07:00:00Z',
      reviews: [{ reviewer_id: 'anchor-chanlun', status: 'ok', findings: [], caveats: [] }],
    },
  ]);
  assert.match(html, /前几轮的点评/);
  assert.match(html, /第 1 版/);
  assert.match(html, /anchor-chanlun/);
});

test('renderReviewHistory returns nothing when there is no history', () => {
  assert.equal(renderReviewHistory([]), '');
  assert.equal(renderReviewHistory(undefined), '');
});

test('renderHorizon marks a review date that is already due', () => {
  // 观察期锚在**线程起点**：补记一条旧观察时结算日可能已经在过去，
  // 不标出来用户会以为是系统算错了。
  const html = renderHorizon({ tier: 'mid', review_at: '2020-01-02', rationale: 'x', checks: [] });
  assert.match(html, /已到期/);
});

test('renderHorizon does not mark a future review date as due', () => {
  const html = renderHorizon({ tier: 'mid', review_at: '2999-01-02', rationale: 'x', checks: [] });
  assert.doesNotMatch(html, /已到期/);
});
