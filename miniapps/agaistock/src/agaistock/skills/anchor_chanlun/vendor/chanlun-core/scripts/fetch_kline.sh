#!/bin/bash
# 缠论分析师 - 多周期 K 线抓取脚本
#
# 用法：
#   ./fetch_kline.sh <source> <code> [options]
#
# source:
#   tdx   通达信 MCP（需在 WorkBuddy 会话中调用工具，见下方说明）
#   em    东方财富 HTTP（日线/周线首选，历史完整）
#   sina  新浪 HTTP（30 分钟首选，可取约 1023 根 ≈ 6 个月）
#
# options:
#   -p, --period  week | day | m30     分析级别（默认 day）
#   -b, --begin   YYYYMMDD             起始日期
#   -e, --end     YYYYMMDD             结束日期
#   -n, --num     数字                 取多少根（sina 用，上限 1023）
#   -o, --out     文件名               输出文件（默认 kline_<period>.json）
#   -h, --help
#
# 示例：
#   ./fetch_kline.sh em   600967 -p week -b 20160101     # 周线 约 547 根 / 10 年
#   ./fetch_kline.sh em   600967 -p day  -b 20240701     # 日线 约 540 根 / 2 年
#   ./fetch_kline.sh sina 600967 -p m30  -n 500          # 30 分钟 500 根（与日线对齐，推荐）
#   ./fetch_kline.sh sina 600967 -p m30  -n 1023         # 30 分钟 1023 根（细看模式，窗口偏长）
#   ./fetch_kline.sh tdx  600967 -p m30
#
# 数据源能力对照（实测）：
#   级别    东方财富 em            新浪 sina               通达信 tdx
#   周线    全历史 klt=102         仅近期                   period=5
#   日线    全历史 klt=101         scale=240                period=4
#   30分钟  仅约 248 根(约1.5月)   1023 根(约6个月)         period=2，wantNum 上限约 800
#
# 建议搭配：周线/日线走 em，30 分钟走 sina；需要更长 30 分钟历史时走 tdx。
#
# ── 窗口取舍原则（重要，别按"越长越好"抓数）────────────────────────────
# 识别规则（包含处理/分型/笔/段）是尺度不变的：识别出一个中枢所需的 K 线根数
# 在各级别基本相同（约 45-75 根）。所以要让三个级别"看到可比数量的结构"，三个
# 级别的窗口根数就该落在同一量级（250-600 根），而不是让自然时间跨度随意拉开。
#
#   级别     推荐根数    约合自然跨度   预期中枢数
#   周线     250-500     5-10 年        4-8 个
#   日线     250-600     1-2.5 年       4-8 个
#   30分钟   400-600     3-4 个月       6-10 个
#
# 窗口下界 = 当前未完成走势的起点 + 至少 2 个完整中枢 + 1 个前中枢（供背驰比较）。
# 窗口上界 = 再多只是压扁图表、稀释最近中枢的参照权重，边际收益为零。
# 跨度失衡的真实代价：① 结构密度失衡会让买卖点泛滥、区间套确认门槛被拉低；
# ② 上游背驰若早于下游窗口起点，下游根本无从确认，区间套结论就是伪结论。
#
# 所以：30 分钟不要无脑取 1023 根。要与日线对齐就取 -n 500；只有在明确要"把
# 当前日线一笔的内部结构看清楚"时才用 -n 1023，并在报告中说明该级别窗口偏长。
# ─────────────────────────────────────────────────────────────────────

set -e

usage() {
    sed -n '2,53p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
}

[[ $# -lt 1 ]] && usage
[[ "$1" == "-h" || "$1" == "--help" || "$1" == "help" ]] && usage

SOURCE=$1
CODE=$2
[[ -z "$CODE" ]] && { echo "❌ 请提供股票代码"; exit 1; }

PERIOD="day"
BEGIN=""
END=""
NUM=""
OUTFILE=""

shift 2
while [[ $# -gt 0 ]]; do
    case "$1" in
        -p|--period) PERIOD="$2"; shift 2 ;;
        -b|--begin)  BEGIN="$2";  shift 2 ;;
        -e|--end)    END="$2";    shift 2 ;;
        -n|--num)    NUM="$2";    shift 2 ;;
        -o|--out)    OUTFILE="$2"; shift 2 ;;
        # 兼容旧写法：fetch_kline.sh em 600967 20240701 20260911
        [[0-9]]*)    if [[ -z "$BEGIN" ]]; then BEGIN="$1"; else END="$1"; fi; shift ;;
        *)           echo "❌ 未知参数: $1"; exit 1 ;;
    esac
done

case "$PERIOD" in
    week|day|m30) ;;
    *) echo "❌ 未知级别: ${PERIOD}  (支持 week / day / m30)"; exit 1 ;;
esac

OUTFILE=${OUTFILE:-"kline_${PERIOD}.json"}

# --- 周期 → 各数据源参数 ---
case "$PERIOD" in
    week) EM_KLT=102; SINA_SCALE=240; SINA_LEN=1023; TDX_PERIOD=5; DEFAULT_BEGIN="20160101" ;;
    day)  EM_KLT=101; SINA_SCALE=240; SINA_LEN=1023; TDX_PERIOD=4; DEFAULT_BEGIN="20240701" ;;
    m30)  EM_KLT=30;  SINA_SCALE=30;  SINA_LEN=500;  TDX_PERIOD=2; DEFAULT_BEGIN="20260101" ;;
esac

# 东方财富接口必需的 ut 令牌（缺失会返回空响应，HTTP=000 / exit 52）
EM_UT="fa5fd1943c7b386f172d6893dbfba10b"

