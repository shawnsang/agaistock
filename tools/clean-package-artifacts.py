#!/usr/bin/env python
"""publish 前清掉插件包里的**运行产物**。

为什么需要它：`data/`（含 `agaistock.db`、`chanlun/`）是 gitignored 的运行产物，
而**宿主会把 gitignored 产物一并拷进安装目录**（实测：仓库插件包
`miniapps/agaistock/src/agaistock/**` 的 24 个 `.pyc` 与宿主持久安装目录
`~/.minimax/plugins/agaistock/src/agaistock/**` 的 24 个 `.pyc` **mtime 24/24 完全相同**；
至于「有多少个早于运行时解包时刻」**随解包批次变化**（实测 19/24 ~ 24/24），
**不要**把某个固定数字当证据 —— 决定性的是「mtime 逐个完全相同」这一条）。

于是只要仓库里留下一个 `miniapps/agaistock/data/agaistock.db`，publish 就会把它带进安装产物：
- 宿主侧读到的是**空库**（0 observations），而真实数据在 `context.dataDir` 的库里
  ⇒ 用户会以为「一条观察都没有」；
- 安装产物被污染（重装覆盖、只读安装都受影响）。

实测触发路径（**不是** Node 侧的运行时接线）：在插件包目录里直跑内核且**不带**
`AGAISTOCK_DB` / `AGAISTOCK_DATA_DIR` 时，`config.data_dir()` 回落到
`repo_root()/"data"`，而插件包副本里的 `repo_root()` 就是**包根** ⇒ 写出包内 `data/`。

用法：
    python tools/clean-package-artifacts.py          # 检查 + 清理（打印发现了什么）
    python tools/clean-package-artifacts.py --check  # 只检查，不改；发现残留时退出码 1
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / 'miniapps' / 'agaistock'

# 插件包里**不该**存在的运行产物
ARTIFACT_DIRS = ('data',)
ARTIFACT_GLOBS = ('*.db', '*.db-journal', '*.db-wal', '*.db-shm')


def find_artifacts() -> list[Path]:
    found: list[Path] = []
    if not PKG.is_dir():
        return found
    for name in ARTIFACT_DIRS:
        d = PKG / name
        if d.exists():
            found.append(d)
    for pattern in ARTIFACT_GLOBS:
        found.extend(p for p in PKG.rglob(pattern) if p.is_file())
    # __pycache__ 也是 gitignored 产物 —— 宿主会拷，但那是字节码，无害；
    # 这里**只**报不删（删了会让每次运行都重编，反而更慢）。
    return sorted(set(found))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='只检查，不修改')
    args = ap.parse_args()

    artifacts = find_artifacts()
    if not artifacts:
        print('插件包里没有运行产物 —— 可以 publish。')
        return 0

    print('插件包里发现运行产物（会被 publish 带进安装目录）：')
    for p in artifacts:
        kind = '目录' if p.is_dir() else '文件'
        print(f'  [{kind}] {p.relative_to(ROOT)}')

    if args.check:
        print('\n--check 模式：不修改。跑 `python tools/clean-package-artifacts.py` 清理。')
        return 1

    # 先删文件、再删目录 —— 反过来会「删完目录再删里面的文件」而报 FileNotFoundError。
    for p in artifacts:
        if p.is_dir():
            continue
        if p.exists():
            p.unlink()
            print(f'  已删除文件 {p.relative_to(ROOT)}')

    for p in artifacts:
        if not p.is_dir():
            continue
        if p.exists():
            shutil.rmtree(p)
            print(f'  已删除目录 {p.relative_to(ROOT)}')

    # 删完再验一遍
    left = find_artifacts()
    if left:
        print('\n仍有残留：', file=sys.stderr)
        for p in left:
            print(f'  {p}', file=sys.stderr)
        return 1
    print('\n清理完成 —— 可以 publish。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
