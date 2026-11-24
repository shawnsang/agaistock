#!/usr/bin/env python3
"""
TDX MCP K线数据 → 东方财富格式转换器

输入：tongdaxin_kline.json（TDX MCP 的 tdx_kline 工具返回结果）
      包含 ListHead + AttachInfo 结构

输出：kline_latest.json（东方财富格式，兼容 chan_analyze.py）
      {"data": {"klines": ["YYYY-MM-DD,o,c,h,l,v,a", ...]}}

TDX K线返回结构（参考 tdx-mcp-quick-reference.md）：
  ListHead: ["日期", "开盘", "最高", "最低", "收盘", "成交量", "成交额", ...]
  AttachInfo: [["20240901", 12.34, 12.50, 12.20, 12.45, 12345.0, 67890.0], ...]

注：
  - TDX 字段顺序：日期、开、高、低、收、量、额
  - 东方财富字段顺序：日期、开、收、高、低、量、额
  - 需要交换"收"和"高/低"的顺序
"""
import json
import os
import sys
from datetime import datetime


def parse_tdx_date(d):
    """TDX 日期格式多种：'20240901' / '2024-09-01' / '2024/09/01'，统一为 YYYY-MM-DD"""
    s = str(d).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    if len(s) == 10 and "-" in s:
        return s
    if "/" in s:
        return s.replace("/", "-")
    raise ValueError(f"无法识别的日期格式: {d}")


def tdx_to_em_format(tdx_data, source_name="TDX MCP"):
    """把 TDX MCP K线响应转成东方财富格式"""
    if not isinstance(tdx_data, dict):
        raise ValueError("TDX 数据应为 dict 类型")

    # 兼容两种 TDX 返回结构
    head = tdx_data.get("ListHead", [])
    rows = tdx_data.get("AttachInfo", tdx_data.get("AttachInfoList", []))

    if not head or not rows:
        # 兜底：可能直接是 list
        if isinstance(tdx_data, list) and tdx_data:
            rows = tdx_data
            head = ["日期", "开盘", "最高", "最低", "收盘", "成交量", "成交额"]

    if not rows:
        raise ValueError("TDX 数据无 K线行（AttachInfo 为空）")

    # 找字段下标
    def col_idx(names):
        out = {}
        for n in names:
            for i, h in enumerate(head):
                if str(h).strip() == n:
                    out[n] = i
                    break
        return out

    idx = col_idx(["日期", "开盘", "最高", "最低", "收盘", "成交量", "成交额"])

    missing = [k for k in ["日期", "开盘", "收盘", "最低", "最高", "成交量"] if k not in idx]
    if missing:
        raise ValueError(f"TDX 数据缺少必需字段：{missing}，ListHead={head}")

    klines = []
    for row in rows:
        if len(row) < 7:
            continue
        try:
            date = parse_tdx_date(row[idx["日期"]])
            o = float(row[idx["开盘"]])
            h = float(row[idx["最高"]])
            l = float(row[idx["最低"]])
            c = float(row[idx["收盘"]])
            v = float(row[idx["成交量"]])
            a = float(row[idx["成交额"]]) if "成交额" in idx and idx["成交额"] < len(row) else 0.0
        except (ValueError, TypeError, IndexError) as e:
            print(f"  跳过一行（解析失败）: {row[:3]}... {e}")
            continue

        # 东方财富格式：date,o,c,h,l,v,a
        line = f"{date},{o:.2f},{c:.2f},{h:.2f},{l:.2f},{v:.0f},{a:.0f}"
        klines.append(line)

    # 按日期升序（TDX 默认倒序，最新的在前）
    klines.reverse()

    return {
        "data": {
            "klines": klines,
            "_source": source_name,
            "_converted_at": datetime.now().isoformat(),
            "_count": len(klines),
        }
    }


def main():
    if len(sys.argv) < 2:
        print("用法: python3 tdx_to_em_format.py <tdx_kline.json> [output.json]")
        print("  - tdx_kline.json: TDX MCP tdx_kline 返回的 JSON")
        print("  - output.json:   转换后的东方财富格式（默认 kline_latest.json）")
        sys.exit(1)

    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "kline_latest.json"

    if not os.path.exists(src):
        print(f"❌ 输入文件不存在: {src}")
        sys.exit(1)

    with open(src, "r", encoding="utf-8") as f:
        tdx = json.load(f)

    try:
        em = tdx_to_em_format(tdx, source_name="TDX MCP")
    except (ValueError, KeyError) as e:
        print(f"❌ 转换失败: {e}")
        sys.exit(1)

    with open(out, "w", encoding="utf-8") as f:
        json.dump(em, f, ensure_ascii=False, indent=2)

    print(f"✅ 转换成功: {out}")
    print(f"   共 {em['data']['_count']} 根 K 线")
    print(f"   起始: {em['data']['klines'][0].split(',')[0]}")
    print(f"   结束: {em['data']['klines'][-1].split(',')[0]}")
    print(f"   来源: {em['data']['_source']}")
    print(f"   转换时间: {em['data']['_converted_at']}")


if __name__ == "__main__":
    main()