# 沪/深/北 判断
case "$CODE" in
    6*)      EM_SECID="1.$CODE"; SINA_SYM="sh$CODE"; TDX_SETCODE=1 ;;
    0*|3*)   EM_SECID="0.$CODE"; SINA_SYM="sz$CODE"; TDX_SETCODE=0 ;;
    8*|4*)   EM_SECID="0.$CODE"; SINA_SYM="bj$CODE"; TDX_SETCODE=2 ;;
    *)       EM_SECID="0.$CODE"; SINA_SYM="sz$CODE"; TDX_SETCODE=0 ;;
esac

BEGIN=${BEGIN:-$DEFAULT_BEGIN}
END=${END:-$(date +%Y%m%d)}
NUM=${NUM:-$SINA_LEN}

echo "数据源 : $SOURCE"
echo "标的   : ${CODE}  (em=${EM_SECID}  sina=${SINA_SYM}  tdx setcode=${TDX_SETCODE})"
echo "级别   : $PERIOD"
echo "输出   : $OUTFILE"
echo ""

case "$SOURCE" in
    em)
        echo "区间: $BEGIN → $END"
        curl -s -m 40 -A "Mozilla/5.0" \
          "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=${EM_SECID}&ut=${EM_UT}&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58&klt=${EM_KLT}&fqt=1&beg=${BEGIN}&end=${END}" \
          -o "$OUTFILE"
        ;;
    sina)
        echo "取数: ${NUM} 根"
        curl -s -m 40 -A "Mozilla/5.0" \
          "https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData?symbol=${SINA_SYM}&scale=${SINA_SCALE}&ma=no&datalen=${NUM}" \
          -o "${OUTFILE}.sina.tmp"
        # 新浪格式 → 东方财富统一格式
        python3 - "$OUTFILE" <<'PYEOF'
import json, sys
out = sys.argv[1]
src = out + ".sina.tmp"
raw = json.load(open(src, encoding="utf-8"))
if not raw:
    print("❌ 新浪返回空数据")
    sys.exit(1)
klines = []
for r in raw:
    d = str(r["day"])
    d = d[:16] if len(d) > 16 else d          # "2026-03-11 10:30:00" → "2026-03-11 10:30"
    klines.append(f"{d},{float(r['open']):.2f},{float(r['close']):.2f},"
                  f"{float(r['high']):.2f},{float(r['low']):.2f},"
                  f"{float(r['volume']):.0f},{float(r.get('amount') or 0):.0f}")
json.dump({"data": {"klines": klines, "_source": "sina"}},
          open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"   已转换 {len(klines)} 根")
PYEOF
        rm -f "${OUTFILE}.sina.tmp"
        ;;
    tdx)
        cat <<TDXEOF
⚠️  通达信 MCP 无法从命令行直接调用，请让 Agent 在会话中执行：

  1) tdx_lookup_stock keyword="$CODE"
       → 拿到标准化 code / setcode / range

  2) tdx_kline code="$CODE" setcode="$TDX_SETCODE" period="$TDX_PERIOD" wantNum="800"
       → 拿到 ${PERIOD} K 线（ListHead + AttachInfo）

  3) 把响应保存为 tongdaxin_kline.json，然后转换：
       python3 scripts/tdx_to_em_format.py tongdaxin_kline.json $OUTFILE

  4) 跑缠论分析：
       python3 scripts/chan_analyze.py . --level $PERIOD

提示：TDX 的 wantNum 上限约 800。
      30 分钟级别建议改用：./fetch_kline.sh sina $CODE -p m30 -n 1023
TDXEOF
        exit 1
        ;;
    *)
        echo "❌ 未知数据源: $SOURCE（支持 tdx / em / sina）"
        exit 1
        ;;
esac

# --- 抓取结果自检 ---
echo ""
echo "文件大小: $(wc -c < "$OUTFILE") 字节"
python3 - "$OUTFILE" "$PERIOD" <<'PYEOF'
import json, sys
f, period = sys.argv[1], sys.argv[2]
data = json.load(open(f, encoding="utf-8"))
klines = data.get("data", {}).get("klines", [])
if not klines:
    print("❌ 无 K 线数据，请检查股票代码或日期范围")
    sys.exit(1)
print(f"共 {len(klines)} 根 K 线")
print(f"起始: {klines[0].split(',')[0]}")
print(f"结束: {klines[-1].split(',')[0]}")

if period == "day" and len(klines) < 250:
    print(f"⚠️ 日线仅 {len(klines)} 根，中枢样本偏少（理想 250-600 根）")
if period == "m30" and len(klines) < 400:
    print(f"⚠️ 30 分钟 K 线仅 {len(klines)} 根，中枢与段的识别样本偏少")
    print("   建议改用：./fetch_kline.sh sina <code> -p m30 -n 500")
if period == "m30" and len(klines) > 600:
    print(f"⚠️ 30 分钟取了 {len(klines)} 根，超出理想区间 250-600 根：")
    print("   该级别结构密度会高于周线/日线，短期买卖点容易泛滥、区间套确认门槛被拉低。")
    print("   若要与日线对齐请改用 -n 500；确实需要细看日线一笔的内部结构时才保留 1023，")
    print("   并在报告中声明「30 分钟窗口偏长，其早期中枢仅作背景」。")
if period == "week" and len(klines) > 600:
    print(f"⚠️ 周线取了 {len(klines)} 根（约 {len(klines)/52:.0f} 年），超出理想区间；"
          f"更早的中枢对当下走势已无约束力，只会压扁图表")
PYEOF
