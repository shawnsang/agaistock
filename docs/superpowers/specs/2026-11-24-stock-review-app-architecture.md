# 股票复盘 App · 架构设计（草案 v0.5）

> 状态：待用户评审（含 Mini App 垂直切片实测结论）
> 日期：2026-11-24
> 工作区：`D:\workroom\agaistock`（全新，git 未初始化）

---

## 1. 目标与核心闭环

用户的核心诉求不是"看行情"，而是**通过反复复盘提升个人观察股票的能力和认知**。

因此产品的唯一主干闭环是：

```
口述观察 → 结构化记录 → 多镜审阅(合理性建议) → 自适应观察期
   ↑                                              ↓
认知档案 ← 归因反馈 ← 到期结算 ← 观察期内实际走势 ←┘
```

**其他一切（行情接入、多模型配置、UI）都是为这条闭环服务的支撑设施。**

### 1.1 三个不可混淆的产物

| 产物 | 含义 | 取值 | 谁产出 |
|---|---|---|---|
| `observation` | 用户的一条观察记录 | 结构化对象 | 解析 skill |
| `observation_score` | **我的观察质量**分 | 0~100 | 评分聚合 skill |
| `market_view` | **这只股票当前多空分** | -100~+100 | seven-dim 等客观引擎 |

把 `observation_score` 和 `market_view` 混为一谈是这类产品最常见的失败模式：股票跌了不代表你观察得差。
**硬性约束：二者在数据模型、UI、报告中始终物理分离，分别命名、分别存储、分别呈现。**

---

## 2. 关键决策记录

| # | 决策 | 结论 | 理由 |
|---|---|---|---|
| D1 | 市场范围 | 仅 A 股 | 现有 `seven-dim-stock-analysis` 直接复用 |
| D2 | 客户端 | 桌面本地安装；**移动端暂缓** | 本轮先做闭环；架构不封死移动端（保留 HTTP API 出口） |
| D3 | 运行时 | **宿主无关业务内核 + 标准 MCP 接入层** | 成本最低、维护最好、依赖可快速升级（见 §3） |
| D4 | 观察期 | LLM 按信号强度自适应，但**限定档位 + 必须产出可判定 checks** | 纯 LLM 给天数不可靠，且无 checks 则到期无法判定 |
| D5 | 数据源 | **双源互补**：通达信 MCP 为主源（行情/K线/资金流/股东/复权因子）；**同花顺 iFinD 为增强源**（估值分位/DDX 家族/财务分析）；东方财富妙想待评估；Tushare/AKShare 降为可选 | 实测见 §6.7：⑤估值 iFinD 直接给近三年分位，通达信直接给复权因子；两源都能免 token 调用，且各自有对方缺的能力 |
| D6 | 复权口径 | 后复权序列 + 复权因子落库，前复权仅作展示 | 前复权随除权回溯变化，跨源可差几个百分点，累积数年足以让同一判断得出相反结论 |
| D7 | 节奏 | 批量复盘 与 随手记 两模式并存，可切换 | 用户明确要求 |
| D8 | 部署形态 | **本地优先**：MCP server 为本地 stdio 子进程，不监听端口；**不需要公网地址 / 云服务器** | 用户是单机自用；数据不出本机 |
| D9 | 数据边界 | 个人数据全部留在本机 SQLite；**仅两类出网**：口述文本→LLM API、行情查询→行情 API | 可选本地模型进一步减少外发 |
| D10 | UI 载体 | **Mini App 优先于「对话驱动」**：垂直切片已端到端跑通，录入面直接落在 Mini App | 对话驱动无法承载"随时口述→即得卡片"的节奏；而 Mini App 无需自建 ASR、无需打包签名 |
| D11 | 解析层 | 提示词守则 **6 条硬规则** + 确定性归一化层（`normalizeDraft`）兜底 | 模型会漂移；提示词单独不够，必须配一层可测的归一化 |
| D12 | Stage 1 形态 | **可插拔的「点评师」层**；一位点评师 = 一个目录 + 一条注册记录；结论**全部落库**，一起进入评分与观察期 | 固定 skill 列表无法持续上新；结论不落库则认知档案无原料、用户看不到"当时怎么被评的"。详见 §5.2 与点评师设计文档 |
| D13 | 维度口径 | 五维**固定**，新增维度须显式改 `config/scoring.json`；无点评师贡献的维度从加权平均中剔除并标注 `no_reviewer` | §5.6 的 Brier 校准要求跨期可比；隐式扩张维度会让早晚观察的分数不可比 |

---

## 3. 运行时选型：按"成本 / 维护 / 依赖可升级"重新排序

用户的三条标准：成本最低、维护性最好、新依赖版本能快速升级。

| 方案 | 成本 | 维护性 | 依赖升级 | 判定 |
|---|---|---|---|---|
| **dsh 内核 + 自建客户端** | 中 | ❌ 差 | ❌ 差 | rc 阶段，每次 release 222 个文件同步改版号，破坏性变更频繁，追版本成本高；且沙箱有 CVE-2026-82533（9.4 分）前科 |
| **自研薄内核 + Tauri 客户端** | ❌ 高 | 中 | ✅ 好 | 要自写运行时 + 客户端外壳 + 打包签名更新，工作量最大 |
| **宿主无关内核 + MCP 接入层** | ✅ 最低 | ✅ 最好 | ✅ 最好 | 业务逻辑与宿主解耦；宿主（MCode / dsh / 独立壳）可随时替换 |

**结论：选第三个。**

它的含义不是"寄生在 MCode 里"，而是：

- **业务内核独立成仓库**：`D:\workroom\agaistock\` 内，纯 Python + SQLite，不依赖任何 harness 的私有 API
- **对外只暴露标准 MCP Server**：`agaistock-mcp`，任何支持 MCP 的宿主都能挂载
- **宿主只是客户端**：MCode 桌面（当前）、dsh（未来）、独立 Tauri 壳（未来）都能调同一套工具
- **分析逻辑写成 SKILL.md**：MCode 原生加载；同时兼容 dsh 插件形态（只需一层薄适配）

代价：MCP 工具要自己实现（标准协议，工作量可控）；换来的是**宿主不绑架**。

---

## 4. 整体架构

```
┌──────────────────────────────────────────────────────────┐
│  宿主层（可替换）                                            │
│  MCode 桌面  │  DeepSeek Harness  │  未来：独立 Tauri 壳      │
└───────────────┬──────────────────────────────────────────┘
                │ 标准 MCP 协议
