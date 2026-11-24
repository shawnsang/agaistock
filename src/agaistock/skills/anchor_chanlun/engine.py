"""缠论三级别结构编排。

数据流：
  tdx_kline(week/day/m30) → tdx_rows_to_em → 上游 chan_analyze.py → chan_multi_level.py

上游脚本**只读不改**，全部通过子进程调用。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from ...providers import tdx, tdx_rows_to_em

LEVELS = {"week": "5", "day": "4", "m30": "2"}
LEVEL_ORDER = ("week", "day", "m30")
WANT_NUM = 500


def vendor_root() -> Path:
    """上游 chanlun-core 的根目录。"""
    return Path(__file__).resolve().parent / "vendor" / "chanlun-core"


def _run_script(script: str, work_dir: Path, extra: list[str]) -> None:
    result = subprocess.run(
        [sys.executable, str(vendor_root() / "scripts" / script), str(work_dir), *extra],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(work_dir),
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"{script} 执行失败(exit={result.returncode}): {(result.stderr or '')[-800:]}"
        )


def load_analysis(work_dir: Path, level: str) -> dict[str, Any]:
    """读 `chan_analysis_<level>.json`。"""
    path = work_dir / f"chan_analysis_{level}.json"
    if not path.is_file():
        raise FileNotFoundError(f"缺少 {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def build_structure(
    symbol: str,
    name: str,
    setcode: str,
    work_dir: Path,
    kline_fetcher: Callable[..., dict] = tdx.fetch_kline,
) -> dict[str, Any]:
    """拉三级别 K 线 → 跑上游识别 → 读回多级别统合结果。"""
    work_dir.mkdir(parents=True, exist_ok=True)

    for level in LEVEL_ORDER:
        payload = kline_fetcher(symbol, setcode, LEVELS[level], WANT_NUM)
        em = tdx_rows_to_em.rows_to_em_format(payload)
        kline_file = work_dir / f"kline_{level}.json"
        kline_file.write_text(
            json.dumps(em, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _run_script("chan_analyze.py", work_dir, ["--level", level])

    _run_script(
        "chan_multi_level.py",
        work_dir,
        ["--symbol", str(symbol), "--name", str(name)],
    )

    multi = work_dir / "chan_multi_level.json"
    if not multi.is_file():
        raise RuntimeError("上游未产出 chan_multi_level.json")
    return json.loads(multi.read_text(encoding="utf-8"))
