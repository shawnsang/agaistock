# 点评师层与缠论点评师 · 设计文档

> 状态：待用户评审
> 日期：2026-11-24
> 上游规格：`docs/superpowers/specs/2026-11-24-stock-review-app-architecture.md`（下称「主规格」）
> 复用资产：`C:\Users\shawn\.workbuddy\plugins\marketplaces\my-experts\plugins\chanlun-analyst`

---

## 1. 背景与目标

### 1.1 问题

主规格的闭环是「口述观察 → 结构化记录 → 多镜审阅 → 自适应观察期 → 跟踪结算 → 认知档案」。
其中的「多镜审阅」目前被建模为**固定的 5 个 skill**（`audit-fact` / `audit-logic` / `audit-falsification` / `audit-bias` / `anchor-7dim`）。这带来两个限制：

1. **不能持续上新**。每加一位新的审阅者，都要改 §5.2 的表、改 §5.3 的判定来源表，还要考虑评分口径是否变化。
2. **审阅结论不落库**。目前 `Finding[]` 只是当次流程中的中间产物，用完即弃。用户看不到"当时到底被怎么评的"，认知档案也没有原料做长期统计。

### 1.2 目标

把「多镜审阅」升级为**可插拔的「点评师」层**：

- 点评师是一个**有统一契约的组件**，新增点评师 = 新增一个目录 + 一条注册记录，**不改评分口径**。
- **每位点评师的结论都落库**，可回看、可统计、可追溯。
- 所有点评师的结论**一起进入评分与观察期**。
- 第一位上线的点评师是**缠论**（`anchor-chanlun`），复用用户既有的 `chanlun-analyst` 资产。

### 1.3 同时交付的独立需求

- **观察卡内容可删除**（软删除，见 §7）。

### 1.4 非目标（本轮不做）

- `audit-fact` / `audit-logic` / `audit-bias` 迁入点评师框架（框架先立，迁移后做）。
- 认知档案看板、批量复盘模式。
- 点评师的自注册/热加载（本期用静态注册表）。

---

## 2. 点评师契约

### 2.1 ReviewVerdict

所有点评师输出同一结构。**规则层产出判定，LLM 层只产出措辞**（§10）。

```jsonc
{
  "reviewer_id": "anchor-chanlun",       // 全局唯一
  "reviewer_version": "0.1.0",
  "ran_at": "2026-11-24T07:30:00Z",
  "status": "ok",                        // ok | partial | skipped | error
  "duration_ms": 8420,

  // 取数留痕：取了哪些源、什么参数、什么窗口、何时取的
  "data_refs": [
    { "source": "tdx_kline", "params": { "code": "002378", "period": "4", "wantNum": 500 },
      "window": "2024-11-18~2026-11-24", "fetched_at": "2026-11-24T07:29:41Z" }
  ],

  // 结构化发现。每条必须能定位到一个维度并给出分差。
  "findings": [
    {
      "code": "CHAN_DAY_TOP_DIVERGENCE",
      "severity": "critical",              // critical | high | medium | low | info
      "dimension": "位置与时机",           // 必须是主规格 §5.3 定义的维度
      "delta": -12,                        // 该维度分差（负=扣分，正=加分）
      "claim": "日线顶背驰成立（MACD 面积比 0.70）",
      "why": "你的看多主张与大级别动能背离。按纪律二，小级别信号在大级别未背书时只能定性为反弹",
      "evidence_ref": ["chan.levels.day.recent_divergence"],
      "suggested_fix": "把主张降级为『反弹参与』，或等周线底背驰背书后再加仓"
    }
  ],

  // 建议的证伪条件。只建议，不自动写入 observation —— 需用户确认。
  "proposed_invalidation": [
    { "desc": "跌破日线中枢下沿 12.01", "source": "chan.levels.day.nearby_pivots[].ZD",
      "comparator": "below", "tolerance": 0.5,
      "rationale": "中枢下沿是本级别结构的失效位" }
  ],

  // 对观察期的建议：只能给档位上限，不能给具体天数
  "horizon_hint": {
    "tier": "short",                      // short | mid | long | event
    "rationale": "日线顶背驰成立、30 分钟未见同向确认 → 属短线信号，不支持 20 日以上观察期",
    "checks": [
      { "id": "c1", "desc": "跌破日线中枢下沿 12.01", "source": "chan.pivot.ZD",
        "comparator": "below", "tolerance": 0.5 }
    ]
  },

  // 限制声明。缠论的 25 条纪律主要落在这里，必须随结论一起落库。
  "caveats": [
    "背驰 active 标签仅表示锚点落在背驰窗口内，不代表背驰仍然成立；须复核价格是否已突破锚点、新一笔动能是否同步放大",
    "周线窗口仅识别出 2 个中枢（样本偏薄），依赖周线中枢的关键价位置信度折损"
  ]
}
```

### 2.2 契约的硬性要求

| 要求 | 理由 |
|---|---|
| **不输出自由文本作为主要结论** | 自由文本无法聚合评分、无法做统计、无法累积认知档案（主规格 §5.2 已有此结论） |
| **每条 finding 必须有 `dimension` + `delta`** | 评分聚合完全依赖这两个字段；缺失即视为该点评师输出不合法 |
| **`dimension` 必须是已定义维度** | 评分口径跨期可比的前提。新增维度必须显式改 `config/scoring.json`，不允许隐式扩张（见 §5.1） |
| **`caveats` 不得为空（若有适用纪律）** | 限制声明缺失 = 把机械结论当结论，是本产品最容易产生的误导 |
| **`proposed_invalidation` 不得直接写进 observation** | 用户口述的证伪条件是用户自己的判断标准，被点评师改写会破坏校准统计的归因（主规格 §5.5） |