┌───────────────▼──────────────────────────────────────────┐
│  接入层：agaistock-mcp（Python, stdio + http）              │
│  tools: record_observation / list_observations /           │
│         set_horizon / settle_observation / get_profile /   │
│         fetch_market_data / list_skills                    │
└───────────────┬──────────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────┐
│  技能层：SKILL.md × N —— 每个 skill = 一个审阅透镜            │
│  ┌────────────┬──────────────┬──────────────┬───────────┐ │
│  │ observation│ audit-fact   │ audit-logic  │ audit-    │ │
│  │ -parse     │ 事实核验     │ 因果链检查    │ falsify   │ │
│  ├────────────┼──────────────┼──────────────┼───────────┤ │
│  │ audit-bias │ anchor-7dim  │ observation- │ observation│ │
│  │ 偏差检测    │ 客观锚点      │ horizon      │ -score    │ │
│  ├────────────┼──────────────┼──────────────┼───────────┤ │
│  │ observation│ observation- │ observation- │           │ │
│  │ -settle    │ profile      │ summary      │           │ │
│  └────────────┴──────────────┴──────────────┴───────────┘ │
└───────────────┬──────────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────┐
│  引擎层：Skill Runtime                                      │
│  调度 / 结构化输出校验 / 轨迹日志(Trajectory 式) / 多模型路由   │
│  模型读 config/providers.json：DeepSeek / GLM-5.3 / MiniMax-M3   │
└───────────────┬──────────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────┐
│  数据层：Provider Adapter → Cache → SQLite                  │
│  主源: iFinD / 通达信 / 恒生（插件连接器）                    │
│  兜底: Tushare（按 trade_date 批量拉）                        │
│  可选: AKShare（强制走缓存 + 指数退避重试）                    │
└───────────────┬──────────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────┐
│  存储层：SQLite                                             │
│  observations / assertions / findings / horizons / checks / │
│  settlements / scores / bias_profile / market_cache        │
└──────────────────────────────────────────────────────────┘
```

**关键解耦点**：所有客观数值只能来自数据层，skill 引用数值必须携带 `data_ref`；LLM 不得自行编造行情数字。

### 4.1 MCP 工具契约（接入层的正式接口）

宿主只通过这组工具与内核交互。这组工具是**稳定的对外接口**，内部怎么实现可以随便重构。

| 工具 | 入参 | 出参 | 说明 |
|---|---|---|---|
| `record_observation` | symbol, name, raw_text, direction, confidence, position, supersedes_id? | observation_id | 写入一条观察（只追加） |
| `get_observation` | observation_id | 观察卡 + assertions + findings + horizon | 读回完整观察 |
| `list_observations` | symbol?, status?, since?, limit? | 观察列表 | 自选池视图 |
| `draft_observation` | raw_text | ObservationDraft | 只解析不落库，供用户确认后再写 |
| `review_observation` | observation_id, lenses[] | findings[] | 跑指定透镜（默认全部） |
| `score_observation` | observation_id | 五维分数 + 扣分明细 | |
| `set_horizon` | observation_id, signal_strength, review_at, checks[] | horizon | 限定档位校验后写入 |
| `list_due_horizons` | date | 到期 / 临期列表 | 定时任务入口 |
| `settle_observation` | horizon_id | settlement（归因 + 扣分） | 只读 checks，不可改标准 |
| `get_profile` | scope?, window? | 偏差标签 + 五维画像 + 校准曲线 | 认知档案 |
| `fetch_market_data` | symbol, kind, window | 行情片段 + data_ref | 给 skill 取数用 |
| `sync_market_cache` | trade_date?, symbols? | 同步报告 | 收盘后批量任务入口 |

**写操作（`record_observation` / `set_horizon` / `settle_observation`）在宿主侧需触发一次用户确认。**

### 4.2 宿主、插件与 Mini App 的关系（澄清）

```
MCode 桌面 App  ← 宿主 / Host（Electron 应用本身），不是本产品
│
└── Plugin 插件包
    ├── App / Connector   通达信、iFinD、恒生… → 各自提供 MCP 工具
    ├── MCP Server        插件自带的标准 MCP 工具
    ├── Skill             SKILL.md 分析技能
    ├── Hook              同步脚本
    └── Mini App          miniapp/client/index.html + Node entry
                          ↑ Mini App 是插件包的一种 UI 形态，
                            跑在 MCode FilePanel 面板里，不是独立应用
```

**Mini App ≠ MCode。** 本产品的边界是：

| 层 | 归属 | 换宿主的代价 |
|---|---|---|
| 业务内核（数据层 / 技能 / 评分 / 存储） | **独立仓库**，不属于任何插件 | 零 |
| 接入层 | 标准 MCP server | 零 |
| 宿主（MCode / dsh / 独立壳） | 换掉即可 | 零 |
| UI（Mini App / Tauri 壳） | 换掉即可 | 零 |

### 4.3 Mini App 作为 UI 层的能力基线

Mini App 原生能力已覆盖本产品 P1 的全部需求，**不需要自建 ASR、不需要自建数据通道**：

| 能力 | 接口 | 用途 |
|---|---|---|
| 麦克风 + 语音转写 | `deviceAccess:["microphone"]` + `window.mcode.miniapp.speech.transcribe` | **口述输入**（§5.0 的 ASR 在此路径下由 Host 提供） |
| 调连接器 | `context.hostConnector` | 行情数据（通达信） |
| 调任意工具 | `context.tool`（需 manifest 声明 `"toolAccess":["call"]`） | 调 `agaistock-mcp` 的 12 个工具 |
| 跑 Agent | `context.agent.run({text, sessionId?, model?})` | 面板内触发一轮分析 |
| 本地持久化 | Node 服务 `dataDir` | 观察记录落本地文件（原子写 / 事务性存储） |

**约束**：Mini App 不可见时 Host 可能直接停掉 Node entry，**不保证保活**。因此状态必须持续落盘、重启后恢复，不能只靠内存或定时器。
**访问边界**：Mini App 应通过 `context.tool` 调 `agaistock-mcp`，**不要直连 SQLite**，保持「接入层是唯一接口」这一条不变。

#### 4.3.1 垂直切片实测结论（2026-11-24，已验证）

Mini App `agaistock`（股票复盘教练）已构建、发布并在 MCode 中跑通。以下结论**由实测得出，不是设计意图**：

| 环节 | 实测结果 | 证据 |
|---|---|---|
| Mini App 生命周期 | `publish` → runtime `running` → `open` 成功，URL `http://127.0.0.1:51090/dashboard` | `miniapp inspect`：readiness 通过 |
| 页面结构 | 语义 HTML 完整，`observe-card` / 观察库表格 / 能力条均正确渲染 | Browser `inspect` 语义树；console 0 报错 |
| Agent 通道 | `context.agent.run` 可用，能力探测「语音可用 · Agent 可用」 | `/api/status` + 能力条 |
| **口述→观察卡** | 002378 章源钨业 / 看多 72% / 依据 4 条（事实 2 + 假设 2）/ 时限「半年」 | 解析实测输出 |
| **证伪条件不编造** | 用户未说「什么情况下我错」→ `invalidation: []` + 界面红色缺失警告**正确触发** | 核心设计约束生效 |
| 落盘 | `dataDir/observations.json` 原子写入成功 | 文件内容已核对 |
| **重启恢复** | `publish` 重启运行时后记录仍在 | 持久化跨重启验证通过 |
| 确定性层 | `node --test` 23/23 通过 | `miniapps/agaistock/test/pipeline.test.mjs` |

**尚未实测**（P0 必须补）：
- **真实麦克风链路**：能力探测显示 `speech.transcribe` 可用，但无麦克风输入设备，录音→转写未走通。
- **`context.tool` 调 `agaistock-mcp`**：因此前未声明 `toolAccess`，未做成功探测。
- **`context.hostConnector` 调通达信**：连接器在 MCode 中尚未连接（见 §6.6）。

**本轮发现并已修复的缺陷**：

1. **时间跨度漂移（重要）**：模型把口述的「还能拿半年」擅自写成「预计还能持有一年半」，且 `thesis` 与 `timeframe` 自相矛盾（`thesis` 一年半 / `timeframe` 未来半年）。
   → 在提示词中追加第 6 条硬规则（时间跨度忠实原文，不得推断延长）。复测：thesis 与 timeframe 均回到「半年」，**漂移消除**。
   → 归一化层明确**不改写** `timeframe`，该保证留在提示词层并由实测守护。
2. **`invalidation_missing` 存在自相矛盾态**：模型给了证伪条件却漏掉 `invalidation_missing: false` 时，归一化会产出「有条件 + 标记缺失」的矛盾卡。
   → 改为**由 `invalidation` 数组长度单一决定**，消除不可能状态。
3. **右上角计数 chip 不随保存更新** → 引入 `runtimeState` + `renderChip()`。

> **结论**：Mini App 路线在「录入 → 结构化 → 落盘 → 持久化」这一段**已被证明可行**，且不依赖任何未连接的外部连接器。P0 的风险已从「UI 是否可行」收敛为「取数是否可行」（§8 第 0 步）。

---

## 5. 智能辅助分析引擎（核心）

### 5.0 Stage -1 · 语音转写（ASR）

口述是本产品的主输入方式，因此 ASR 是**独立于分析模型的一条通道**，不能与 §5.1 之后的分析模型混用。

