/** 纯渲染函数：从点评/评分/观察期数据生成 HTML 片段。 */

const SEVERITY_CLASS = {
  critical: 'sev-critical',
  high: 'sev-high',
  medium: 'sev-medium',
  low: 'sev-low',
  info: 'sev-info',
};

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

export function renderReviews(reviews) {
  if (!Array.isArray(reviews) || reviews.length === 0) {
    return '<p class="muted">还没有点评结论。</p>';
  }
  return reviews.map((review) => {
    const failed = review.status === 'error' || review.status === 'skipped';
    const findings = (review.findings || []).map((f) => `
      <li class="finding ${SEVERITY_CLASS[f.severity] ?? 'sev-info'}">
        <div class="finding-head">
          <span class="finding-claim">${escapeHtml(f.claim)}</span>
          <span class="finding-delta">${escapeHtml(f.delta)}</span>
        </div>
        <div class="finding-meta">${escapeHtml(f.dimension)} · ${escapeHtml(f.code)}</div>
        <div class="finding-why">${escapeHtml(f.why)}</div>
        ${f.suggested_fix ? `<div class="finding-fix">建议：${escapeHtml(f.suggested_fix)}</div>` : ''}
      </li>`).join('');

    // 「采纳」暂时禁用：采纳要写入 observation.invalidation，而观察记录只追加不修改，
    // 需要观察版本链（新版本行 + supersedes_id）—— 当前存储模型还没有版本链。
    // 一个点了没反应的按钮比一个明确禁用的按钮更糟，所以先禁用 + 说明。
    const invalidations = (review.proposed_invalidation || []).map((p) => `
      <li class="invalidation">
        <span>${escapeHtml(p.desc)}</span>
        <button type="button" data-adopt-invalidation="${escapeHtml(p.desc)}" disabled title="采纳需要观察版本链，本轮未实现">采纳</button>
      </li>`).join('');

    const caveats = (review.caveats || []).map((c) => `<li>${escapeHtml(c)}</li>`).join('');

    return `
      <details class="reviewer ${failed ? 'reviewer-failed' : ''}" ${failed ? 'open' : ''}>
        <summary>
          <span class="reviewer-id">${escapeHtml(review.reviewer_id)}</span>
          <span class="reviewer-count">${(review.findings || []).length} 条发现</span>
          ${failed ? '<span class="badge-failed">未成功运行</span>' : ''}
        </summary>
        ${failed ? `<p class="muted">该点评师未成功运行：${escapeHtml((review.caveats || []).join('；'))}</p>` : ''}
        ${findings ? `<ul class="finding-list">${findings}</ul>` : ''}
        ${invalidations ? `<div class="proposed"><h4>建议的证伪条件（需你确认）</h4><ul>${invalidations}</ul></div>` : ''}
        ${caveats ? `<div class="caveats"><h4>判读限制</h4><ul>${caveats}</ul></div>` : ''}
      </details>`;
  }).join('');
}