### 2.3 点评师接口

业务内核内，点评师是可注册的 Python 模块：

```python
class Reviewer:
    id: str
    version: str
    def review(self, ctx: ReviewContext) -> ReviewVerdict: ...
```

`ReviewContext` 携带：

- `observation: ObservationDraft` —— 用户的观察卡
- `symbol` / `name` / `now`
- `data_dir` —— 落盘目录
- `cache` —— 行情/财务缓存访问器
- `llm: LlmPort | None` —— 措辞层端口；`None` 表示只出规则结论
- `prior_reviews: list[ReviewVerdict]` —— 该观察已有的其它点评师结论（点评师可互相参考，但**不得改写**彼此结论）

---

## 3. 注册表与生命周期

### 3.1 目录结构

```
D:\workroom\agaistock\
├── src/agaistock/
│   ├── providers/
│   │   ├── tdx_rows_to_em.py            ← tdx_kline Rows → 东财格式（重写，见 §9.3）
│   │   ├── tdx.py                       ← 通达信取数（含后复权口径收口）
│   │   └── mcode_cli.py                 ← 连接器调用桥
│   ├── reviewers/
│   │   ├── contract.py                  ← ReviewVerdict / ReviewContext 定义
│   │   ├── registry.py                  ← 静态注册表 + 发现
│   │   └── engine.py                    ← 调度、并发、落库
│   ├── skills/                          ← 点评师（可插拔）
│   │   └── anchor_chanlun/              ← 目录名用下划线（Python 模块名不能带连字符）
│   │       ├── reviewer.py               ← Reviewer 实现（入口）
│   │       ├── engine.py                 ← 结构构建（适配上游产物格式）
│   │       ├── rules.py                  ← 纯规则层：结构 + 观察卡 → findings（可单测）
│   │       ├── signals.py                ← proposed_invalidation / horizon_hint 生成
│   │       ├── wording.py                ← LLM 措辞层
│   │       └── vendor/chanlun-core/      ← 上游拷贝，保持可追溯（只读不改）
│   │           ├── SKILL.md                ← 上游 skill 说明（25 条纪律的来源）
│   │           ├── scripts/                ← chan_analyze.py / chan_multi_level.py / ...
│   │           ├── references/             ← glossary.md / tdx-mcp-reference.md
│   │           └── templates/              ← 上游报告模板与 inline_data 模板
│   ├── llm/client.py                    ← LLM 措辞调用（§10）
│   ├── scoring.py                       ← 维度聚合（§5）
│   ├── horizon.py                       ← 观察期（§6）
│   ├── config.py                        ← repo_root() / 配置加载
│   ├── cli.py                           ← 唯一对外入口（stdin/stdout JSON）
│   └── storage/
│       └── db.py                        ← SQLite，含 reviews 表 + deleted_at
│   （每个包目录都另有 `__init__.py`：agaistock / llm / providers / reviewers /
│     skills / skills/anchor_chanlun / storage）
├── config/
│   ├── reviewers.json                   ← 点评师注册表（§3.2）
│   └── scoring.json                     ← 五维与权重（§5.1）
├── tools/sync-kernel.py                 ← 内核随包复制 + 漂移守卫（见 §16.2）
└── miniapps/agaistock/                  ← Mini App（§8）
    ├── miniapp/miniapp.json             ← Mini App 清单
    ├── miniapp/node/server.mjs          ← HTTP 路由 + 内核子进程桥
    ├── miniapp/client/index.html        ← 页面
    ├── miniapp/client/render.mjs        ← 渲染层（点评 / 评分 / 观察期 / 观察库）
    ├── src/agaistock/**、config/**       ← 内核与配置的逐字节副本（随包走）
    ├── test/*.test.mjs                  ← node --test 用例
    ├── package.json、icon.png、.minimax-plugin/plugin.json   ← 插件打包清单与图标
    └── （包内**没有**运行数据目录）                            ← 数据库与缠论分析工作目录都落宿主的 `context.dataDir`（§16.2）
```

> **「没有运行数据目录」说的是数据，不是字节码**：包内运行时仍会累积 `__pycache__`
> 字节码（无害：只读安装时 CPython 容忍 `.pyc` 写失败，终审实测内核仍 exit 0
> 且输出 JSON 有效）。
>
> ⚠️ 括号里「只读安装时 CPython 容忍 `.pyc` 写失败」这条**尚未独立复现**：
> Windows 的只读**属性**不阻断写入，要验只能在 POSIX 的只读安装上做。
> 本仓库的 Windows 环境**验不了**这条，所以它现在只是历史结论，不是已验证事实。

**与初稿的三处偏离（以实现为准）**：

1. **点评师放在 `src/agaistock/skills/` 下，而不是仓库根的 `skills/`**。理由：Mini App 的宿主会把插件包解到临时目录运行，业务内核必须随包走（§16.2）；点评师是内核的一部分，放在包内才能被内核 import。
2. **没有适配层 `SKILL.md`**。本轮第一位点评师 `anchor-chanlun` 是内核内的 Python 包，不是 Host skill，因此不需要 skill 描述文件；上游的 `SKILL.md` 作为只读 vendor 资产保留（其 25 条判读纪律是规则层的来源）。
3. **`src/agaistock/mcp/` 尚未实现**。本轮 MCP 暴露面只有 Mini App 的 Node 侧 HTTP 路由；`agaistock-mcp` 工具暴露列入下一轮。

### 3.2 注册表

静态注册表（`src/agaistock/reviewers/registry.py`）。每个点评师在 `config/reviewers.json` 声明：

```json
{
  "reviewers": [
    {
      "id": "anchor-chanlun",
      "enabled": true,
      "module": "agaistock.skills.anchor_chanlun.reviewer",
      "weight": 1.0
    }
  ]
}
```