- **约束**：ASR 模型必须支持音频输入。当前已配置模型中，MiniMax M3 / M3.1-Flash 支持音频；**DeepSeek V4 系列不支持音频**，因此 DeepSeek 可作为分析模型，但不能作为 ASR 模型。
- **实现路径（择一或并存）**：
  1. MCode 的 Matrix Connector `connector__matrix__listen_audio`（本地文件需先 `mcode-tools upload_temp_url` 换成可访问 URL）
  2. 本地 Whisper / FunASR（完全离线，隐私最好）
  3. 任一支持音频的 OpenAI 兼容端点
- **配置**：ASR 通道在 `config/providers.json` 中**单独声明**（`asr_provider` / `asr_model`），与分析用的 `analysis_provider` 分开，可分别切换。
- **两条路径**：
  1. **Mini App 路径（已选定为主线，D10）**：直接用 Host 的 `window.mcode.miniapp.speech.transcribe`，无需自建 ASR provider。
     实测：能力探测 `speech.transcribe = true`；**真实麦克风链路尚未走通**（当前环境无麦克风输入），P0 必须补测（§4.3.1）。
  2. **MCP / CLI 路径（仅批量/脚本场景）**：必须自配 ASR provider，因为此时没有 Host 面板可用。
- **降级**：ASR 不可用时，退化为文字输入，流程其余环节不变。
- **实测形态**：录音 → 16kHz/mono/s16 PCM → `speech.transcribe({audio, format}, {onPartial})`；
  错误码 `not_permitted` / `runtime_unavailable` / `transcription_failed` / `result_unknown` / `audio_too_large` / `busy`，
  须逐个给出可读提示（尤其 `not_permitted` 要引导用户授权麦克风，而非报错）。

### 5.1 Stage 0 · 结构化：`observation-parse`

输入原始口述文本，输出 `ObservationDraft`：

```jsonc
{
  "symbol": "002378",
  "name": "章源钨业",
  "thesis": "钨价上行周期，公司资源储量领先",
  "direction": "bullish",
  "evidence": [
    { "id": "e1", "text": "钨精矿价格连续3个月上涨", "type": "fact", "verify": "commodity_price" },
    { "id": "e2", "text": "公司明年产量翻倍",        "type": "assumption", "verify": null }
  ],
  "timeframe": "3个月",
  "trigger": "钨价站上关键位",
  "invalidation": ["钨价回落至关键位以下", "季度产量不达预期"],
  "invalidation_missing": false,
  "position": { "entry": "当前价附近", "size": "半仓" },
  "confidence": 0.7,
  "raw_text": "..."
}
```

**硬性设计**：口述中若没有证伪条件，`invalidation` 留空并置 `invalidation_missing: true`。
**禁止 LLM 代为编造证伪条件。**
这是整个学习闭环的地基 —— 没有证伪条件，到期后无法判定对错，也就无法评分、无法学习。
后续 `audit-falsification` 会针对此给扣分与改进建议。

#### 5.1.1 解析提示词契约（6 条硬规则，已落地）

结构化这一步完全依赖模型，因此提示词必须写成**可验证的禁令**，而不是描述性要求。已落地并实测的 6 条：

| # | 规则 | 违反时的后果 |
|---|---|---|
| 1 | 用户没说「什么情况下我错」→ `invalidation` 必须是空数组，**绝不代为编造** | 闭环地基被伪造，后续评分全部失真 |
| 2 | 每条 `evidence` 必须来自用户原话，不得添加用户没说的信息 | 依据变成模型的话，主观判断被当成事实 |
| 3 | 客观可查（价格/公告/财报/产量/储量）标 `fact`；预期/计划/无出处/主观标 `assumption` | 事实与假设混淆，用户看不出哪条是自己的猜测 |
| 4 | 用户没说的字段留空串/空数组/0，不要瞎填 | 凭空信息被当成用户口述 |
| 5 | `confidence` 反映**用户自己**的确信程度，不是模型对观点正确性的判断 | 信心值语义漂移，校准统计失真 |
| 6 | `thesis` 与 `timeframe` 忠实原文，**不得推断、延长或改写时间跨度** | 半年被写成一年半 → 观察期与结算全部错位（**已发生并已修复**，§4.3.1） |

#### 5.1.2 确定性归一化层（`normalizeDraft`）

提示词是软约束，模型仍可能越界。因此解析结果进入**确定性归一化层**，规则全部可单测：

- `direction` 白名单校验，非法值回落 `neutral`
- `confidence` 收敛到 `[0,1]`，非数值归 0
- `evidence.type` 只允许 `fact` / `assumption`，其余一律降级为 `assumption`（宁可标假设，不可误标事实）
- 空白 `evidence` / `invalidation` 条目剔除
- **`invalidation_missing` 由 `invalidation` 数组长度单一决定**（消除「有条件却标缺失」的矛盾态）
- **`timeframe` 不做任何改写** —— 时间跨度忠实性是提示词层的保证，归一化层不得二次加工

实现见 `miniapps/agaistock/miniapp/node/server.mjs`，单测见 `miniapps/agaistock/test/pipeline.test.mjs`（`node --test`，23/23 通过）。

### 5.2 Stage 1 · 点评师层（可插拔）

> 详细设计见 **`docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md`**。本节为摘要，冲突时以设计文档为准。

Stage 1 被建模为**可插拔的「点评师」层**：一位点评师 = 一个有统一契约的组件。**新增点评师 = 新增一个目录 + 一条注册记录，不改评分口径。**

#### 5.2.1 统一契约 `ReviewVerdict`

```jsonc
{
  "reviewer_id": "anchor-chanlun", "reviewer_version": "0.1.0",
  "ran_at": "...", "status": "ok|partial|skipped|error",
  "data_refs": [{ "source": "tdx_kline", "params": {...}, "window": "...", "fetched_at": "..." }],
  "findings": [{
    "code": "CHAN_DAY_TOP_DIVERGENCE", "severity": "critical",
    "dimension": "位置与时机", "delta": -12,          // ← 归属维度 + 分差，评分靠这两个字段
    "claim": "...", "why": "...", "evidence_ref": [...], "suggested_fix": "..."
  }],
  "proposed_invalidation": [{ "desc": "...", "source": "...", "comparator": "below", "tolerance": 0.5 }],
  "horizon_hint": { "tier": "short", "rationale": "...", "checks": [...] },
  "caveats": ["背驰 active 标签仅表示锚点在窗口内，不代表背驰仍然成立；须复核是否已突破锚点"]
}
```

**契约硬约束**（违反即视为输出不合法）：

| 约束 | 理由 |
|---|---|
| 不以自由文本作为主要结论 | 自由文本无法聚合评分、无法做统计、无法累积认知档案 |
| 每条 finding 必须有 `dimension` + `delta` | 评分聚合完全依赖这两字段 |
| `dimension` 必须是已定义维度 | 评分口径跨期可比的前提（§5.6 校准统计依赖它） |
| `caveats` 不得省略适用限制 | 把机械结论当结论，是本产品最容易产生的误导 |
| `proposed_invalidation` **不得自动写入** observation | 用户自己的证伪条件被工具改写会破坏归因（§5.5） |

#### 5.2.2 点评师名录

| 点评师 | 职责 | 外部数据 | 本轮状态 |
|---|---|---|---|
| `anchor-chanlun` | 缠论三级别结构 → 与用户观点对照，指出位置/时机/证伪位上的偏差 | 全量 K 线 | **本轮上线** |
| `anchor-7dim` | 客观多空锚点：当前多空分 + 资金 6 阶段 | 全量行情资金 | 待迁入 |
| `audit-falsification` | 证伪条件是否明确、是否可观测、是否自相矛盾 | 无 | 待迁入 |
| `audit-fact` | 逐条断言核查：被数据支持 / 臆测 / 矛盾 | 行情/财务/商品价 | 待迁入 |
| `audit-logic` | 因果链跳跃、单因谬误、循环论证 | 无 | 待迁入 |
| `audit-bias` | 对照个人偏差档案检测认知偏差标签 | 个人档案库 | 待迁入 |

未来可继续上线：`audit-timing` / `audit-consistency` / `blind-review` 等。

#### 5.2.3 结论必须落库

