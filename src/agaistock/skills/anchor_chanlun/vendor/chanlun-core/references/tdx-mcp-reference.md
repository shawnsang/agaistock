# 通达信 MCP (TDX-finance) 速查

> 本文件收录与「缠论分析师」专家对接所需的通达信 MCP 工具要点。完整规范见 `~/workbuddy/connectors-marketplace/connectors/tdx-connector/skills/SKILL.md`。

## 核心工具（缠论分析用到的）

| 工具 | 用途 | 关键参数 |
|---|---|---|
| `tdx_lookup_stock` | 代码检索 | `keyword`, `range`(GP/HK-GP/MG-GP/ZS/JJ) |
| `tdx_quotes` | 实时行情 | `code`, `setcode`(1=沪/0=深/2=北交所), `hasCalcInfo` |
| `tdx_kline` | K 线 | `code`, `setcode`, `period`(0-11), `wantNum` |
| `tdx_indicator_select` | 自然语言查指标 | `message`（含代码） |
| `tdx_api_data` | 深度数据 | `entry`, `fixedTag`, `code` |

## K 线周期 (period)

| 值 | 周期 |
|---|---|
| 0 | 5 分钟 |
| 1 | 15 分钟 |
| 2 | 30 分钟 |
| 3 | 60 分钟 |
| **4** | **日线（默认）** |
| 5 | 周线 |
| 6 | 月线 |
| 7 | 1 分钟 |
| 9 | 日 K |
| 10 | 季线 |
| 11 | 年线 |

## 沪/深判断 (setcode)

| 代码前缀 | setcode | 市场 |
|---|---|---|
| 60xxxx | 1 | 沪市 |
| 00xxxx / 30xxxx | 0 | 深市 |
| 8xxxxx | 2 | 北交所 |
| 港股 00700 | 6 | 港股（需 `target=1`） |
| 美股 AAPL | 5 | 美股 |

## K 线返回结构

```json
{
  "ListHead": ["日期", "开盘", "最高", "最低", "收盘", "成交量", "成交额"],
  "AttachInfo": [
    ["20240901", 12.34, 12.50, 12.20, 12.45, 12345.0, 67890.0],
    ["20240831", 12.30, 12.40, 12.20, 12.34, 11000.0, 65000.0]
  ]
}
```

**字段顺序**：日期 / 开 / 高 / 低 / 收 / 量 / 额
**日期格式**：YYYYMMDD（紧凑）
**默认排序**：**倒序**（最新在前），需用 `tdx_to_em_format.py` 自动转升序

→ 东方财富格式字段顺序：日期 / 开 / 收 / 高 / 低 / 量 / 额

## 已知限制与应对

| 场景 | 限制 | 应对 |
|---|---|---|
| 港股 K 线 | 数据行可能为空 | 降级东方财富 |
| 主营构成 (jyfx) | 上游 SQL 持续报错 | 用 tdx_indicator_select |
| 龙虎榜（个股）| 未上榜报数据库错误 | 改查全市场 |
| 龙虎榜（全市场）| 非交易日返回空 | 传具体日期 |
| 北向资金 | 数据源不稳定 | 用 screener 筛个股 |
| 估值历史 | 部分个股返回空 | 用 indicator_select |
| 基金指标 | 只认代码不认名称 | 先查代码 |

## 缠论三级别分析推荐调用流程

```
1. tdx_lookup_stock keyword="600967"
   → 拿到标准 code + setcode + range

2. tdx_indicator_select message="600967 的 PE 和 PB"
   → 拿到估值指标（用于报告头部数据卡片）

3. 分别拉取三个级别的 K 线
   tdx_kline code="600967" setcode="1" period="5" wantNum=500   → 周线
   tdx_kline code="600967" setcode="1" period="4" wantNum=500   → 日线
   tdx_kline code="600967" setcode="1" period="2" wantNum=800   → 30 分钟
   → 各自拿到 ListHead + AttachInfo（倒序，最新在前）

4. 每个级别分别保存并转换
   python3 scripts/tdx_to_em_format.py tdx_week.json  kline_week.json
   python3 scripts/tdx_to_em_format.py tdx_day.json   kline_day.json
   python3 scripts/tdx_to_em_format.py tdx_m30.json   kline_m30.json
   → 自动转统一格式 + 升序排序
   ⚠️ 若 30 分钟要取更长历史，且 TDX 单次 wantNum 不足，
      可改用：bash scripts/fetch_kline.sh sina 600967 -p m30 -n 1023

5. 三级别结构识别
   python3 scripts/chan_analyze.py . --level week
   python3 scripts/chan_analyze.py . --level day
   python3 scripts/chan_analyze.py . --level m30
   → 输出 chan_analysis_week.json / _day.json / _m30.json

6. 三级别统合
   python3 scripts/chan_multi_level.py . --symbol 600967 --name "内蒙一机"
   → 输出 chan_multi_level.json（共振档位 + 区间套确认 + 操作定性）

7. 生成报告 + 本地预览
   python3 scripts/render_multi_report.py . --title "内蒙一机（600967）· 缠论三级别分析报告"
   node templates/server.js
```

### 各数据源在三个级别上的实测能力

| 级别 | 东方财富 em | 新浪 sina | 通达信 tdx |
|---|---|---|---|
| 周线 | 全历史 `klt=102` | 仅近期 | `period=5` |
| 日线 | 全历史 `klt=101` | `scale=240` | `period=4` |
| 30 分钟 | ⚠️ 仅约 248 根（约 30 个交易日） | ✅ 1023 根（约 6 个月） | `period=2`，wantNum 上限约 800 |

**建议**：周线/日线用 em（无需鉴权、历史完整），30 分钟用 sina；TDX MCP 作为精度与一致性的补充。

## OAuth 启用

通达信 MCP 端点：`https://txmcp.tdx.com.cn:3001/txmcp`

1. 打开 WorkBuddy → 连接器管理
2. 找到「tdx-connector」
3. 点击「信任」启用
4. 第一次调用会自动跳 OAuth 登录页
5. 用通达信账号授权即可

---

参考：完整工具列表见 `connectors-marketplace/connectors/tdx-connector/skills/SKILL.md`