> **配置用 JSON 不用 YAML**（主规格 D4）：业务内核零第三方依赖，YAML 要 PyYAML。
> `module` 是相对于 `agaistock` 包根的模块路径。
> `weight` 的语义：点评师在某维度内贡献 `delta` 时乘上的系数。同一维度有多家点评师时，各自 `delta × weight` 后归一化。这样某位点评师可以"轻一点"（例如 `audit-timing` 只提供参考）而不改维度本身的权重。

### 3.3 生命周期

```
保存观察卡
   ↓
engine.run_reviews(observation_id)
   ├─ 逐个点评师执行（可并发，但落库必须串行）
   ├─ 失败隔离：单个点评师 error 不影响其它点评师
   │    → 该点评师落一条 status='error' 的记录，附 error 摘要
   └─ 全部落库 reviews 表
   ↓
scoring.aggregate(observation_id)   ← 读所有点评师最新结论
   ↓
horizon.plan(observation_id)        ← 读 horizon_hint + proposed_invalidation
```

**每个点评师的失败都被隔离**：一位点评师挂了，观察仍有评分（该维度按剩余点评师归一化），并在 UI 上明确显示"该点评师未成功运行"。

### 3.4 结构化观察的数据流（接入层 → 内核）

**观察卡是由「接入层」解析出来的，不是内核解析的。** 内核只接收已经结构化的观察，
不自己猜用户说了什么：

```
用户口述
   ↓
接入层（Mini App 的 LLM 层）解析
   ↓  结构化草稿：symbol / name / thesis / direction / confidence /
   ↓              evidence[] / invalidation[] / position / timeframe / trigger
   ↓
内核接收并**逐字段校验**（不信模型输出的每一个字段）
   ↓
observations 表落库
   ↓
点评师拿结构化观察去对照客观结构
```

- **草稿经文件传给内核**（`--observation-file <path>`），不拼在命令行里 ——
  口述原文可能很长，Windows 命令行长度有上限。
- **内核逐字段校验**：方向只认 `bullish/bearish/neutral`；信心夹到 `[0,1]`；
  `evidence[].type` 只认 `fact/assumption`；证伪条件只留非空字符串。
  不合法的字段**退回关键词解析**的结果，不让脏数据进库。
- **没有草稿时**（直接用 CLI 记录）退回关键词启发式解析，`confidence` 为 0，
  且 UI 要显示「未提取」而不是假装有值。
- **落库的观察必须保留用户的原始口径**：信心、依据、用户自己说的证伪条件 ——
  这是后面「认知档案 / 校准统计」唯一能用的输入。**接入层解析出来的结构化结果
  不能在中途被丢掉**（这是 2026-11-24 端到端实测发现的真实缺陷）。

---

## 4. 记录与查询

### 4.1 表结构

```sql
CREATE TABLE reviews (
  id               TEXT PRIMARY KEY,
  observation_id   TEXT NOT NULL,
  reviewer_id      TEXT NOT NULL,
  reviewer_version TEXT NOT NULL,
  ran_at           TEXT NOT NULL,
  status           TEXT NOT NULL,          -- ok | partial | skipped | error
  duration_ms      INTEGER,
  verdict_json     TEXT NOT NULL,          -- 完整 ReviewVerdict
  created_at       TEXT NOT NULL
);
CREATE INDEX idx_reviews_obs ON reviews(observation_id, reviewer_id, ran_at);
```

**每次运行都追加一行**（重跑留痕）。查询时取每位点评师的**最新一版**（`max(ran_at)` per reviewer_id）用于展示与评分；历史版本保留，供认知档案做"点评一致性"分析。

### 4.2 删除语义（§7 的软删除在此生效）

`reviews` 不随观察卡删除而物理删除，但**软删除的观察不参与评分与校准统计**。保留是为了审计与排障。

### 4.3 认知档案的原料

`reviews` 落库后，认知档案可以直接回答：

- 哪类问题最常命中你（按 `finding.code` 频次）
- 哪位点评师的提示你最容易忽略（该点评师的 finding 存在，但你后续观察没有针对性处理）
- 你在哪些维度上长期失分（按 `dimension` 汇总 `delta`）

这三项在本轮只保证**数据可查**，看板留到下一轮。

---

## 5. 评分聚合

### 5.1 维度固定，点评师自由贡献

主规格 §5.3 的五个维度**保持不变**：

| 维度 | 权重 | 本轮由谁贡献 |
|---|---|---|
| 事实锚定 | 25% | （下一轮：`audit-fact`） |
| 证伪条件 | 25% | `anchor-chanlun` 贡献"结构位证伪条件"部分 |
| 逻辑链条 | 20% | （下一轮：`audit-logic`） |
| 位置与时机 | 15% | `anchor-chanlun` |
| 一致性 | 15% | （下一轮：`audit-consistency`） |

**新增维度必须显式改 `config/scoring.json`。** 理由：主规格 §5.6 的 Brier 校准统计要求跨期可比；若点评师可以随意引入新维度，早期观察与后期观察的分数就不可比，校准曲线失去意义。

### 5.2 聚合算法

```
参与维度 = [d for d in DIMENSIONS if 有贡献]
for dimension in 参与维度:
    contributions = [f for review in latest_reviews for f in review.findings
                     if f.dimension == dimension]
    weighted = sum(f.delta * reviewer.weight for f in contributions)
    raw = 100 + weighted                    # 以 100 为基准做加减
    completeness[dimension] = "ok"

for dimension in DIMENSIONS - 参与维度:
    completeness[dimension] = "no_reviewer"

score = Σ(raw_d * weight_d for d in 参与维度) / Σ(weight_d for d in 参与维度)
```