每条点评结论写入 `reviews` 表（见 §7），**每次运行都追加一行**（重跑留痕），读取时取每位点评师的最新一版。这使认知档案得以回答：哪类问题最常命中你、哪条提示你最容易忽略、哪些维度长期失分。

#### 5.2.4 点评结论如何进入下游

- **评分**（§5.3）：所有点评师的 finding 按 `dimension` 汇总进五维评分，每一分可追溯到「哪位点评师的哪条发现」。
- **观察期**（§5.4）：`horizon_hint.tier` 决定可选档位**上限**（多家点评师取最保守）；`checks` 来自 `proposed_invalidation`。

### 5.3 Stage 2 · 聚合评分：`observation-score`

五个维度加权，**每一分必须可追溯到具体 Finding**：

| 维度 | 权重 | 判定来源 | 典型扣分 |
|---|---|---|---|
| 事实锚定 | 25% | `audit-fact` | 3 条断言 2 条无数据支撑 → -12 |
| 证伪条件 | 25% | `audit-falsification` + `anchor-chanlun` | 无证伪条件 → -25（致命项） |
| 逻辑链条 | 20% | `audit-logic` | 依据→结论有跳跃 → -8 |
| 位置与时机 | 15% | `anchor-7dim` + `anchor-chanlun` + `audit-timing` | 与资金阶段冲突 → -9 |
| 一致性 | 15% | `audit-consistency` | 与 3 天前观察矛盾且未说明 → -7 |

**维度集合固定**：新增维度必须显式改 `config/scoring.json`。理由：§5.6 的 Brier 校准统计要求跨期可比；若点评师可随意引入新维度，早期与后期观察的分数就不可比，校准曲线失去意义。

**聚合规则**：

- 同一维度有多位点评师贡献时，各自 `delta` **直接相加**（不是平均）—— 两位都认为有问题，扣分就该更多；`weight` 只用于调节某位点评师的影响力。
- **没有点评师贡献的维度，既不按 0 分算，也不按满分算**，而是从加权平均的分子与分母中一并剔除，并标记 `completeness: "no_reviewer"`。
  把"没人点评"当成 0 分 = 因系统未覆盖而惩罚用户；当成满分 = 把缺失粉饰成肯定。两者都让分数失真。**正确做法是剔除 + 明确标注。**
- 区分两件不同的事：**有点评师且结论中性**（`delta = 0` → `raw = 100`，真实满分）与**无人点评**（`raw = null`，缺失）。

**可解释性是硬约束**：输出必须包含 `score_breakdown: [{dimension, weight, raw, weighted, completeness, contributions: [{reviewer_id, finding_codes[], delta, weight}]}]`，以及 `scored_dimensions` 与 `score_denominator`（总分实际除以的权重和）。
用户看到"62 分"却不知道扣在哪，就无法改进 —— 可解释性直接决定这个产品能不能起到"提升认知"的作用。

### 5.4 Stage 3 · 自适应观察期：`observation-horizon`

LLM 在**限定档位内**选择，不得自由发挥：

| 信号强度 | 允许 `review_at` 档位（交易日） |
|---|---|
| 弱（单一依据 / 低置信） | 3 / 5 / 10 |
| 中 | 5 / 10 / 20 |
| 强（多依据且客观锚点同向） | 10 / 20 / 40 |
| 事件驱动（有明确催化剂日期） | 锚定催化剂后 + 5 / 10 / 20 |

输出结构：

```jsonc
{
  "start": "2026-11-24", "review_at": "2026-12-08",
  "allowed_window": ["2026-11-27", "2026-12-15"],
  "rationale": "锚点显示 S2 试盘阶段且 DDX 四窗同正，故取 10 日档",
  "confidence": 0.75,
  "checks": [
    { "id": "c1", "desc": "主力净流入连续为正",
      "source": "fund_flow.main_net", "comparator": "all_positive", "tolerance": null }
  ],
  "invalidation_triggers": ["钨价回落至关键位以下"]
}
```

**`checks` 必须来自可取数的数据源**（fund_flow / volume / ma / support_resistance …）。
若某 check 的数据源当前不可用，则该 check 标记为 `data_unavailable`，到期时记为"数据缺失"而非"未命中" —— 二者不可混淆。

信号强度不足时，**明确建议"暂不设观察期，先补数据/补证伪条件"**。这本身就是重要反馈，不是失败。

### 5.5 Stage 4 · 到期结算：`observation-settle`

由定时任务在 `review_at` 触发：

1. 拉观察期内实际走势（价格 / 量 / 资金 / 7 维阶段变化）
2. 用**当初写下的 `checks`** 逐条判定 —— 不得事后重编标准（防自欺的关键）
3. 归因映射：

| 归因 | 含义 | 评分影响 |
|---|---|---|
| 方向对 · 时机对 · 幅度对 | 完全正确 | 不扣分 |
| 方向对 · 时机错 | 判断对但早了/晚了 | 轻扣（时机维度） |
| 方向对 · 幅度错 | 方向对但幅度差远 | 中扣 + 标签"幅度过度自信" |
| 方向错 | 判断本身错 | 重扣 |
| **表述错** | 结论模糊无法判定 | **最重扣**（破坏了学习闭环本身） |
| 数据缺失 | 关键 check 数据源不可用 | 不扣分，标记 `unsettleable` |

4. 生成结算单（settlement）：逐条 check 的命中状态 + 归因 + 扣分明细 + 改进建议

### 5.6 Stage 5 · 认知档案：`observation-profile`

跨观察累积，是"提升认知"的落点：

- **偏差标签频次**：确认偏误 / 追高锚定 / 无证伪条件 / 仓位与逻辑脱节 / 叙事驱动 / 过度自信 / 损失厌恶 …每个标签带**证据链**（哪几次观察命中）
- **五维画像曲线**：识别长期拖后腿的维度
- **预测校准（Brier score 式）**：把每次观察的方向性判断 vs 实际涨跌做校准统计 —— 长期看"看多准确率"与"自评信心度"是否匹配。**信心高但准确率低 = 过度自信**，这是最可量化的认知缺陷
- **周期报告**：每周/每月输出「最大的认知漏洞 + 下阶段聚焦改进项」

### 5.7 护栏

- **数据引用强制**：skill 输出中的客观数值必须带 `data_ref`，无 `data_ref` 的数值在渲染层标为"未溯源"
- **角色隔离**：同一 skill 不得同时担任提出者与评估者；`blind-review` 走独立上下文
- **风险声明**：每份报告固定附「本工具用于个人观察复盘，不构成投资建议」
- **写操作需确认**：任何写入观察/结算/修改观察期的 MCP 工具调用，宿主侧应触发一次用户确认

---

## 6. 数据层

### 6.1 Provider Adapter 契约

```python
class MarketDataProvider(Protocol):
    name: str
    def daily_bars(self, symbols, start, end, adjust="post") -> pd.DataFrame: ...
    def fund_flow(self, symbol, window) -> pd.DataFrame: ...        # DDX/DDY/主力净流入
    def valuation(self, symbol) -> pd.DataFrame: ...                # PE/PB/分位
    def chips(self, symbol) -> pd.DataFrame: ...                    # 股东人数/集中度
    def news(self, symbol, window) -> list[dict]: ...
    def health(self) -> ProviderHealth: ...                         # 供数据源页展示连接状态
```

所有 provider 返回统一 schema，**字段映射与复权口径在适配层收口**。

### 6.2 缓存策略（强制）

| 数据 | 频率 | 方式 |
|---|---|---|
| 交易日历 / 标的列表 | 每日一次 | 全量落库 |
| 日线（后复权 + 复权因子） | 每日收盘后增量 | 落库，复盘只读本地 |
| 资金流 / 估值 / 筹码 | 每日收盘后增量 | 落库 |
| 盘中快照 | 按需，带 TTL | 内存缓存，不落库 |

**盘中禁止批量拉取** —— 这是 AKShare 被封 IP 的直接原因。

### 6.3 provider 选型