export function renderScore(score) {
  if (!score) return '';
  const denominator = Number(score.score_denominator ?? 0);
  const rows = (score.score_breakdown || []).map((entry) => {
    if (entry.completeness === 'no_reviewer') {
      return `<tr class="dim-empty">
        <td>${escapeHtml(entry.dimension)}</td>
        <td class="num">—</td>
        <td class="num">—</td>
        <td>无人点评</td>
      </tr>`;
    }
    const sources = (entry.contributions || [])
      .map((c) => `${escapeHtml(c.reviewer_id)}（${(c.finding_codes || []).map(escapeHtml).join('、')}）`)
      .join('；');
    return `<tr>
      <td>${escapeHtml(entry.dimension)}</td>
      <td class="num">${escapeHtml(entry.raw)}</td>
      <td class="num">${escapeHtml(entry.weight)}</td>
      <td>${sources || '—'}</td>
    </tr>`;
  }).join('');

  return `
    ${denominator > 0
      ? `<div class="score-total"><span class="num">${escapeHtml(Math.round(score.total ?? 0))}</span> / 100</div>`
      : '<div class="score-total muted">本次无人点评，未评分</div>'}
    <p class="muted">本次被审维度：${escapeHtml((score.scored_dimensions || []).join('、') || '无')}
       （权重和 ${escapeHtml(score.score_denominator ?? 0)}）</p>
    <table class="score-table">
      <thead><tr><th>维度</th><th>得分</th><th>权重</th><th>扣分来源</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

export function renderHorizon(plan) {
  if (!plan) return '';
  // rationale 必须一起显示：中枢在头顶时「跌破下沿」的条件**已经成立**，
  // 只作结构参考、不作为本次的失效判定 —— 不显示 rationale 会被读成待触发的失效条件。
  const checks = (plan.checks || []).map((c) => `<li>
      <span>${escapeHtml(c.desc)}</span>
      ${c.rationale ? `<div class="muted check-rationale">${escapeHtml(c.rationale)}</div>` : ''}
    </li>`).join('');
  // 结算日落在今天之前 ⇒ 已经到期。
  // 观察期锚在**线程起点**，所以补记一条旧观察时看到的日期可能已经在过去 ——
  // 不标出来，用户会以为是系统算错了。
  const reviewAt = plan.review_at || '';
  const overdue = Boolean(reviewAt) && reviewAt < todayIso();
  return `
    <div class="horizon-main">
      <strong>${escapeHtml(reviewAt)}</strong>
      <span class="muted">（档位 ${escapeHtml(plan.tier || '默认')}）</span>
      ${overdue ? '<span class="badge-failed">已到期</span>' : ''}
    </div>
    <p class="muted">${escapeHtml(plan.rationale || '')}</p>
    ${checks ? `<div class="horizon-checks"><h4>到期检查项</h4><ul>${checks}</ul></div>` : ''}`;
}

function todayIso() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

const DIRECTION_LABEL = { bullish: '看多', bearish: '看空', neutral: '中性' };

/** 时间戳 → 本地可读格式；解析不了就原样返回（不丢信息）。 */
function formatTime(value) {
  if (!value) return '';
  const when = new Date(value);
  return Number.isNaN(when.getTime())
    ? String(value)
    : when.toLocaleString('zh-CN', { hour12: false });
}

/**
 * 观察库表格行。
 *
 * 入参是**内核行**（Task 14 之后 /api/observations 走内核 list --json）：
 * id / created_at / symbol / name / direction / thesis / confidence。
 * Task 21 之后内核默认按**观察线程**返回 —— 一个标的一条持续观察 = 一行，
 * 行上还带 `version`（第几版）/ `version_count` / `first_seen_at`。
 * 删除按钮把内核行 id 放在 data-delete-observation 上，由 index.html 事件委托取出；
 * 内核按它把**整条线程**软删。
 */
export function renderObservationRows(items) {
  if (!Array.isArray(items) || items.length === 0) return '';
  return items.map(function (item) {
    const firstSeen = item.first_seen_at || item.created_at;
    const timeText = formatTime(firstSeen);
    const dir = 'dir-' + (item.direction || 'neutral');
    const label = DIRECTION_LABEL[item.direction] || item.direction || '中性';
    const evidence = Array.isArray(item.evidence) ? item.evidence : [];
    const invalidation = Array.isArray(item.invalidation) ? item.invalidation : [];
    const version = Number(item.version || 0);
    const versionText = version > 1 ? '第 ' + version + ' 版' : '初版';
    // 「最近更新」用**同一个**时间格式 —— 混着原始 ISO 串会让人以为两列口径不同。
    const updated = item.created_at && item.created_at !== firstSeen
      ? '<div class="sub">最近更新 ' + escapeHtml(formatTime(item.created_at)) + '</div>'
      : '';
    return '<tr>'
      + '<td class="num">' + escapeHtml(timeText) + updated + '</td>'
      + '<td class="num">' + escapeHtml((item.symbol || '—') + (item.name ? ' ' + item.name : '')) + '</td>'
      + '<td>' + escapeHtml(item.thesis || '（未提取）')
      + (evidence.length ? '<div class="sub">依据 ' + evidence.length + ' 条</div>' : '')
      + '</td>'
      + '<td><span class="tag ' + dir + '">' + escapeHtml(label) + '</span></td>'
      + '<td class="num">' + Math.round((item.confidence || 0) * 100) + '%</td>'
      + '<td>' + (invalidation.length
          ? escapeHtml(invalidation.join('；'))
          : '<span style="color:var(--mcode-warning)">缺失</span>') + '</td>'
      + '<td><span class="tag version-tag">' + escapeHtml(versionText) + '</span></td>'
      + '<td><button type="button" class="ghost small" data-delete-observation="'
        + escapeHtml(item.id || '') + '">删除</button></td>'
      + '</tr>';
  }).join('');
}

/**
 * 前几轮的点评（Task 21）。
 *
 * 续接把新输入并进同一条观察线程，历史点评因此可以一并显示 ——
 * 用户能看到「上一轮点评师说了什么、这一轮改了什么」。
 */
export function renderReviewHistory(history) {
  if (!Array.isArray(history) || history.length === 0) return '';
  const rounds = history.map(function (entry) {
    const reviews = Array.isArray(entry.reviews) ? entry.reviews : [];
    const when = entry.created_at ? new Date(entry.created_at) : null;
    const timeText = when && !Number.isNaN(when.getTime())
      ? when.toLocaleString('zh-CN', { hour12: false })
      : (entry.created_at || '');
    return '<details class="review-round">'
      + '<summary>'
      + '<span class="round-label">第 ' + escapeHtml(entry.version || '?') + ' 版</span>'
      + '<span class="muted">' + escapeHtml(timeText) + '</span>'
      + '<span class="reviewer-count">' + reviews.length + ' 位点评师</span>'
      + '</summary>'
      + (reviews.length
          ? renderReviews(reviews)
          : '<p class="muted">这一轮没有点评结论。</p>')
      + '</details>';
  }).join('');
  return '<h3 class="history-title">前几轮的点评</h3>' + rounds;
}

// 供 index.html 的主脚本调用（module 脚本是 deferred，用户点击时必定已就绪）。
// Node 里没有 window —— 直接赋值会让 import 该模块的测试在第一条用例前就抛
// ReferenceError，所以必须先判断。
if (typeof window !== 'undefined') {
  window.agaistockRender = {
    renderReviews,
    renderScore,
    renderHorizon,
    renderObservationRows,
    renderReviewHistory,
  };
}