**关键：没有点评师贡献的维度既不按 0 分算，也不按满分算，而是从加权平均的分子与分母中一并剔除。**

理由：把"没人点评这一项"当成 0 分 = 因为系统没覆盖就惩罚用户；当成满分 = 把缺失的信息粉饰成肯定。两者都会让分数失真。**正确做法是剔除并在 UI 上明确标注「无人点评」** —— 这样总分只反映"被真正审阅过的部分"，同时缺失是可见的。

（对比：若某维度确有点评师但结论为中性，则 `delta = 0` → `raw = 100`，这是**真实的满分**，与"无人点评"性质不同，不可混淆。）

**同一维度多家点评师时，各自 delta 直接相加**（不是平均）—— 两位点评师都认为有问题，扣分就该更多。权重只用于调节某位点评师的影响力。

### 5.3 可解释性输出

```jsonc
"score_breakdown": [
  {
    "dimension": "位置与时机", "weight": 0.15, "raw": 88, "weighted": 13.2,
    "completeness": "ok",
    "contributions": [
      { "reviewer_id": "anchor-chanlun", "finding_codes": ["CHAN_DAY_TOP_DIVERGENCE"],
        "delta": -12, "weight": 1.0 }
    ]
  },
  {
    "dimension": "证伪条件", "weight": 0.25, "raw": null, "weighted": null,
    "completeness": "no_reviewer",
    "contributions": []
  }
],
"scored_dimensions": ["位置与时机"],
"score_denominator": 0.15
```

**`completeness: "no_reviewer"` 必须显示在 UI 上**（且 `raw` / `weighted` 为 `null`，不是 0、也不是 100）。否则用户会以为"证伪条件 25 分我拿满了"，实际是没人点评这一项。这是主规格"可解释性是硬约束"的直接落实。

`score_denominator` 明示总分实际除以的权重和 —— 用户能一眼看出"这次只有 15% 的维度被审过"，这本身就是重要的认知提示。

### 5.4 评分不得由 LLM 产出

与主规格 §5.1.2 的分层一致：**分数只由规则层算出**。LLM 只负责把 finding 组织成人话，不参与加权。

---

## 6. 观察期接入

### 6.1 档位上限来自点评师

主规格 §5.4 定义了四档信号强度与各自的允许档位。本设计增加一层：**点评师的 `horizon_hint.tier` 决定该观察的可选档位上限**。

| tier | 语义 | 允许 `review_at`（交易日） |
|---|---|---|
| `short` | 只够短线验证 | 3 / 5 |
| `mid` | 中期可跟踪 | 5 / 10 / 20 |
| `long` | 支持长观察 | 10 / 20 / 40 |
| `event` | 事件驱动 | 催化剂 + 5 / 10 / 20 |

多家点评师同时给出 hint 时，取**最保守**（档位更低）的那个。理由：宁可观短一点，也不要在结构不支持时给长观察期。

### 6.2 checks 来源

`checks` 优先取 `proposed_invalidation` 中**可自动判定**的项（中枢位、价格位、主力净流入方向等）。每个 check 必须声明 `source`（可取数的数据源标识）。

若某 check 的数据源当前不可用，标记 `data_unavailable`，到期时记为"数据缺失"而非"未命中"（主规格 §5.4 已有此规则）。

### 6.3 证伪条件的采纳路径

```
proposed_invalidation
      ↓
UI 展示为「建议的证伪条件」+ 「采纳」按钮
      ↓ 用户点采纳
写入 observation.invalidation（append-only，新版本行 + supersedes_id）
```

**点评师不自动写入。** 理由：用户的证伪条件是用户自己的判断标准；被工具改写会破坏归因 —— 到期时无法区分"判断错了"和"标准被换了"。

> **当前实现（2026-11-24）**：「采纳」按钮暂时**禁用**。观察记录目前没有版本链
> （`supersedes_id`），而采纳会修改已存在的观察记录 —— 与「观察记录只追加不修改」
> 的不变量冲突。下一轮补观察版本链时再启用。点评师的 `proposed_invalidation`
> 依然**不会自动写入** observation（§2.2 硬约束），这一点不变。

---

## 7. 观察卡可删除

### 7.1 语义：软删除

主规格已定"观察记录只追加不修改"。物理删除会毁掉认知档案的校准样本（§5.6），因此删除实现为**软删除**：

```sql
ALTER TABLE observations ADD COLUMN deleted_at TEXT;   -- NULL = 存活
```

- 观察库列表**过滤掉** `deleted_at IS NOT NULL` 的行。
- 软删的观察**不参与**评分聚合、观察期计划、校准统计。
- `reviews` 记录保留（审计与排障需要）。

### 7.2 两个删除入口

| 入口 | 对象 | 行为 |
|---|---|---|
| 解析区「清空」按钮 | 尚未保存的草稿 | 清空 textarea + 丢弃已解析的卡片 + 清 localStorage 草稿 |
| 观察库每行「删除」按钮 | 已保存的观察 | 置 `deleted_at`，从列表消失 |

### 7.3 不可撤销提示

删除按钮需要一次确认，明确告知「删除后不再参与评分与校准统计」。不做硬删除，也不提供回收站（本期）。

---

## 8. Mini App 呈现

### 8.1 观察卡区域改造