**主源：通达信 MCP**（`https://txmcp.tdx.com.cn:3001/txmcp`，streamable-http）。
理由：① 平台托管认证，**用户不需要任何 token**；② 覆盖面足够 —— 10 个工具含行情/K线/结构化指标/自然语言选股/研报/公告/资讯/宏观，且 `tdx_api_data` 可直达 TDX 内部 API（股东人数、十大流通股东、机构持股明细、研报一致预期、股本结构、行业产业链）；③ 用户本机已验证可用。

| 角色 | 选择 | 鉴权 | 理由 |
|---|---|---|---|
| **主源** | **通达信 MCP**（MCode 插件市场 `tdx-finance`） | 平台托管，无需 token | 免账号依赖、覆盖够、已在用 |
| 增强 | 东方财富妙想 `mx-ds-mcp` | OAuth2，凭证在 workbuddy 加密存储 | 11 工具含 `mx_ashare_finance_data`，与 seven-dim 完全匹配；MCode 市场无此条目，需另行适配 |
| 兜底 | Tushare | **需 token + 积分** | 按 `trade_date` 批量拉；因需独立账号与积分，仅作可选兜底 |
| 可选 | AKShare | 无 | 冷门数据补充；强制走缓存 + 指数退避重试 |

### 6.4 与 seven-dim 的衔接

`seven-dim-stock-analysis` 硬依赖 `mcp_mx-ds-mcp.mx_ashare_finance_data`。

**已核实**：东方财富妙想 MCP（`https://mxapi.eastmoney.com/mxds/v2/mcp`）确实提供 `mx_ashare_finance_data`，工具名与 skill 依赖**完全一致**。但该服务走 OAuth2，凭证加密存放在 workbuddy 的凭证库里，**MCode 侧无对应插件市场条目**，裸注册 URL 实测返回 401。

因此 v1 走 §6.4 路线 2：**由本项目自建 `mx_ashare_finance_data` 等价 MCP Server**，底层走通达信 `tdx_api_data`，实现同一契约（7 段 query、字段名对齐）。skill 原文不改，同时解除对特定第三方 MCP 的硬依赖。

实现时的字段覆盖**已于 2026-11-24 逐项实测完毕**（详见 §6.7）：

| seven-dim 分段 | 取数来源 | 状态（实测） |
|---|---|---|
| ① 趋势类 MA/MACD/BOLL/SAR/DMI | `tdx_kline` 取原始 K 线 + 自算 | ✅ 可自算 |
| ② 摆动类 KDJ/RSI/CCI/WR/BIAS | `tdx_kline` + 自算 | ✅ 可自算 |
| ③ 量价类 VOL/OBV/ATR/量比 | `tdx_kline` + 自算 | ✅ 可自算 |
| ④ 风险类 Beta/Sharpe/Alpha/回撤 | `tdx_kline` + 自算 | ✅ 可自算（本来就该自算） |
| ⑤ 估值类 PE/PB/PS/PCF 分位 | **iFinD** `get_security_indicators`（含近三年分位）+ `tdx_quotes.ExtInfo` | ✅ **完全覆盖** |
| ⑥ 资金流类 DDX/DDY/DDZ/主力净流入 | `tdx_api_data` `capital_flow` + iFinD DDE 家族 | ⚠️ 覆盖，**DDX 3日/DDY/DDZ 需自建**（§6.7.3） |
| ⑦ 筹码类 股东人数/集中度/融资余额 | `tdx_api_data` `gdyj`/`ltgd` + iFinD | ⚠️ 覆盖，**70%/90%集中度·平均成本·获利%·支撑压力位 两源皆缺**，走 seven-dim Fallback #3 |

> ✅ **「取数可行性验证」门禁已通过（2026-11-24）**，结论与逐项实测数据见 **§6.7**。
> 关键结论：**⑥资金流的最关键项 DDX 四窗口没有全部现成可用，但缺口是确定性的、可自建的**（iFinD 给 DDE 大单净量日度序列，5/10 日窗口已现成，3 日窗口自建即可），因此 **`anchor-7dim` 透镜无需更换锚点**，§5 的评分维度设计不受影响。
> ⚠️ 唯一必须硬性记住的坑：通达信自然语言入口会**误匹配**（§6.7.2），生产取数只用精确 `entry` + `fixedTag`。

### 6.5 模型与 Provider 配置

**业务内核将自带 `config/providers.json`（下一轮交付；本轮 `config/` 下只有 `reviewers.json` 与 `scoring.json`），不读宿主的 `config.yaml`。**
理由：D3 决定业务内核不依赖任何宿主的私有文件结构，否则"换宿主不重写"的承诺就不成立。

```json
{
  "providers": {
    "deepseek": {
      "api": "anthropic-messages",
      "base_url": "https://api.deepseek.com/anthropic",
      "api_key": "${DEEPSEEK_API_KEY}",
      "models": ["deepseek-v4-pro", "deepseek-flash"],
      "supports_audio": false
    },
    "minimax": {
      "api": "anthropic-messages",
      "base_url": "https://api.minimax.cn/anthropic",
      "api_key": "${MINIMAX_API_KEY}",
      "models": ["MiniMax-M3", "MiniMax-M3.1-Flash"],
      "supports_audio": true
    },
    "local": {
      "api": "openai-completions",
      "base_url": "http://127.0.0.1:11434/v1",
      "models": ["qwen2.5:14b"],
      "supports_audio": false
    }
  },
  "analysis_provider": "deepseek",
  "analysis_model": "deepseek-v4-pro",
  "asr_provider": "minimax",
  "asr_model": "MiniMax-M3.1-Flash"
}
```

- `asr_provider` 选中的 provider **必须** `supports_audio: true`（上例为 `minimax`）。
- `supports_audio: false` 的 provider 被 ASR 通道选中时，启动即报错（而非运行到一半失败）。
- 提供 `agaistock import-models --from <mcode config.yaml>` 一次性把宿主已配置的 provider 条目导入进来，**导入后两者独立**，宿主升级不影响本项目。
- 密钥只从环境变量读，**不入库、不写进配置文件**。

### 6.6 现有连接器事实记录（2026-11-24 实测）

| 连接器 | 端点 | 协议 | 鉴权 | 工具 | 本机状态 |
|---|---|---|---|---|---|
| 通达信 | `https://txmcp.tdx.com.cn:3001/txmcp` | streamable-http | **平台托管，无需用户 token** | **10 个（已在 MCode 连接并实测可用）**：`tdx_api_data`（直达 TDX/TQLEX 内部 API）/ `tdx_quotes` / `tdx_kline` / `tdx_lookup_stock` / `tdx_screener` / `tdx_indicator_select` / `tdx_ai_listening` / `tdx_security_deep_info` / `tdx_technical_indicator_lookup` / `tdx_technical_indicator_query` | ✅ **MCode 中已连接**（`connector__tdx-finance__*` 可调用） |
| 同花顺 iFinD | 平台托管 | — | 平台托管 | **5 个（已连接并实测可用）**：`get_security_indicators`（核心，指标库）/ `get_stock_summary` / `search_edb`（宏观行业指标）/ `search_news` / `search_trending_news` | ✅ **MCode 中已连接**（`connector__thsifind__*` 可调用） |
| 东方财富妙想 | `https://mxapi.eastmoney.com/mxds/v2/mcp` | streamable-http | **OAuth2**（accessToken + refreshToken，aes-256-gcm 加密存于 workbuddy 凭证库） | 11 个，含 `mx_ashare_finance_data`（与 seven-dim 依赖**完全一致**） | workbuddy 插件已缓存；**MCode 市场无此条目** |

实测记录：

- 两个端点**裸 POST `initialize` 均返回 401** —— 必须走平台托管认证或自带凭证，不能直接 `mcp create --url` 注册。
- 通达信的认证是平台注入的 managed auth header（凭证库里无独立条目）；东方财富妙想走标准 OAuth2 客户端流程（有 `client_id` + `redirect_uris`）。
- 通达信 skill 提示的能力边界：**港股支持检索/选股/研报，但不支持实时行情与 K 线；美股支持有限；单次返回建议 ≤ 100 条。**
- `tdx_api_data` 的 `entry` 命名空间形如 `TdxSharePCCW.tdxf10_gg_gdyj`，`fixedTag` 区分业务子类型 —— 自建等价层时需按此映射。
- 通达信连接器实际暴露的工具数比 workbuddy 缓存时记录的更多，新增了 `tdx_ai_listening` / `tdx_security_deep_info` / `tdx_technical_indicator_lookup` / `tdx_technical_indicator_query` —— **连接器能力会随版本漂移，接入层必须做能力探测而非硬编码工具清单**。

