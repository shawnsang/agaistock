"""把业务内核同步进 Mini App 包，让安装包自带内核。

宿主安装的是**整个 Mini App 包目录**（`miniapps/agaistock/`），安装后的目录
就是运行时的代码根。安装副本里必须带着 `src/agaistock` 与 `config/`，
否则 `python -m agaistock.cli` 只在开发机（editable 安装）下能跑，
交付到用户机器上必然 ModuleNotFoundError。

用法：
    python tools/sync-kernel.py          # 同步（覆盖副本）
    python tools/sync-kernel.py --check  # 只检查漂移，有漂移则退出码 1

`tests/test_kernel_vendor.py` 会调用 --check，把漂移变成测试失败。
"""
from __future__ import annotations

import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "miniapps" / "agaistock"

# (源目录, 副本目录) —— 副本必须与源逐字节相同。
PAIRS = (
    (ROOT / "src" / "agaistock", PLUGIN_ROOT / "src" / "agaistock"),
    (ROOT / "config", PLUGIN_ROOT / "config"),
)

IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")


def _rel_files(base: Path) -> set[str]:
    return {
        str(p.relative_to(base)).replace("\\", "/")
        for p in base.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    }


def diff() -> list[str]:
    """返回漂移描述列表；空列表表示没有漂移。"""
    problems: list[str] = []
    for src, dst in PAIRS:
        if not src.is_dir():
            problems.append(f"源目录不存在：{src}")
            continue
        if not dst.is_dir():
            problems.append(f"副本目录不存在：{dst}（跑 python tools/sync-kernel.py 修复）")
            continue
        src_files = _rel_files(src)
        dst_files = _rel_files(dst)
        for missing in sorted(src_files - dst_files):
            problems.append(f"副本缺少文件：{dst / missing}")
        for extra in sorted(dst_files - src_files):
            problems.append(f"副本多出文件：{dst / extra}")
        for name in sorted(src_files & dst_files):
            if not filecmp.cmp(src / name, dst / name, shallow=False):
                problems.append(f"副本内容不一致：{dst / name}")
    return problems


def sync() -> None:
    for src, dst in PAIRS:
        shutil.copytree(src, dst, dirs_exist_ok=True, ignore=IGNORE)


def main(argv: list[str]) -> int:
    if "--check" in argv:
        problems = diff()
        if problems:
            print("内核副本与源不一致：")
            for item in problems:
                print(f"  - {item}")
            print("修复：python tools/sync-kernel.py")
            return 1
        print("内核副本与源一致。")
        return 0
    sync()
    print("已同步内核到 Mini App 包。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