```
┌ 我的观察卡 ────────────────────────────┐
│ 002378 章源钨业 · 看多 72% · 半年         │
│ 依据 4 条（事实 2 · 假设 2）              │
│ ⚠ 缺少证伪条件                [清空]     │
└─────────────────────────────────────────┘
┌ 点评师意见 ────────────────────────────┐
│ ▼ anchor-chanlun  3 条发现   ❗1 高危     │
│   · 日线顶背驰成立（面积比 0.70）→ -12   │
│     你的看多主张与大级别动能背离，按纪律二 │
│     只能定性为反弹                         │
│     建议：降级为「反弹参与」或等周线背书   │
│   · 建议证伪条件：跌破日线中枢下沿 12.01  │
│     [采纳]                               │
│   · 窗口提示：周线仅 2 个中枢，置信度折损  │
│   ⚠ 背驰 active ≠ 仍成立，须复核是否破锚点 │
│                                          │
│ ▼ audit-falsification  1 条发现  ⚠ 高危   │
│   · 缺少证伪条件 → -25                    │
└─────────────────────────────────────────┘
┌ 评分 62 / 100 ─────────────────────────┐
│ 事实锚定   —   无人点评                  │
│ 证伪条件  100  25.0                     │
│ 逻辑链条   —   无人点评                  │
│ 位置与时机 88  13.2  ← anchor-chanlun   │
│ 一致性     —   无人点评                  │
│ [展开] 每一分的来源                      │
└─────────────────────────────────────────┘
┌ 观察期：10 个交易日（2026-11-24 → 12-08）┐
│ 依据：日线顶背驰成立、30 分钟未见同向确认 │
│ → 档位上限 short，故只能取 5 或 3        │
│ checks：跌破 12.01 即视为证伪            │
└─────────────────────────────────────────┘
```

### 8.2 呈现规则

| 元素 | 规则 |
|---|---|
| finding 严重度 | critical/high → 红色警示；medium → 橙；low/info → 灰 |
| `dimension` + `delta` | **必须显示**，否则用户不知道扣在哪、也回溯不了 |
| `suggested_fix` | 必须显示（这是"怎么改"的部分） |
| `caveats` | 收在「⚠ 判读限制」折叠区，**默认展开 critical 级的** |
| `completeness: no_reviewer` | 必须显示"无人点评"，**不得显示为 0 分或满分** |
| `proposed_invalidation` | 单独区块 + 「采纳」按钮，**不自动写入** |
| LLM 措辞 | 只替换/丰富 `claim` 的自然语言表述与"这说明什么"；`code`/`severity`/`dimension`/`delta` **不可改** |

### 8.3 措辞层的降级

若 LLM 不可用（provider 未配 / 调用失败 / 超时），**直接展示规则层原文**，不阻塞评分与观察期。规则层结论本身已是完整可用的。

---

## 9. `anchor-chanlun` 点评师

### 9.1 数据流

```
tdx_kline(code, setcode, period=5/4/2, wantNum=500)     ← 通达信 MCP，主数据源
      ↓  （三个级别，各 500 根 —— 对齐模式，见纪律四）
providers/tdx_rows_to_em.py                                ← Rows → 东财格式（升序，7 列）
      ↓
vendor/chanlun-core/scripts/chan_analyze.py --level week|day|m30
      ↓
vendor/chanlun-core/scripts/chan_multi_level.py
      ↓  → chan_multi_level.json
rules.py                                                    ← 纯规则：结构 + 观察卡 → findings
      ↓
wording.py                                                  ← LLM 措辞（可选）
      ↓
ReviewVerdict
```

### 9.2 窗口与级别纪律

| 级别 | `period` | 根数 | 角色 |
|---|---|---|---|
| 周线 | `5` | 500 | 长期战略：能不能做 |
| 日线 | `4` | 500 | 中期战术：在哪、什么买卖点 |
| 30 分钟 | `2` | 500 | 短期执行：在哪进、在哪止损 |

**三级别统一 500 根**，不是随意的自然时间跨度 —— 缠论识别规则尺度不变，统一根数才能让三级别的中枢数可比（纪律四）。30 分钟取 1023 根会让它的中枢数翻倍、短期结构被放大、区间套确认门槛被拉低。

**背驰有效期按级别折算**：周 12 / 日 15 / 30 分 24 根（上游已实现，不改）。

### 9.3 数据适配器（必须重写）

上游 `vendor/chanlun-core/scripts/tdx_to_em_format.py` **不能直接用**：

| 维度 | 上游假设 | 当前 MCode 实际 |
|---|---|---|
| 表头 | `ListHead` 是数组 `["日期","开盘",...]` | `ListHead.ItemHead` 是数组，`ListHead` 是对象 |
| 数据行 | `AttachInfo` 是数组的数组 `[[...],[...]]` | `AttachInfo` 是**元信息对象**；真正的行在 **`Rows`** |
| 字段名 | 中文表头名 | 英文 `Data` / `Open` / `High` / `Low` / `Close` / `Volume` / `Amount` |
| 排序 | 倒序（需 `reverse()`） | **升序**（新适配器**不得** reverse） |

新的 `tdx_rows_to_em.py` 行为：

1. 从 `Rows` 读取每行，取 `Data`（日期）、`Open`、`High`、`Low`、`Close`、`Volume`、`Amount`。
2. 日期 `YYYYMMDD` → `YYYY-MM-DD`。
3. 输出东财字段序 `date,o,c,h,l,v,a`（注意 `c` 在 `h`/`l` 之前，与 TDX 的 `o,h,l,c` 不同）。
4. **保持升序，不 reverse。**
5. 保留上游 `parse_tdx_date` 的多格式兼容。

### 9.4 规则层：25 条纪律 → findings

规则层是**纯函数**：`f(观察卡, chan_multi_level.json) -> findings/delta/proposed_invalidation/caveats`，全部可单测。