### 6.7 取数可行性验证结论（P0 第 0 步 · 已完成 2026-11-24）

> 验证标的：**002378 章源钨业**（深市 `setcode=0`）；对比基准：`seven-dim-stock-analysis` SKILL.md 的第⑤⑥⑦段原始取数清单。

#### 6.7.1 逐段覆盖度

| seven-dim 段 | 需求要点 | 通达信 | 同花顺 iFinD | 结论 |
|---|---|---|---|---|
| **⑤估值 20%** | PE/PB/PS/PCF 现值 + 近三年百分位、ROE、毛利率、净利率、资产负债率、归母净利同比、EPS、总市值、股息率 | 现值（`SYL`/`MGSY`/`MGJZC`/`ZSZ`/`ZGB`/`LTGB`/`HSL`）+ 股东人数序列 | **全覆盖**：PE(TTM) 22.81 / PB 6.42 / PS(TTM) 1.93 / PCF(TTM) −20.08 / **PE 近三年分位数 0.3115** / ROE 27.44% / 毛利率 24.71% / 净利率 8.60% / 资产负债率 68.94% / 归母净利同比 +279.17% / EPS 0.6 | ✅ **完全覆盖** |
| **⑥资金流 25%** | DDX 当日/3/5/10 日、DDY、DDZ、主力净流入 90 天序列、超大/大/中/小单拆分、控盘比例 | `capital_flow` preset：主力净额金额+占比、超大单净买入金额+占比、大单净买入金额+占比、主买净额（**20 行/页**）+ **复权因子表** | **DDE 大单净量(%)**、DDE 大单净额(万元)、**5 日 DDE**、**10 日 DDE**、主力净流入额占比（45 交易日） | ⚠️ **DDX 当日/5日/10日有，3 日窗口、DDY、DDZ 序列、中单/小单拆分、控盘比例缺** → 需自建（§6.7.3） |
| **⑦筹码 10%** | 股东人数+变化率、人均流通股+变化率、十大流通合计、机构持仓拆分、**70%/90% 集中度、平均成本、收盘获利%、支撑压力位**、概念板块、涨停天数、**融资融券 60 天日频序列** | 股东人数 32 期 + 人均流通股 + 环比 ✅；十大流通股东 18 期/180 明细 + 「实际流通A股」分母 ✅；概念板块 ✅（3 个 + 各周期涨跌幅）；两融余额 ✅ 但**月度**（37 期）；机构持仓 ✅；涨停天数 ❌ | — | ⚠️ **70%/90% 集中度、平均成本、收盘获利%、支撑压力位、涨停天数、日频两融 —— 两源皆缺** → 走 §6.7.3 自建/降级 |

#### 6.7.2 三个必须记录的踩坑

1. **通达信自然语言路由会误匹配，且返回「看起来合理但错误」的数据**。
   实测：查询「70%筹码集中度 / 90%筹码集中度」被规划到 `f9_ashare_share_pledge_ratio_trend`（**股权质押比例趋势**），返回了 52 行质押比例序列，无任何错误提示。
   → **结论：`tdx_security_deep_info` 的自然语言入口不可用于生产取数**。必须用 `tdx_api_data` 的**精确 `entry` + `fixedTag`**（已验证：`TdxSharePCCW.tdxf10_gg_jyds`/`zjlx`、`TdxSharePCCW.tdxf10_gg_gdyj`/`gdrs`·`ltgd`），或用 iFinD。
2. **iFinD 单次请求的指标数上限约 5 个，超出即降级**。
   实测：一次要 12 个估值指标，返回体附带「复杂问句降级提示」，只执行了 PE/PB/PS/PCF + PE 分位数，**静默丢弃**其余指标。
   → 接入层必须**拆分请求并校验返回指标数**，不能相信「没报错 = 全部拿到」。
3. **跨源同名指标口径不同，不可混用**。
   实测：PE(TTM) 通达信 `SYL` = **19.42**，iFinD PE(TTM) = **22.81**；而 EPS 两源一致（均为 0.6）。
   → 同一指标必须**锁定单源**，或显式记录口径（TDD/TTM/静态）后再比较。

#### 6.7.3 缺口的处置方案（已定）

| 缺口 | 处置 | 依据 |
|---|---|---|
| DDX 3 日窗口 | **自建**：DDX 日度 = iFinD DDE 大单净量(%)；3/5/10 日 = 移动均值；用通达信 `LTGB` 流通股本校验 | 5/10 日 DDE 与 DDX 可互算 |
| DDY / DDZ | **自建**：DDZ = 主力净额占比的 z-score（60 日窗口）；DDY 用「主力净额占比 × 当日涨跌幅」近似 | seven-dim 阈值本就要求"优先用自身历史分位数"（SKILL.md §⑦） |
| 中单/小单拆分、控盘比例 | **自建**：中/小单 = 成交总额 − 主力 − 超大 − 大；控盘比例 = 主力净额累计 / 流通市值 | 恒等式自洽 |
| 70%/90% 集中度、平均成本、收盘获利% | **降级**：改用 seven-dim 自带的 **Fallback #3**（股东人数变化 + 融资余额 + 十大流通合计 联合替代），缺项直接跳过、剩余项归一化 | seven-dim SKILL.md 已定义该降级路径 |
| 支撑位/压力位 | **自建**：由后复权 K 线算 pivot / MA20 / MA60 / 近期密集成交区 | §6.7.4 已拿到复权因子 |
| 日频两融序列 | **接受月度频率**：两融为月度披露，本无日频；按月度点参与趋势判断，不做日频加速率 | 披露频率决定，非数据缺陷 |
| 涨停天数 | **自建**：由日线 K 线统计（`close >= 涨停价` 且 `prev_close` 反推） | 通达信行情已给涨跌停价 |

#### 6.7.4 附带收获：复权因子直接可得（D6 风险解除）

`tdx_api_data` 的 `capital_flow` preset **同时返回 `adjustment_factor` 表**：14 条历史除权记录，含「精确复权因子」与「精确复权常数」（2026-06-26 / 2.6 / 2.2552 … 2010-10-29 / 1 / 0.15）。
→ D6「后复权序列 + 复权因子落库」**不再依赖任何额外接口**，直接落库即可。

#### 6.7.5 接入层工程约束（实测得出）

| # | 约束 | 说明 |
|---|---|---|
| 1 | **Windows 下必须用 `--args-file`** | `mcode-tools connector call --args '{...}'` 的双引号会被 PowerShell 剥离，报 `Connector arguments must be valid JSON` |
| 2 | 通达信 `capital_flow` 单页 20 行 | 90 天序列需翻页（`pageNo`/`pageSize`）或改用 iFinD 的 45 日窗 |
| 3 | iFinD 返回体是 **Markdown 表格字符串**（非结构化 JSON） | 需自写解析器，且注意其中的空值标记 `\t`（非交易日） |
| 4 | iFinD 行情类指标为**日频**，当日收盘前（<15:05）取到的是**昨日**数据 | 响应体自带 `trade_time_description` 提示，必须按提示标注数据日期 |
| 5 | 通达信 `tdx_quotes` 的 `ExtInfo` 已含估值/股本/换手率 | 单次调用即可拿到 PE/EPS/BVPS/股息率/总市值/总股本/流通股本/换手率，无需二次请求 |

#### 6.7.7 已验证可用的调用参数（接入层直接照抄）

| 用途 | 工具 | 参数（已实测返回正确数据） |
|---|---|---|
| 实时行情 + 估值快照 | `tdx_quotes` | `{code:"002378", setcode:"0"}` → `ExtInfo` 含 PE/EPS/BVPS/股息率/总市值/总股本/流通股本/换手率 |
| 日 K 线 | `tdx_kline` | `{code:"002378", setcode:"0", period:"4", tqFlag:"2"}`（后复权）+ `wantNum` 控制条数 |
| **资金流 + 复权因子** | `tdx_api_data` | `{entry:"TdxSharePCCW.tdxf10_gg_jyds", fixedTag:"zjlx", code:"002378"}` → preset `capital_flow` |
| **股东人数 / 人均流通股** | `tdx_api_data` | `{entry:"TdxSharePCCW.tdxf10_gg_gdyj", fixedTag:"gdrs", code:"002378", pageNo:"1", pageSize:"20"}` → preset `shareholder_count` |
| 十大流通股东 | `tdx_api_data` | `{entry:"TdxSharePCCW.tdxf10_gg_gdyj", fixedTag:"ltgd", code:"002378", pageNo:"1", pageSize:"10"}` → preset `top_float_shareholders` |
| 融资融券（月度） | `tdx_security_deep_info` | `{query:"查询 002378 章源钨业 的融资融券余额近 60 个交易日序列", entity_type:"A股代码"}` → `f9_ashare_sl_003` |
| 概念板块 | `tdx_security_deep_info` | `{query:"查询 002378 章源钨业 的所属概念板块完整列表", entity_type:"A股代码"}` → `f9_ashare_concept_board_membership` |
| **估值现值 + 近三年分位** | `thsifind.get_security_indicators` | `{market:"A股", query:"002378 章源钨业 最新一期PE(TTM)、PB、PS(TTM)、PCF(TTM)以及各自近三年百分位"}` |
| **财务分析指标** | `thsifind.get_security_indicators` | `{market:"A股", query:"002378 章源钨业 最新一期报告期的ROE(加权)、销售毛利率、销售净利率、资产负债率、归母净利润同比增长率、每股收益EPS"}` |
| **DDX 家族** | `thsifind.get_security_indicators` | `{market:"A股", query:"002378 章源钨业 最近45个交易日的DDX大单动向指标、DDY大单_diff、DDZ大单_z值，以及主力净流入占比、换手率"}` → 实返 `DDE大单净量`/`DDE大单净额`/`5日DDE`/`10日DDE`/`Z值` |

> ⚠️ **iFinD 每次请求的指标数必须 ≤ 5**，否则返回体带「复杂问句降级提示」并**静默丢弃**多余指标（实测：请求 12 个指标只执行 5 个）。
> ⚠️ **通达信 `tdx_security_deep_info` 的自然语言入口仅用于「已验证映射」的查询**（如上表最后两行的 `f9_ashare_sl_003` / `f9_ashare_concept_board_membership`）；**任何未被上表验证过的自然语言查询都不得用于生产取数**，因为它会误匹配且不报错（§6.7.2）。

#### 6.7.8 可复现的验证脚本（已入库）

`tools/probe/run-probe.mjs` —— 把本节的实测结论固化成**可重跑、可换标的**的探测脚本。

```bash
# 默认标的（002378 章源钨业，深市）
node tools/probe/run-probe.mjs

# 换标的（沪市 / 其他行业）
node tools/probe/run-probe.mjs --symbol 600519 --name 贵州茅台 --setcode 1

# 只跑某一条 + 落报告
node tools/probe/run-probe.mjs --only capital-flow --out coverage.json
```

脚本对 10 条探针逐一调用连接器，用**正则校验「拿到的是不是对题的数据」**（而不是只看有没有报错），最后输出 `HIT/MISS/ERROR` 汇总并写 JSON 报告。**这正是 §6.7.2 那个「误匹配却不报错」的坑所要求的防御方式** —— 接口返回 200 不等于取对了数据。

实测结果：**002378 章源钨业（深市/小金属）10/10 命中；600519 贵州茅台（沪市/白酒）10/10 命中** —— 覆盖度结论对深沪两市、两类行业均成立。

#### 6.7.9 门禁结论

**P0 第 0 步通过。** ⑤估值完全覆盖；⑥资金流、⑦筹码的核心判据覆盖，缺口全部有确定性处置方案（自建或 seven-dim 已定义的降级路径），且无一项缺口会阻断 seven-dim 的**多空判定**——只影响部分子项的精细度，缺失项按 seven-dim 既有规则归一化。
→ **可进入 P0 开发**。

---

## 7. 存储模型（SQLite）

```sql
observations(id, symbol, name, created_at, direction, thesis, confidence,
             timeframe, trigger, position_json, raw_text, horizon_id,
             supersedes_id, deleted_at)  -- 修订版本指向被修订行；只追加不原地改
                                         -- deleted_at 非空 = 软删除（从列表隐藏，
                                         --   不参与评分/观察期/校准统计，物理行保留）
assertions(id, observation_id, text, type, verify_target, status)   -- fact/assumption
reviews(id, observation_id, reviewer_id, reviewer_version, ran_at, status,
       duration_ms, verdict_json, created_at)
         -- 每位点评师每次运行都追加一行（重跑留痕）；
         -- 读取时取每位 reviewer 的最新一版用于展示与评分
findings(id, observation_id, reviewer_id, code, severity, dimension, delta,
         claim, why, evidence_ref_json, suggested_fix)
horizons(id, observation_id, start, review_at, rationale, confidence,
         signal_strength, status)
checks(id, horizon_id, desc, source, comparator, tolerance, result, evaluated_at)
settlements(id, horizon_id, attribution, score_delta, detail_json)
scores(id, observation_id, dimension, raw, weighted, completeness,
       findings_json, total, score_denominator)
bias_profile(tag, first_seen, last_seen, count, evidence_json)
market_cache(symbol, trade_date, kind, payload_json, source, fetched_at,
             PRIMARY KEY(symbol, trade_date, kind))
```

**观察记录只追加不修改**：修订走新版本行，保留 `supersedes_id`。认知档案依赖历史完整性，不能被覆盖。

**删除是软删除**：置 `deleted_at` 而非物理删除。物理删除会毁掉 §5.6 校准统计所需的样本。软删的观察从列表隐藏，且不参与评分聚合、观察期计划与校准统计；其 `reviews` 行保留供审计与排障。详见 `docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md` §7。

---

## 8. 分期范围

### P0 · 核心闭环（先只做这个）
- ~~**第 0 步（前置门禁）**：取数可行性验证~~ ✅ **已完成（2026-11-24），门禁通过** —— 结论见 **§6.7**
  - ⑤估值 完全覆盖；⑥资金流、⑦筹码核心判据覆盖，缺口均有确定性处置（§6.7.3）
  - **附带解除 D6 风险**：通达信 `capital_flow` 直接返回复权因子表
  - **附带发现两个生产级坑**（§6.7.2）：通达信自然语言路由会误匹配、iFinD 单次指标数超限会静默降级
  - 下一步：把这三条实测约束写进接入层（§6.7.5），并用 2–3 只真实标的跑通七段取数
- 数据层：**双源 Provider Adapter** —— 通达信主源 + iFinD 增强 + 本地缓存 + SQLite（§6.3、§6.7）
- 模型通道：ASR 通道（§5.0）+ 分析通道，各自可配
- **Stage 1 = 点评师层**（§5.2）：契约 + 注册表 + `reviews` 落库；本轮上线 `anchor-chanlun`（缠论）
  - 详细设计：`docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md`
  - 其余点评师（`anchor-7dim` / `audit-*`）迁入：下一轮
- Stage 2–5：`observation-score`（接入点评师维度贡献）/ `observation-horizon`（接入 `horizon_hint` 档位上限与 checks）/ `observation-settle` / `observation-profile`
- 接入：`agaistock-mcp`，**P0 仅 stdio**（http transport 留到 P3，接口不变）
- **宿主 / UI：Mini App 录入面**（D10）—— 垂直切片已实测可行（§4.3.1），在现有 `agaistock` Mini App 上扩展，而非回到「纯对话驱动」
- **补测三项已探明但未走通的链路**（§4.3.1）：
  1. 真实麦克风 → `speech.transcribe` 端到端
  2. `context.tool` 调 `agaistock-mcp`（需在 `miniapp.json` 声明 `toolAccess`，探测通过后再声明）
  3. `context.hostConnector` 调通达信 —— **现已具备前置条件**（连接器已在 MCode 连接并实测可用）