| 纪律 | 触发条件 | finding code | dimension | delta |
|---|---|---|---|---|
| 纪律二 小级别服从大级别 | 周线 `bias=down` 且用户 `direction=bullish` | `CHAN_HIGHER_LEVEL_DENIES` | 位置与时机 | −15 |
| 纪律二 仓位上限 | 周线 `bias=down` | `CHAN_POSITION_SIZE_CAP` | 位置与时机 | −5（info 级，附仓位上限建议） |
| 纪律四/八 顶背驰优先 | 任一级别 `signal` 含"顶背驰"且成立 | `CHAN_TOP_DIVERGENCE_OVERRIDES` | 位置与时机 | −12 |
| 纪律二/二十一 方向冲突 | 用户 `direction` 与日线 `signal` 方向相反 | `CHAN_DIRECTION_CONFLICT` | 位置与时机 | −18 |
| 纪律二十一 位置≠趋势 | `bias` 与 `trend_direction` 不一致 | `CHAN_POSITION_VS_TREND` | 位置与时机 | 0（info，caveat） |
| 纪律二十二 中枢不贴近现价 | 该级别最近中枢距现价 > 15% | `CHAN_PIVOT_FAR_FROM_PRICE` | 证伪条件 | −3（提示降权） |
| 纪律二十二 旧中枢供给/支撑带 | `nearby_pivots` 中存在距现价 < 10% 的旧中枢 | `CHAN_NEARBY_SUPPLY_BAND` | 位置与时机 | −4 |
| 中枢上下沿 | `nearby_pivots` 有 ZD/ZG | → `proposed_invalidation` | 证伪条件 | 0 |
| 纪律十三 区间套未确认 | `interval_nesting.verdict == "unconfirmed"` | `CHAN_NESTING_UNCONFIRMED` | 位置与时机 | −6 |
| 纪律九 区间套方向 | `interval_nesting.verdict` ∈ {partial, confirmed} | → caveat（必须写明方向） | — | 0 |
| 纪律十二 背驰失效复核 | `recent_divergence.active == true` | → caveat | — | 0 |
| 纪律十四 基准退化 | 标注背驰日期与最新价新低/新高相距很远 | → caveat（需手工复算） | — | 0 |
| 纪律二十四 窗口偏薄 | `window_verdict` ∈ {样本偏薄, 窗口偏短} | `CHAN_WINDOW_THIN` | 位置与时机 | −2 |
| 纪律二十五 盘中未收盘 | 当日 K 线未收盘 | → caveat | — | 0 |
| 纪律十七 现价在中枢内部 | 现价落入某个中枢区间 | `CHAN_PRICE_INSIDE_PIVOT` | 证伪条件 | −5 |
| 纪律二十三 回调不创新低 | 结构呈 2 买形态但大级别无背书 | `CHAN_SECOND_BUY_NO_BACKING` | 位置与时机 | −6 |

**不产生 finding、只进 `caveats` 的纪律**：一、三、五、六、七、十一、十六、十九、二十。

**delta 数值是初版约定值**，实现时通过单测锁定语义（"周线未许可且用户看多 → delta ≤ −15"），具体数值可随真实使用校准，但**一旦定版不得随意改**（影响跨期可比）。

### 9.5 `proposed_invalidation` 生成

从 `nearby_pivots` 生成两类建议：

| 类型 | 规则 | 用途 |
|---|---|---|
| 结构失效位 | 跌破最近中枢下沿 `ZD`（容忍 0.5%） | 证伪条件 |
| 结构确认位 | 站上最近中枢上沿 `ZG`（容忍 0.5%） | 视为主张强化（可作为 `checks`） |

**均需用户点「采纳」才写入观察。**

### 9.6 `horizon_hint` 生成

| 条件 | tier |
|---|---|
| 任一级别有成立且未被更高级别推翻的顶/底背驰 | `short` |
| 大级别许可（周线 bias=up）+ 日线有同向信号 | `mid` |
| 周线底背驰成立 + 日线区间套确认 | `long` |
| 用户给出明确催化剂日期 | `event` |

多个条件同时命中时**取最保守**（见 §6.1）。

### 9.7 降级链

| 情况 | 行为 |
|---|---|
| TDX `tdx_kline` 不可用 | 降级上游 `fetch_kline.sh`（em / sina）。**注意东财限流**：同一 IP 连续请求会返回空，必须换源而非重试（上游 SKILL.md 已记录此坑） |
| TDX 30 分钟根数不足 | 用 `wantNum=800`；仍不足则该级别标记 `partial`，整体 `status='partial'` |
| 结构识别失败 | `status='error'`，落库错误摘要，不影响其它点评师 |
| 样本偏薄（如次新股） | 正常出结论，但 `caveats` 必须标注置信度折损，delta 不因此加重（薄样本不是用户的错） |

---

## 10. LLM 措辞层

### 10.1 为什么放在业务内核而不是 Mini App

主规格 §6.5 已定：业务内核自带 provider 配置，不读宿主配置。因此**措辞层由业务内核直连 `analysis_provider`**（DeepSeek / MiniMax 等），而不是依赖 Mini App 的 `context.agent.run`。

理由：

1. **MCP / CLI 路径同样可用** —— 点评师不绑定宿主形态（主规格 D3）。
2. Mini App 的 `context.agent.run` 是"面板内触发一轮分析"的宿主能力，业务内核的 stdio 子进程拿不到它。
3. 措辞层失败必须能降级（§8.3），放在内核里降级逻辑只有一处。

### 10.2 约束

输入：规则层 findings + 原始观察卡 + 结构摘要。
输出：每条 finding 的一段人话点评。

**硬约束**：LLM 不得修改 `code` / `severity` / `dimension` / `delta` / `evidence_ref`。归一化层（仿主规格 §5.1.2 的 `normalizeDraft`）会校验：若 LLM 改动了这些字段，**丢弃 LLM 输出，保留规则层原文**。