- **观察卡可删除**（软删除，§7）
- 交付判据：**在 Mini App 里**口述一条观察 → 拿到点评师意见 + 评分 + 观察期 → 到期自动出结算单

### P1 · 界面
- **Mini App 内扩展**（已不需再做选型）：评分雷达、结算单、认知档案看板、偏差标签墙、批量复盘模式（D7）
- 独立 Tauri 桌面壳（可选，P3 再评估）：唯一优势是能脱离 MCode 独立存在

### P2 · 成长
- 认知档案看板 + Brier 校准曲线 + 周期报告
- `audit-timing` / `audit-consistency` / `blind-review`

### P3 · 扩展
- 移动端、产业链知识图谱、多市场

---

## 9. 部署形态与数据边界（本地优先）

### 9.1 运行拓扑

```
┌──────────────── 用户的电脑（唯一一台机器） ────────────────┐
│                                                          │
│  MCode 桌面 App                                          │
│   └── 拉起 → agaistock-mcp（本地 Python 子进程，stdio）    │
│                ├── 读写 → data/agaistock.db（SQLite）     │
│                ├── 读取 → skills/*/SKILL.md                │
│                ├── 调用 → 行情 API（iFinD / Tushare…）      │
│                └── 调用 → LLM API（DeepSeek / MiniMax…）   │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

**MCP server 不是"部署在服务器上的服务"**，而是宿主拉起的本地子进程，通过 stdio 通信，**不监听任何端口**。
注册方式（实现阶段执行一次，走 MCode 的 MCP 管理命令 `mcp create`）：

```
name:        agaistock
transport:  stdio
command:     python
args:        ["-m", "agaistock.mcp"]
env:         { AGAISTOCK_HOME: "D:\\workroom\\agaistock" }
```

### 9.2 数据位置

| 数据 | 位置 | 是否出网 |
|---|---|---|
| 观察记录 / 断言 / 评分 / 扣分明细 | `data/agaistock.db` | 否 |
| 认知档案（偏差标签、校准曲线） | 同上 | 否 |
| 行情缓存（K线 / 资金流 / 财务） | 同上 | 否 |
| 技能定义 | `skills/*/SKILL.md` | 否 |
| 模型调用上下文（口述文本、结构化草稿） | 内存 + LLM API | **是**（→ LLM 提供商） |
| 行情查询请求（股票代码、字段名） | 行情 API | **是**（→ 行情提供商） |

**除上述两行外，无任何数据离开本机。** 备份 = 拷贝 `.db` 文件；迁移 = 拷贝整个仓库目录。

### 9.3 隐私与降级

- **LLM 出网**：口述文本必须发给模型才能被理解。默认走云端模型；如需更私密，在 provider 配置中指向本地推理端点（Ollama / vLLM），业务代码不变。
- **可关闭外发的部分**：行情缓存、观察记录、认知档案的读写全程本地，无外部依赖。
- **加手机端时**（P3）：接入层切换到 http transport，监听**局域网地址 + 令牌鉴权**。**不暴露公网端口**；若必须跨网，走内网穿透 / 零信任组网，而非裸暴露 MCP 端口。

---

## 10. 待用户确认的点（已收敛）

**已定死、无需再问**（如有异议请指出）：
- 观察记录**只追加不修改**，修订走新版本行 + `supersedes_id`（§7）
- 评分五维**权重做成 `config/scoring.json`**，默认值见 §5.3
- ASR 与分析模型**分两条独立通道**（§5.0）；DeepSeek 只能做分析模型，不能做 ASR
- 业务内核**自带 provider 配置**（`config/providers.json`，下一轮交付），不读宿主 `config.yaml`（§6.5）
- **P0 主数据源 = 通达信 MCP**（D5、§6.3），无需再比较 iFinD / Tushare
- **seven-dim 取数走自建等价 MCP**，底层用通达信实现（§6.4）
- **UI 主线 = Mini App**（D10），不再回到「纯对话驱动」；垂直切片已跑通（§4.3.1）
- **解析层 = 6 条提示词硬规则 + 确定性归一化层**（D11、§5.1.1、§5.1.2）

**仍需用户拍板的**：

1. ~~**是否现在就跑「取数可行性验证」**~~ ✅ **已完成，门禁通过（§6.7）**
   结论：通达信 + 同花顺 iFinD 双源互补，⑤估值完全覆盖、⑥资金流与⑦筹码核心判据覆盖；缺口（DDX 3日窗口/DDY/DDZ/70%·90%集中度/支撑压力位）均有确定性处置方案，无一阻断多空判定。
   **后续动作**：用 2–3 只真实标的跑通七段取数，把 §6.7.5 的三条工程约束落进接入层。

2. **P0 的第一个验证标的**：建议用 2–3 只你正在跟踪的票真实跑一轮，
   验证"观察卡 → 评分 → 观察期 → 结算单"这条链的输出你看得懂、愿意用。
   （本轮验证用的是 002378 章源钨业作为**技术**样本；它同时也是一份真实观察卡的标的，可直接复用。）

3. **`mx-ds-mcp`（东方财富妙想）要不要一并接进 MCode**
   它有现成的 `mx_ashare_finance_data`，seven-dim 可以零改动直接用。
   但需 OAuth2，MCode 插件市场目前无此条目 —— 需要额外适配工作。
   **现在的判断较前次下调必要性**：通达信 + iFinD 已在实测中覆盖了 seven-dim 全部七段的**核心判据**（§6.7.1），mx-ds-mcp 的边际价值主要在「省掉自建等价层的工作量」，而非补数据缺口。
   建议：**P0 先不接**，把 §6.7.3 的自建项做完后再评估。

---

## 11. 已识别风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 无公网/无云服务 | 单机可用，多设备需另配通道 | 本地优先即目标态；跨网需求延后到 P3 且走私有通道 |
| 东财按源 IP 限流封禁 | 数据获取失败 | 商业连接器主源 + 缓存 + 不盘中批量 |
| 复权跨源口径不一致 | 判断结论反转 | 后复权+复权因子落库，单源自洽 |
| LLM 编造行情数字 | 分析结论不可信 | `data_ref` 强制 + 无溯源标注 |
| 事后重编判定标准 | 自欺，闭环失效 | checks 落库不可变，结算只读 |
| 观察量不足以做统计校准 | Brier 校准无意义 | 档案层需 ≥30 条样本才出结论，否则只做提示 |
| dsh/MCode 版本变更 | 宿主侧接口变动 | 业务内核不依赖宿主私有 API，只走标准 MCP |
| UI 载体单点依赖 MCode | Mini App 不可用时无备用录入路径 | 录入面与业务内核解耦（D3/D10）；Tauri 壳作为 P3 逃生口；口述文本可随时降级为文字输入 |
| **数据源语义误匹配（实测已发生）** | 取到「看起来合理但完全错误」的数据（如把「筹码集中度」取成「质押比例」），污染观察评分且**无错误提示** | 通达信只用精确 `entry`+`fixedTag`，**禁用自然语言入口**做生产取数；iFinD 返回后校验指标名与请求一致；缺项必须显式标注为缺失而非静默填空 |
| **跨源同名指标口径不一致** | PE 通达信 19.42 vs iFinD 22.81，混用会让估值判断漂移 | 同一指标**锁定单源**；跨源仅做交叉校验并记录口径（TTM/静态/动态） |
| **iFinD 指标数超限静默降级** | 以为 12 个指标全拿到了，实际只执行 5 个 | 接入层拆分请求（≤5 指标/次）+ **校验返回指标数与请求一致**，不一致即报错 |
| **两融/股东数据为季度·月度频率** | 拿不到日频两融加速率 | 按披露频率参与趋势判断，不做日频派生；该限制是市场披露制度而非数据缺陷 |