### 10.3 提示词要点

- 面向"想提升认知的投资者"，不是面向报告
- 每条点评必须回答：**这说明什么 / 你可能忽略了什么 / 下一步该做什么**
- 不得给投资建议、不得预测点位
- 结构判定为既定事实，措辞不得软化或强化

---

## 11. 错误处理与降级汇总

| 故障 | 表现 | 处理 |
|---|---|---|
| 单个点评师抛错 | 该点评师无结论 | 隔离，落 `status='error'`；评分按剩余点评师归一化；UI 显示"该点评师未成功运行" |
| 某维度无点评师贡献 | 无人覆盖 | `completeness='no_reviewer'`，UI 明示，**不按 0 分处理** |
| LLM 不可用 | 无措辞 | 用规则层原文，评分与观察期照常 |
| 行情源不可用 | 结构为空 | 点评师 `status='skipped'`，`caveats` 说明 |
| 数据库写入失败 | 结论丢失 | 抛错回滚，观察卡保存事务与之分离：**观察卡先落盘成功**，点评失败不丢观察 |

---

## 12. 测试策略

| 层 | 手段 | 覆盖 |
|---|---|---|
| 数据适配器 | 单测 | `Rows` → 东财格式的字段序、日期格式、**升序不被 reverse**、缺字段报错 |
| 规则层 | 单测（纯函数） | 每条纪律的触发/不触发、delta 符号、`proposed_invalidation` 生成、`caveats` 非空 |
| 契约校验 | 单测 | 缺 `dimension`/`delta` 的 finding 被拒；LLM 改动受保护字段时被丢弃 |
| 评分聚合 | 单测 | 多点评师同维度求和、`no_reviewer` 不按 0 分、`completeness` 正确 |
| 观察期 | 单测 | 多 hint 取最保守、`no_reviewer`/事件驱动的档位上限 |
| 端到端 | 手工（Browser 实测） | 002378 全链路：口述 → 解析 → 点评 → 评分 → 观察期 → 删除 → 重启恢复 |

**规则层与适配器是本轮测试重点**：它们承载了"点评是否会误导用户"的风险。

---

## 13. 边界与风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 缠论结构被当成结论 | 用户把机械结论当买卖依据 | `caveats` 强制随结论落库；措辞层禁止软化/强化判定；UI 显著呈现限制 |
| 上游脚本升级不兼容 | 缠论结论出错 | 上游**整目录拷贝**并标注版本；`vendor/` 下不改一行；新增/改动走独立适配层 |
| 东财限流 | 降级链断裂 | 主源 TDX（平台托管、无 IP 限流问题）；em 仅作降级；命中限流立即换源不重试 |
| 点评师权重失衡 | 某位点评师主导评分 | 权重写在 `config/reviewers.json`，可审计；`score_breakdown` 显示每位贡献 |
| 维度被点评师撑爆 | 跨期不可比 | 维度集合固定在 `config/scoring.json`，新增需显式改配置 |
| LLM 篡改判定 | 结论不可信 | 归一化层校验受保护字段，篡改即丢弃 |
| 缠论分析慢（拉三级别 K 线 + Python 计算） | 保存体验卡 | 点评异步执行；UI 显示"点评中"；观察卡先落盘，不阻塞保存 |

---

## 14. 与主规格的关系

本设计对主规格做三处修改（实施时同步更新主规格）：

1. **§5.2**：「Stage 1 · 多镜审阅：每个 skill 一个透镜」→ 重写为「Stage 1 · 点评师层」，
   引入 `ReviewVerdict` 契约与可插拔注册表；现有 5 个 skill 的迁移列入下一轮。
2. **§5.3**：评分聚合的 `score_breakdown` 扩展为含 `contributions`（点评师维度）与 `completeness`。
3. **§7**：存储模型新增 `reviews` 表；`observations` 新增 `deleted_at`（软删除）。

其余（D1–D11、§6 数据层、§8 分期、§9 数据边界）不受影响。

---

## 15. 本轮交付清单

- [x] `src/agaistock/skills/anchor_chanlun/`（上游只读拷贝 + 适配层 engine/reviewer/rules/signals + 措辞层 wording）
- [x] `src/agaistock/reviewers/`（契约 + 注册表 + 引擎）
- [x] `src/agaistock/storage/db.py`（`reviews` 表 + `deleted_at`）
- [x] `src/agaistock/scoring.py`（维度聚合 + `completeness`）
- [x] `src/agaistock/horizon.py`（档位上限 + checks）
- [x] `config/reviewers.json`、`config/scoring.json`
- [x] Mini App：点评展示 + 评分展示 + 删除（草稿清空 / 观察软删）
- [x] 单测：适配器 / 规则层 / 契约 / 评分 / 观察期
- [x] 端到端实测（002378）→ 结论见 §16

---

## 16. 端到端实测结论（2026-11-24）

在**真实安装副本**上跑完整闭环（`miniapp publish` → `miniapp open`，不是仓库直跑），标的 **002378 章源钨业**。

### 16.1 实测结果

| 环节 | 结果 |
|---|---|
| 解析 | 看多、信心 70%、**依据 5 条**（事实 2 · 假设 3）、证伪条件「钨价跌回去年年底的水平」 |
| 落库 | 结构化观察写入 SQLite，`evidence_json` 5 项、`invalidation_json` 1 项（**逐字段校验后落库**，不是自由文本） |
| 点评 | `anchor-chanlun` 产出 6 条 finding |
| 评分 | **92 / 100**（UI 取整显示；**精确值 92.125** = (91×0.25 + 94×0.15) / 0.40）；被审维度只有「证伪条件 91（权重 0.25）」+「位置与时机 94（权重 0.15）」，**权重和 0.40** |
| 无人点评 | 事实锚定 / 逻辑链条 / 一致性 三维标 `no_reviewer`，**不按 0 分计**，不进分母 |
| 观察期 | 2026-12-01，档位 **event**，rationale「存在明确催化剂（明年上半年产量翻倍），按事件驱动锚定」（落库实际值带点评师前缀：`anchor-chanlun: …`） |
| 到期检查项 | 6 条，**每条都带 rationale** |
| 删除 | 确认弹窗 → `DELETE /api/observations/<id>` → 200；DB 层 `deleted_at` 置位，**行未被物理删除** |
| 重启恢复 | `publish` 重解包 + runtime 重启后，观察行**仍在**（依据 / 信心 / 证伪条件齐全），已删行仍隐藏 |

**口径确认**：这个 92 分的分母是 **0.40** 而不是 1.0。UI 必须显示 `score_denominator`，否则用户会把「只在两个维度上被评了 91 和 94」误读成「全面 92 分」。

### 16.2 实测挖出的、必须写进设计的四条事实

这四条都不是纸面推导出来的，只有装包实测才会暴露：

| # | 事实 | 影响 |
|---|---|---|
| 1 | **宿主把插件包解到临时目录再跑**（实测 `C:\Users\shawn\AppData\Local\Temp\mavis-miniapp-XXXXXX\package\`），仓库里的 `src/` 根本不在运行路径上 | 内核必须随包走：采用「复制 + 逐字节漂移守卫」（`tools/sync-kernel.py` + `tests/test_kernel_vendor.py`），而不是把内核搬进插件包（会牵动 pyproject / editable 安装 / `repo_root()` 语义 / 数据目录位置，成本远大于收益） |
| 2 | **`python -S` 是必需项，不是优化**：editable 安装的 meta-path finder 优先级高于 `PYTHONPATH`，不加 `-S` 时包内 `src/` 会被已安装的包截胡 | 顺带把「零第三方依赖」从口号变成运行时硬约束 |
| 3 | **运行期产物（数据库 + 缠论分析工作目录）都落 `context.dataDir`**（实测 `…\.minimax\v2\plugin-data\liveboards\agaistock\`），插件目录是安装产物、可能被覆盖或只读 | 数据库路径由 `server.mjs` 传入；实测插件包内**不含任何 `.db` 文件`。缠论分析工作目录（上游脚本产出的 K 线与结构 JSON）同样由 `server.mjs` 通过 `AGAISTOCK_DATA_DIR` 传下去（`cli.py` 用 `config.data_dir()`），**不再写进插件包自己的 `data/`** —— 包目录若只读，`work_dir.mkdir` 原本会直接失败 |
| 4 | **`miniapp restart` 不能更新已安装副本**，只会重启旧副本 | 更新已安装的 Mini App 必须 `miniapp publish` 再 `open`；实测首次 publish 前 `/render.mjs` 404、`/api/observations` 还返回旧 JSON 库结构 |

### 16.3 实测修掉的缺陷（本轮新增任务）

| 任务 | 缺陷 | 根因 |
|---|---|---|
| Task 17 | 安装包不自包含；内核失败被伪装成空列表 | 包内无内核；`countObservations` 回落到旧 JSON 观察库 |
| Task 18 | GBK 编码崩溃（整轮点评作废，间歇性，3 次中招 1 次） | 连接器 `errors="replace"` 产出 U+FFFD → CLI 用 GBK stdout `print` JSON → `UnicodeEncodeError` |
| Task 18 | 观察期落点可能落在**周日**且在允许窗口之外 | `review_at` 未推进到交易日 |
| Task 19 | 结构化观察**没有落库**（解析出的依据 / 证伪条件丢失） | 接入层解析结果未进内核 |
| Task 19 | 点评师 `reviewer_version` 为空串 | 空版本号未归一化 |
| Task 20 | 缠论分析工作目录写进**插件包自己的 `data/`**（污染安装产物；只读安装时 `work_dir.mkdir` 抛错会让点评师整体失败） | `cli.py` 用 `repo_root()/"data"`，而安装副本里 `repo_root()` 就是包根 |

### 16.4 本轮不做、留给下一轮

- **观察版本链（`supersedes_id`）**：§6.3 要求「采纳」产生新版本行 + supersedes 关系，当前存储模型没有版本链，直接改数组会破坏「观察记录只追加不修改」的不变量 → **「采纳」按钮本轮禁用**并写明原因；启用「采纳」的前提是先建版本链。
- `contract.py` 的 bool delta / 浅拷贝 / `duration_ms` 类型收紧
- `engine.py` 的错误归因与失败路径丢字段
- `persist()` 的**两条落库路径**（正常落库 / 评审失败时转成 `status="error"` 的兜底 verdict）缺「提交进仓库」的测试锁定
- `src/agaistock/mcp/` 的 MCP 工具暴露
- 上游 `resonance` / `window_alignment` / `key_levels` 未接入（设计级，下一轮）
- `AGAISTOCK_DATA_DIR` 若给的是**相对路径**，会按内核 cwd 解析（安装副本里 cwd 就是包根）→ 将来要加绝对路径守卫；宿主目前总是给绝对路径，暂不可达。
- 回落值 `repo_root()/"data"` 在**安装副本里指向包内** —— 环境变量是唯一的护栏，宿主侧一旦回归，缺陷会静默复活。（`buildKernelEnv(context, pluginRoot)` 直接吃宿主 context 算出内核运行路径，中间没有任何可被覆写的对象；三层**行为**护栏锁住它 —— env 纯函数 / 真实 spawn 路径 / `start()` 注入点 —— 能挡住本仓库内的改动，但**挡不住宿主侧回归**。）
