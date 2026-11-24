# 点评师层与缠论点评师 · 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 agaistock 中建立可插拔的「点评师」层，并上线第一位点评师 `anchor-chanlun`（缠论），让用户口述的观察不止被记录，还被对照客观结构给出点评；同时实现观察卡的软删除。

**Architecture:** 业务内核为 **Python 3.11 纯标准库**（零第三方依赖），点评师是可注册的组件，统一输出 `ReviewVerdict`；结论全部落 SQLite `reviews` 表；评分按固定五维聚合所有点评师的贡献，观察期档位上限取各点评师 `horizon_hint` 中最保守者。取数通过 `mcode-tools connector call` 调用宿主托管的通达信连接器（免 token、免裸注册）。Mini App（Node）通过 spawn 内核 CLI 完成点评链路。

**Tech Stack:** Python 3.11.9（仅标准库：`sqlite3` / `urllib.request` / `unittest` / `dataclasses`）· Node.js 24.x（Mini App，`node --test`）· 上游缠论脚本（纯标准库，整目录 vendor 拷贝，不改一行）

**Design spec:** `docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md`

---

## Global Constraints

这些约束适用于**每一个** Task，无需重复声明：

1. **Python 命令一律用 `python`**（本机 `python` = 3.11.9；`python3` 不存在，调用会失败并弹出 Microsoft Store 别名提示）。
2. **业务内核零第三方依赖**，只用标准库。测试框架用 `unittest`（不是 pytest）。不引入 PyYAML —— 配置文件一律用 **JSON**。
3. **缠论上游脚本只读不改**：`vendor/chanlun-core/` 整目录拷贝自 `C:\Users\shawn\.workbuddy\plugins\marketplaces\my-experts\plugins\chanlun-analyst\skills\chanlun-core`，**不改其中任何一行**。所有适配写在 `src/agaistock/skills/anchor_chanlun/` 内。
4. **目录名用下划线**（Python 模块名不能带连字符）。`reviewer_id` 用连字符（稳定标识符）。
5. **Windows 下调用 `mcode-tools` 必须用 `--args-file`**，不可用 `--args '{...}'`（PowerShell 会剥掉双引号，报 `Connector arguments must be valid JSON`）。且 `mcode-tools` 是 `.cmd` 批处理，Python 侧需 `shell=True` 或直接走 `cmd.exe /c`。
6. **`tdx_kline` 返回结构（已实测）**：`Rows` 是**升序**对象数组，键为英文字段 `Data`(YYYYMMDD) / `Open` / `High` / `Low` / `Close` / `Volume`(手) / `Amount`(元)；`ListHead` 是 `{ItemHead:[...]}` 对象；`AttachInfo` 是元信息对象。上游 `tdx_to_em_format.py` 假设的是旧结构（`ListHead` 数组 + `AttachInfo` 数组的数组），**不可直接使用**。
7. **东财格式字段序为 `date,o,c,h,l,v,a`**（注意 `c` 在 `h`/`l` 之前，与 TDX 的 `o,h,l,c` 不同）。**升序不 reverse。**
8. **上游 `chan_multi_level.py` 要求三个级别的 `chan_analysis_<level>.json` 都存在**，缺任何一个就 exit 1。因此 `build_structure` 必须对 week/day/m30 **全部**跑一遍 `chan_analyze.py` 再跑统合。上游输出的关键字段（已实测）：顶层 `levels` / `resonance` / `interval_nesting` / `interval_nesting_week_day` / `window_alignment` / `action` / `key_levels` / `caveats` / `narrative` / `framework`；`levels.<lv>` 内含 `bias` / `bias_zh` / `trend_direction` / `signal` / `signal_detail` / `nearby_pivots` / `recent_divergence` / `divergence_hint` / `window_verdict` / `may_be_partial` / `last_close` / `pivots_total`。
   - `resonance` 的档位字段是 **`grade`**（如 `"C"`），`level` 是中文定性（如 `"级别交错"`）。
   - `may_be_partial` 是**盘中未收盘的权威标志**，纪律二十五据此触发，不要无条件报警。
   - `levels.<lv>.last_close` 已含现价，**不必再单独调一次行情接口**。
9. **点评结论必须全部落库**（`reviews` 表），每次运行追加一行。
10. **LLM 措辞层不得修改** `code` / `severity` / `dimension` / `delta` / `evidence_ref`；归一化层校验到篡改即**丢弃 LLM 输出、保留规则层原文**。
11. **五维集合固定**在 `config/scoring.json`；无点评师贡献的维度**从加权平均的分子分母一并剔除**并标 `completeness="no_reviewer"`，**不得**当 0 分或满分。
12. **`proposed_invalidation` 只建议、不自动写入** observation，必须用户显式采纳。
13. **软删除**：置 `observations.deleted_at`，**不物理删除**；软删观察不参与评分 / 观察期 / 校准统计，其 `reviews` 保留。
14. **每个 Task 结束必须 commit**。仓库尚未初始化，Task 1 负责 `git init`。
15. 内核包路径统一为 `src/agaistock/`，通过 `pyproject.toml` 的 `src` 布局安装；测试放 `tests/`。
16. **复权口径（D6；2026-11-24 用户裁决）**：K 线一律取 **后复权**。
    **不能依赖连接器的 `tqFlag:"2"`** —— 实测该参数**只在日线/周线生效，30 分钟级别不生效**
    （600519 的 m30 `tqFlag:"2"` 给 `1563.54`，同一天日线给 `10014.70`；002378 m30 给 `15.73`，日线给 `42.66`）。
    后果：三个级别会落在**两个价格空间**，上游 `key_levels` 把它们拍平成一张表，
    证伪位就成了「后复权价位 vs 前复权价位」的混账。
    → **后复权由 provider 层自己统一重建**：取 `tqFlag:"0"`（不复权）原始序列 + 复权因子表 →
    逐 bar 换算 `后复权价(d) = 不复权价(d) × 精确复权因子 + 精确复权常数`，
    因子行取 **ex_date ≤ d 的最新一行**（因子表日期带连字符、K 线日期不带，比较前统一成 `YYYYMMDD`）；
    早于首个 ex_date 的用 factor=1 / constant=0。
    该规则已实测**精确复现连接器自身的后复权**：600519 700 根日线中位相对误差 0.00003%（纯舍入）、
    300 根周线 300/300 命中；002378 误差 ≤0.002%（连接器自身只给 2 位小数）。
    `Volume` / `Amount` **保持原值**（与连接器后复权行为一致）。
17. **复权口径在适配层收口**（主规格 §6.7）：provider 返回统一 schema；`tqFlag`、因子换算都由 `providers/tdx.py` 处理，**不向调用方暴露成可切换参数** —— 避免下游任务各自选口径。
18. **后复权 ↔ 现价 的换算公式（已实测）**：`后复权价 = 现价 × 精确复权因子 + 精确复权常数`，反解 `现价 = (后复权价 − 精确复权常数) / 精确复权因子`。
    因子与常数取 `adjustment_factor` 表中**该价格所属日期**的那一行（对「当前价位」用最新一行）。
    实测：600519 `1460.00 × 5.627766 + 1798.159313 = 10014.70`（= `tdx_kline` 的 `tqFlag:"2"` 实测值）；002378 `15.54 × 2.6 + 2.2552 = 42.66` ✓。
    **推论**：后复权序列的价位与实时行情（现价）**不在同一空间**，凡是拿后复权位与现价比对的地方（如 Task 10 的 `fetch_last_close` 回退路径、Task 15 的展示）**必须**先换算，否则会把 10014 当成 1460 比。
19. **连接器返回形态不稳定**：`tdx_api_data` 偶尔返回 `response.data`（未套用 preset 转换）而不是 `response.transformed.tables`。
    因此 `fetch_adjustment_factors` 在「请求成功但找不到因子表」时**必须重试一次，仍失败就抛错**，
    **不得静默返回 `[]`** —— 静默空表会被当成「该标的没有除权记录」，导致后复权重建悄悄退化成不复权。

---

## File Structure

| 文件 | 职责 |
|---|---|
| `pyproject.toml` | 包元数据，`src` 布局，无第三方依赖 |
| `.gitignore` | 忽略 `__pycache__/`、`*.pyc`、`.tmp/`、运行时数据目录 |
| `config/scoring.json` | 五维定义与权重（**固定集合**） |
| `config/reviewers.json` | 点评师注册表（id / enabled / module / weight） |
| `src/agaistock/config.py` | 读取上述两个 JSON，提供 `load_scoring()` / `load_reviewers()` |
| `src/agaistock/storage/db.py` | SQLite 连接、建表、迁移；observations / reviews / adjustment_factors 读写 |
| `src/agaistock/reviewers/contract.py` | `Finding` / `ProposedInvalidation` / `HorizonHint` / `ReviewVerdict` / `ReviewContext` + 校验 |
| `src/agaistock/reviewers/registry.py` | 按 `config/reviewers.json` 发现并实例化点评师 |
| `src/agaistock/reviewers/engine.py` | 调度点评师、失败隔离、落库 |
| `src/agaistock/providers/mcode_cli.py` | 调用 `mcode-tools connector call`，返回 text |
| `src/agaistock/providers/tdx.py` | 通达信取数：`fetch_kline` / `fetch_quotes` |
| `src/agaistock/providers/tdx_rows_to_em.py` | `Rows` → 东财格式 |
| `src/agaistock/skills/anchor_chanlun/engine.py` | 三级别 K 线编排 + 调用上游脚本 + 读结构 JSON |
| `src/agaistock/skills/anchor_chanlun/rules.py` | 纪律 → findings / caveats（纯函数） |
| `src/agaistock/skills/anchor_chanlun/signals.py` | `proposed_invalidation` / `horizon_hint` 生成（纯函数） |
| `src/agaistock/skills/anchor_chanlun/wording.py` | LLM 措辞层 + 受保护字段校验 |
| `src/agaistock/skills/anchor_chanlun/reviewer.py` | `AnchorChanlunReviewer` 组装上述各层 |
| `src/agaistock/llm/client.py` | OpenAI 兼容 HTTP 客户端（标准库 `urllib`） |
| `src/agaistock/scoring.py` | 维度聚合、`score_breakdown` |
| `src/agaistock/horizon.py` | 观察期规划、档位上限、checks |
| `src/agaistock/cli.py` | `python -m agaistock.cli` 子命令 |
| `miniapps/agaistock/miniapp/node/server.mjs` | Mini App 后端：新增点评 / 评分 / 删除 API |
| `miniapps/agaistock/miniapp/client/index.html` | Mini App 前端：点评展示 / 评分展示 / 删除按钮 |
| `tests/test_*.py` | 各层单测 |

---

### Task 1: 仓库初始化与 Python 工程骨架

**Files:**
- Create: `.gitignore`, `pyproject.toml`, `src/agaistock/__init__.py`, `src/agaistock/config.py`, `config/scoring.json`, `config/reviewers.json`
- Create: `tests/__init__.py`, `tests/test_config.py`

**Interfaces:**
- Produces:
  - `agaistock.config.load_scoring() -> dict`，返回 `{"dimensions": [{"name": str, "weight": float}, ...]}`，按权重降序无关，顺序固定为五维声明顺序。
  - `agaistock.config.load_reviewers() -> list[dict]`，每项 `{"id": str, "enabled": bool, "module": str, "weight": float}`。
  - `agaistock.config.repo_root() -> Path`，返回仓库根（`src/agaistock/config.py` 的上两级）。

- [ ] **Step 1: 初始化仓库并写 .gitignore**

```bash
cd /d D:\workroom\agaistock
git init
```

`.gitignore` 内容：

```gitignore
__pycache__/
*.pyc
.pytest_cache/
.tmp/
data/
*.db
```

- [ ] **Step 2: 写 pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "agaistock"
version = "0.1.0"
description = "股票复盘教练 · 业务内核"
requires-python = ">=3.11"
dependencies = []

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
"agaistock" = ["skills/anchor_chanlun/vendor/**/*"]
```

- [ ] **Step 3: 写 config/scoring.json**

```json
{
  "dimensions": [
    { "name": "事实锚定", "weight": 0.25 },
    { "name": "证伪条件", "weight": 0.25 },
    { "name": "逻辑链条", "weight": 0.20 },
    { "name": "位置与时机", "weight": 0.15 },
    { "name": "一致性", "weight": 0.15 }
  ]
}
```

- [ ] **Step 4: 写 config/reviewers.json**

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

- [ ] **Step 5: 写 src/agaistock/config.py**

```python
"""配置读取：评分维度与点评师注册表。

只读仓库内的 JSON 配置，不读宿主的任何私有配置文件（主规格 D3）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def repo_root() -> Path:
    """仓库根目录：src/agaistock/config.py -> src/agaistock -> src -> 根。"""
    return Path(__file__).resolve().parents[2]


def _load_json(relative_path: str) -> Any:
    path = repo_root() / relative_path
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_scoring() -> dict:
    """返回 {"dimensions": [{"name": str, "weight": float}, ...]}"""
    data = _load_json("config/scoring.json")
    dimensions = data.get("dimensions")
    if not isinstance(dimensions, list) or not dimensions:
        raise ValueError("config/scoring.json 缺少 dimensions")
    for item in dimensions:
        if "name" not in item or "weight" not in item:
            raise ValueError(f"维度定义缺字段: {item}")
    return {"dimensions": dimensions}


def load_reviewers() -> list[dict]:
    """返回点评师注册列表，按配置顺序。"""
    data = _load_json("config/reviewers.json")
    reviewers = data.get("reviewers")
    if not isinstance(reviewers, list):
        raise ValueError("config/reviewers.json 缺少 reviewers")
    for item in reviewers:
        for key in ("id", "enabled", "module", "weight"):
            if key not in item:
                raise ValueError(f"点评师注册缺字段 {key}: {item}")
    return reviewers
```

- [ ] **Step 6: 写失败的测试**

`tests/test_config.py`：

```python
import unittest

from agaistock import config


class ConfigTests(unittest.TestCase):
    def test_load_scoring_returns_five_fixed_dimensions(self):
        scoring = config.load_scoring()
        names = [d["name"] for d in scoring["dimensions"]]
        self.assertEqual(
            names,
            ["事实锚定", "证伪条件", "逻辑链条", "位置与时机", "一致性"],
        )
        self.assertAlmostEqual(sum(d["weight"] for d in scoring["dimensions"]), 1.0)

    def test_load_reviewers_returns_registry(self):
        reviewers = config.load_reviewers()
        self.assertTrue(reviewers)
        for item in reviewers:
            self.assertIn("id", item)
            self.assertIn("module", item)
            self.assertIn("weight", item)

    def test_repo_root_contains_config_dir(self):
        self.assertTrue((config.repo_root() / "config" / "scoring.json").is_file())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 7: 运行测试确认失败**

```bash
python -m pip install -e .
python -m unittest tests.test_config -v
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'agaistock'`

- [ ] **Step 8: 创建包初始化文件并让测试通过**

`src/agaistock/__init__.py`（空文件）与 `tests/__init__.py`（空文件）：

```bash
python -m pip install -e .
python -m unittest tests.test_config -v
```

Expected: 3 tests PASS

- [ ] **Step 9: Commit**

```bash
git add .gitignore pyproject.toml config src/agaistock/__init__.py src/agaistock/config.py tests
git commit -m "chore: init python package skeleton and config loaders"
```

---

### Task 2: 存储层 —— SQLite schema 与软删除

**Files:**
- Create: `src/agaistock/storage/__init__.py`, `src/agaistock/storage/db.py`
- Create: `tests/test_storage.py`

**Interfaces:**
- Produces:
  - `agaistock.storage.db.connect(db_path: str | Path) -> sqlite3.Connection`，行工厂为 `sqlite3.Row`，开启 `foreign_keys`。
  - `agaistock.storage.db.migrate(conn) -> None`，建表（幂等）。
  - `agaistock.storage.db.insert_observation(conn, observation: dict) -> str`，返回 id。
  - `agaistock.storage.db.list_observations(conn, include_deleted: bool = False) -> list[dict]`，默认过滤 `deleted_at IS NULL`。
  - `agaistock.storage.db.soft_delete_observation(conn, observation_id: str) -> bool`，置 `deleted_at`；找不到返回 False。
  - `agaistock.storage.db.insert_review(conn, observation_id: str, verdict: dict) -> str`，返回 id。
  - `agaistock.storage.db.latest_reviews(conn, observation_id: str) -> list[dict]`，每位 reviewer 只返回 `ran_at` 最新的一条，按 `ran_at` 升序。
  - `agaistock.storage.db.insert_adjustment_factors(conn, symbol: str, factors: list[dict]) -> int`，写入复权因子，返回写入条数；同一 `(symbol, ex_date)` 重复写入**覆盖**（upsert），不报错。`factors` 每项形如 `{"ex_date": "2026-06-26", "factor": 2.6, "constant": 2.2552}`。
  - `agaistock.storage.db.list_adjustment_factors(conn, symbol: str) -> list[dict]`，按 `ex_date` **降序**返回该标的的复权因子，字段为 `symbol` / `ex_date` / `factor` / `constant` / `fetched_at`。

- [ ] **Step 1: 写失败的测试**

`tests/test_storage.py`：

```python
import sqlite3
import unittest

from agaistock.storage import db


def make_conn():
    conn = db.connect(":memory:")
    db.migrate(conn)
    return conn


OBSERVATION = {
    "symbol": "002378",
    "name": "章源钨业",
    "direction": "bullish",
    "thesis": "钨价上涨，还可拿半年",
    "confidence": 0.72,
    "timeframe": "半年",
    "trigger": "",
    "position_json": "{}",
    "raw_text": "章源钨业我看了三年了",
}


def verdict(reviewer_id="anchor-chanlun", ran_at="2026-11-24T07:30:00Z"):
    return {
        "reviewer_id": reviewer_id,
        "reviewer_version": "0.1.0",
        "ran_at": ran_at,
        "status": "ok",
        "duration_ms": 100,
        "data_refs": [],
        "findings": [],
        "proposed_invalidation": [],
        "horizon_hint": None,
        "caveats": [],
    }


class StorageTests(unittest.TestCase):
    def test_migrate_is_idempotent(self):
        conn = make_conn()
        db.migrate(conn)
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        self.assertIn("observations", tables)
        self.assertIn("reviews", tables)
        self.assertIn("adjustment_factors", tables)

    def test_insert_and_list_observation(self):
        conn = make_conn()
        obs_id = db.insert_observation(conn, OBSERVATION)
        rows = db.list_observations(conn)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], obs_id)
        self.assertIsNone(rows[0]["deleted_at"])

    def test_soft_delete_hides_observation_by_default(self):
        conn = make_conn()
        obs_id = db.insert_observation(conn, OBSERVATION)
        self.assertTrue(db.soft_delete_observation(conn, obs_id))
        self.assertEqual(db.list_observations(conn), [])
        self.assertEqual(len(db.list_observations(conn, include_deleted=True)), 1)

    def test_soft_delete_unknown_id_returns_false(self):
        conn = make_conn()
        self.assertFalse(db.soft_delete_observation(conn, "nope"))

    def test_insert_review_appends_every_run(self):
        conn = make_conn()
        obs_id = db.insert_observation(conn, OBSERVATION)
        db.insert_review(conn, obs_id, verdict(ran_at="2026-11-24T07:30:00Z"))
        db.insert_review(conn, obs_id, verdict(ran_at="2026-11-24T09:00:00Z"))
        rows = conn.execute("SELECT * FROM reviews").fetchall()
        self.assertEqual(len(rows), 2)

    def test_latest_reviews_returns_only_newest_per_reviewer(self):
        conn = make_conn()
        obs_id = db.insert_observation(conn, OBSERVATION)
        db.insert_review(conn, obs_id, verdict(reviewer_id="a", ran_at="2026-11-24T07:00:00Z"))
        db.insert_review(conn, obs_id, verdict(reviewer_id="a", ran_at="2026-11-24T09:00:00Z"))
        db.insert_review(conn, obs_id, verdict(reviewer_id="b", ran_at="2026-11-24T08:00:00Z"))
        latest = db.latest_reviews(conn, obs_id)
        self.assertEqual([r["reviewer_id"] for r in latest], ["b", "a"])
        a_rows = [r for r in latest if r["reviewer_id"] == "a"]
        self.assertEqual(a_rows[0]["ran_at"], "2026-11-24T09:00:00Z")

    def test_latest_reviews_returns_one_row_when_ran_at_ties(self):
        """同一 reviewer 两条 ran_at 相同的 review，只能返回一条。"""
        conn = make_conn()
        obs_id = db.insert_observation(conn, OBSERVATION)
        db.insert_review(conn, obs_id, verdict(reviewer_id="a", ran_at="2026-11-24T07:00:00Z"))
        db.insert_review(conn, obs_id, verdict(reviewer_id="a", ran_at="2026-11-24T07:00:00Z"))
        latest = db.latest_reviews(conn, obs_id)
        self.assertEqual(len(latest), 1)
        self.assertEqual(latest[0]["reviewer_id"], "a")
        self.assertEqual(latest[0]["ran_at"], "2026-11-24T07:00:00Z")

    def test_insert_observation_keeps_position_json_verbatim(self):
        """position_json 已是序列化字符串，原样落库，不得被静默丢弃。"""
        conn = make_conn()
        observation = dict(OBSERVATION, position_json='{"shares": 1000}')
        obs_id = db.insert_observation(conn, observation)
        rows = db.list_observations(conn)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], obs_id)
        self.assertEqual(rows[0]["position_json"], '{"shares": 1000}')

    def test_insert_observation_serializes_position_dict(self):
        """position 传 dict 时，序列化后落库。"""
        conn = make_conn()
        observation = dict(OBSERVATION)
        observation.pop("position_json")
        observation["position"] = {"shares": 1000}
        db.insert_observation(conn, observation)
        rows = db.list_observations(conn)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["position_json"], '{"shares": 1000}')

    def test_soft_deleted_observation_keeps_its_reviews(self):
        """软删观察不隐藏其 reviews —— 全局约束：reviews 保留。"""
        conn = make_conn()
        obs_id = db.insert_observation(conn, OBSERVATION)
        db.insert_review(conn, obs_id, verdict())
        self.assertTrue(db.soft_delete_observation(conn, obs_id))
        self.assertEqual(db.list_observations(conn), [])
        self.assertEqual(len(db.list_observations(conn, include_deleted=True)), 1)
        latest = db.latest_reviews(conn, obs_id)
        self.assertEqual(len(latest), 1)
        self.assertEqual(latest[0]["reviewer_id"], "anchor-chanlun")

    def test_insert_and_list_adjustment_factors(self):
        conn = make_conn()
        written = db.insert_adjustment_factors(
            conn,
            "002378",
            [
                {"ex_date": "2025-06-06", "factor": 2.6, "constant": 1.9432},
                {"ex_date": "2026-06-26", "factor": 2.6, "constant": 2.2552},
            ],
        )
        self.assertEqual(written, 2)
        rows = db.list_adjustment_factors(conn, "002378")
        # 按 ex_date 降序：最近的除权事件排在最前
        self.assertEqual([r["ex_date"] for r in rows], ["2026-06-26", "2025-06-06"])
        self.assertEqual(rows[0]["factor"], 2.6)
        self.assertEqual(rows[0]["constant"], 2.2552)

    def test_insert_adjustment_factors_upserts_same_ex_date(self):
        conn = make_conn()
        db.insert_adjustment_factors(
            conn, "002378", [{"ex_date": "2026-06-26", "factor": 2.6, "constant": 2.2552}]
        )
        db.insert_adjustment_factors(
            conn, "002378", [{"ex_date": "2026-06-26", "factor": 2.6, "constant": 9.9999}]
        )
        rows = db.list_adjustment_factors(conn, "002378")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["constant"], 9.9999)

    def test_list_adjustment_factors_is_symbol_scoped(self):
        conn = make_conn()
        db.insert_adjustment_factors(
            conn, "002378", [{"ex_date": "2026-06-26", "factor": 2.6, "constant": 2.2552}]
        )
        db.insert_adjustment_factors(
            conn, "600519", [{"ex_date": "2026-06-26", "factor": 1.0, "constant": 1.0}]
        )
        rows = db.list_adjustment_factors(conn, "600519")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["symbol"], "600519")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m unittest tests.test_storage -v
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'agaistock.storage'`

- [ ] **Step 3: 实现 db.py**

`src/agaistock/storage/db.py`：

```python
"""SQLite 存储层。

设计约束（主规格 §7）：
  - 观察记录只追加不修改；修订走新版本行
  - 删除是软删除（deleted_at），不物理删除
  - reviews 每次运行都追加一行，读取时取每位 reviewer 最新一版
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id            TEXT PRIMARY KEY,
    symbol        TEXT NOT NULL,
    name          TEXT,
    created_at    TEXT NOT NULL,
    direction     TEXT,
    thesis        TEXT,
    confidence    REAL DEFAULT 0,
    timeframe     TEXT,
    trigger       TEXT,
    position_json TEXT,
    raw_text      TEXT,
    deleted_at    TEXT
);

CREATE TABLE IF NOT EXISTS reviews (
    id               TEXT PRIMARY KEY,
    observation_id   TEXT NOT NULL,
    reviewer_id      TEXT NOT NULL,
    reviewer_version TEXT NOT NULL,
    ran_at           TEXT NOT NULL,
    status           TEXT NOT NULL,
    duration_ms      INTEGER,
    verdict_json     TEXT NOT NULL,
    created_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reviews_obs
    ON reviews(observation_id, reviewer_id, ran_at);

CREATE TABLE IF NOT EXISTS adjustment_factors (
    symbol     TEXT NOT NULL,
    ex_date    TEXT NOT NULL,
    factor     REAL NOT NULL,
    constant   REAL NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (symbol, ex_date)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id(prefix: str) -> str:
    """生成带前缀的主键。

    秒级时间戳 + uuid 后缀：同一秒内重复落库（同一 reviewer 连续两次运行）
    也不会撞主键，符合"每次运行都追加一行"的约束。
    """
    return f"{prefix}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def _position_json(observation: dict[str, Any]) -> str:
    """把观察里的持仓信息落成 position_json 列的文本。

    同时接受两种键名：
      - ``position_json``：已序列化的字符串，原样存
      - ``position``：dict / list，序列化后存

    优先取 ``position_json``，缺失时回退到 ``position``，两者都缺时存 "{}"。
    """
    raw = observation.get("position_json")
    if raw is None:
        raw = observation.get("position", {})
    if isinstance(raw, str):
        return raw
    return json.dumps(raw, ensure_ascii=False)


def insert_observation(conn: sqlite3.Connection, observation: dict[str, Any]) -> str:
    obs_id = observation.get("id") or _new_id("obs")
    conn.execute(
        """INSERT INTO observations
           (id, symbol, name, created_at, direction, thesis, confidence,
            timeframe, trigger, position_json, raw_text, deleted_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            obs_id,
            observation.get("symbol", ""),
            observation.get("name", ""),
            observation.get("created_at") or _now(),
            observation.get("direction", ""),
            observation.get("thesis", ""),
            float(observation.get("confidence") or 0),
            observation.get("timeframe", ""),
            observation.get("trigger", ""),
            _position_json(observation),
            observation.get("raw_text", ""),
            None,
        ),
    )
    conn.commit()
    return obs_id


def list_observations(conn: sqlite3.Connection, include_deleted: bool = False) -> list[dict]:
    sql = "SELECT * FROM observations"
    if not include_deleted:
        sql += " WHERE deleted_at IS NULL"
    sql += " ORDER BY created_at DESC"
    return [dict(row) for row in conn.execute(sql)]


def soft_delete_observation(conn: sqlite3.Connection, observation_id: str) -> bool:
    cursor = conn.execute(
        "UPDATE observations SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
        (_now(), observation_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def insert_review(conn: sqlite3.Connection, observation_id: str, verdict: dict[str, Any]) -> str:
    review_id = _new_id("rev")
    conn.execute(
        """INSERT INTO reviews
           (id, observation_id, reviewer_id, reviewer_version, ran_at, status,
            duration_ms, verdict_json, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            review_id,
            observation_id,
            verdict.get("reviewer_id", ""),
            verdict.get("reviewer_version", ""),
            verdict.get("ran_at", ""),
            verdict.get("status", ""),
            int(verdict.get("duration_ms") or 0),
            json.dumps(verdict, ensure_ascii=False),
            _now(),
        ),
    )
    conn.commit()
    return review_id


def latest_reviews(conn: sqlite3.Connection, observation_id: str) -> list[dict]:
    """每位 reviewer 只返回 ran_at 最新的一条，按 ran_at 升序返回。

    ran_at 精度只到秒，同一 reviewer 同一秒内的两次运行会并列；
    依次用 created_at、rowid（插入顺序）兜底排序，保证每位 reviewer
    恰好一行，且并列时取后插入的那次运行。
    """
    rows = conn.execute(
        """SELECT * FROM (
               SELECT r.*,
                      ROW_NUMBER() OVER (
                          PARTITION BY r.reviewer_id
                          ORDER BY r.ran_at DESC, r.created_at DESC, r.rowid DESC
                      ) AS rn
               FROM reviews r
               WHERE r.observation_id = ?
           )
           WHERE rn = 1
           ORDER BY ran_at ASC, created_at ASC, id ASC""",
        (observation_id,),
    )
    result = []
    for row in rows:
        item = dict(row)
        item.pop("rn", None)
        item["verdict"] = json.loads(item.pop("verdict_json"))
        result.append(item)
    return result


def insert_adjustment_factors(
    conn: sqlite3.Connection, symbol: str, factors: list[dict[str, Any]]
) -> int:
    """写入复权因子；同一 (symbol, ex_date) 重复写入覆盖。"""
    fetched_at = _now()
    for item in factors:
        conn.execute(
            """INSERT INTO adjustment_factors
               (symbol, ex_date, factor, constant, fetched_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(symbol, ex_date) DO UPDATE SET
                   factor = excluded.factor,
                   constant = excluded.constant,
                   fetched_at = excluded.fetched_at""",
            (
                str(symbol),
                str(item["ex_date"]),
                float(item["factor"]),
                float(item["constant"]),
                fetched_at,
            ),
        )
    conn.commit()
    return len(factors)


def list_adjustment_factors(conn: sqlite3.Connection, symbol: str) -> list[dict[str, Any]]:
    """按 ex_date 降序返回该标的的复权因子。"""
    rows = conn.execute(
        """SELECT symbol, ex_date, factor, constant, fetched_at
           FROM adjustment_factors WHERE symbol = ?
           ORDER BY ex_date DESC""",
        (str(symbol),),
    )
    return [dict(row) for row in rows]
```

同时创建空文件 `src/agaistock/storage/__init__.py`。

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m unittest tests.test_storage -v
```

Expected: 13 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/agaistock/storage tests/test_storage.py
git commit -m "feat: sqlite storage layer with reviews table and soft delete"
```

---

### Task 3: 点评师契约 `ReviewVerdict`

**Files:**
- Create: `src/agaistock/reviewers/__init__.py`, `src/agaistock/reviewers/contract.py`
- Create: `tests/test_contract.py`

**Interfaces:**
- Produces:
  - `Finding(code: str, severity: str, dimension: str, delta: int, claim: str, why: str, evidence_ref: list[str], suggested_fix: str)`
  - `ProposedInvalidation(desc: str, source: str, comparator: str, tolerance: float | None, rationale: str)`
  - `HorizonHint(tier: str, rationale: str, checks: list[dict])`
  - `ReviewVerdict(reviewer_id, reviewer_version, ran_at, status, duration_ms, data_refs, findings, proposed_invalidation, horizon_hint, caveats)`，含 `.to_dict()` / `.from_dict(d)`
  - `ReviewContext(observation: dict, symbol: str, name: str, now: str, data_dir: Path, llm, prior_reviews: list[ReviewVerdict])`
  - `SEVERITIES = ("critical", "high", "medium", "low", "info")`
  - `STATUSES = ("ok", "partial", "skipped", "error")`
  - `validate_verdict(verdict: ReviewVerdict, dimensions: list[str]) -> list[str]`，返回错误信息列表（空 = 合法）
  - `PROTECTED_FIELDS = ("code", "severity", "dimension", "delta", "evidence_ref")`

- [ ] **Step 1: 写失败的测试**

`tests/test_contract.py`：

```python
import unittest

from agaistock.reviewers import contract


def make_finding(**overrides):
    base = dict(
        code="CHAN_DAY_TOP_DIVERGENCE",
        severity="critical",
        dimension="位置与时机",
        delta=-12,
        claim="日线顶背驰成立",
        why="与大级别动能背离",
        evidence_ref=["chan.levels.day.recent_divergence"],
        suggested_fix="降级为反弹参与",
    )
    base.update(overrides)
    return contract.Finding(**base)


class ContractTests(unittest.TestCase):
    def test_finding_to_dict_keeps_all_fields(self):
        data = make_finding().to_dict()
        self.assertEqual(data["code"], "CHAN_DAY_TOP_DIVERGENCE")
        self.assertEqual(data["dimension"], "位置与时机")
        self.assertEqual(data["delta"], -12)
        self.assertIn("evidence_ref", data)

    def test_verdict_round_trips_through_dict(self):
        verdict = contract.ReviewVerdict(
            reviewer_id="anchor-chanlun",
            reviewer_version="0.1.0",
            ran_at="2026-11-24T07:30:00Z",
            status="ok",
            duration_ms=1234,
            data_refs=[{"source": "tdx_kline"}],
            findings=[make_finding()],
            proposed_invalidation=[
                contract.ProposedInvalidation(
                    desc="跌破日线中枢下沿 22.39",
                    source="chan.levels.day.nearby_pivots[].ZD",
                    comparator="below",
                    tolerance=0.5,
                    rationale="中枢下沿是结构失效位",
                )
            ],
            horizon_hint=contract.HorizonHint(tier="short", rationale="顶背驰", checks=[]),
            caveats=["背驰 active 不代表仍成立"],
        )
        restored = contract.ReviewVerdict.from_dict(verdict.to_dict())
        self.assertEqual(restored.findings[0].code, "CHAN_DAY_TOP_DIVERGENCE")
        self.assertEqual(restored.proposed_invalidation[0].comparator, "below")
        self.assertEqual(restored.horizon_hint.tier, "short")
        self.assertEqual(restored.caveats, ["背驰 active 不代表仍成立"])

    def test_validate_rejects_unknown_severity(self):
        verdict = contract.ReviewVerdict(
            reviewer_id="x", reviewer_version="0.1.0", ran_at="t", status="ok",
            duration_ms=0, data_refs=[], findings=[make_finding(severity="致命")],
            proposed_invalidation=[], horizon_hint=None, caveats=[],
        )
        errors = contract.validate_verdict(verdict, ["位置与时机"])
        self.assertTrue(any("severity" in e for e in errors))

    def test_validate_rejects_unknown_dimension(self):
        verdict = contract.ReviewVerdict(
            reviewer_id="x", reviewer_version="0.1.0", ran_at="t", status="ok",
            duration_ms=0, data_refs=[], findings=[make_finding(dimension="第六感")],
            proposed_invalidation=[], horizon_hint=None, caveats=[],
        )
        errors = contract.validate_verdict(verdict, ["位置与时机"])
        self.assertTrue(any("dimension" in e for e in errors))

    def test_validate_rejects_missing_dimension(self):
        finding = make_finding()
        object.__setattr__(finding, "dimension", "")
        verdict = contract.ReviewVerdict(
            reviewer_id="x", reviewer_version="0.1.0", ran_at="t", status="ok",
            duration_ms=0, data_refs=[], findings=[finding],
            proposed_invalidation=[], horizon_hint=None, caveats=[],
        )
        errors = contract.validate_verdict(verdict, ["位置与时机"])
        self.assertTrue(any("dimension" in e for e in errors))

    def test_validate_rejects_missing_delta(self):
        finding = make_finding()
        object.__setattr__(finding, "delta", None)
        verdict = contract.ReviewVerdict(
            reviewer_id="x", reviewer_version="0.1.0", ran_at="t", status="ok",
            duration_ms=0, data_refs=[], findings=[finding],
            proposed_invalidation=[], horizon_hint=None, caveats=[],
        )
        errors = contract.validate_verdict(verdict, ["位置与时机"])
        self.assertTrue(any("delta" in e for e in errors))

    def test_validate_rejects_unknown_status(self):
        verdict = contract.ReviewVerdict(
            reviewer_id="x", reviewer_version="0.1.0", ran_at="t", status="也许",
            duration_ms=0, data_refs=[], findings=[], proposed_invalidation=[],
            horizon_hint=None, caveats=[],
        )
        errors = contract.validate_verdict(verdict, ["位置与时机"])
        self.assertTrue(any("status" in e for e in errors))

    def test_validate_accepts_a_well_formed_verdict(self):
        verdict = contract.ReviewVerdict(
            reviewer_id="x", reviewer_version="0.1.0", ran_at="t", status="ok",
            duration_ms=0, data_refs=[], findings=[make_finding()],
            proposed_invalidation=[], horizon_hint=None, caveats=["c"],
        )
        self.assertEqual(contract.validate_verdict(verdict, ["位置与时机"]), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m unittest tests.test_contract -v
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'agaistock.reviewers'`

- [ ] **Step 3: 实现 contract.py**

`src/agaistock/reviewers/contract.py`：

```python
"""点评师统一契约。

设计依据：docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md §2
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

SEVERITIES = ("critical", "high", "medium", "low", "info")
STATUSES = ("ok", "partial", "skipped", "error")
HORIZON_TIERS = ("short", "mid", "long", "event")
PROTECTED_FIELDS = ("code", "severity", "dimension", "delta", "evidence_ref")


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    dimension: str
    delta: int
    claim: str
    why: str
    evidence_ref: list[str] = field(default_factory=list)
    suggested_fix: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "dimension": self.dimension,
            "delta": self.delta,
            "claim": self.claim,
            "why": self.why,
            "evidence_ref": list(self.evidence_ref),
            "suggested_fix": self.suggested_fix,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Finding":
        return cls(
            code=data.get("code", ""),
            severity=data.get("severity", ""),
            dimension=data.get("dimension", ""),
            delta=data.get("delta"),
            claim=data.get("claim", ""),
            why=data.get("why", ""),
            evidence_ref=list(data.get("evidence_ref") or []),
            suggested_fix=data.get("suggested_fix", ""),
        )


@dataclass(frozen=True)
class ProposedInvalidation:
    desc: str
    source: str
    comparator: str
    tolerance: float | None = None
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "desc": self.desc,
            "source": self.source,
            "comparator": self.comparator,
            "tolerance": self.tolerance,
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProposedInvalidation":
        return cls(
            desc=data.get("desc", ""),
            source=data.get("source", ""),
            comparator=data.get("comparator", ""),
            tolerance=data.get("tolerance"),
            rationale=data.get("rationale", ""),
        )


@dataclass(frozen=True)
class HorizonHint:
    tier: str
    rationale: str
    checks: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"tier": self.tier, "rationale": self.rationale, "checks": list(self.checks)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HorizonHint":
        return cls(
            tier=data.get("tier", ""),
            rationale=data.get("rationale", ""),
            checks=list(data.get("checks") or []),
        )


@dataclass(frozen=True)
class ReviewVerdict:
    reviewer_id: str
    reviewer_version: str
    ran_at: str
    status: str
    duration_ms: int = 0
    data_refs: list[dict] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    proposed_invalidation: list[ProposedInvalidation] = field(default_factory=list)
    horizon_hint: HorizonHint | None = None
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reviewer_id": self.reviewer_id,
            "reviewer_version": self.reviewer_version,
            "ran_at": self.ran_at,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "data_refs": list(self.data_refs),
            "findings": [f.to_dict() for f in self.findings],
            "proposed_invalidation": [p.to_dict() for p in self.proposed_invalidation],
            "horizon_hint": self.horizon_hint.to_dict() if self.horizon_hint else None,
            "caveats": list(self.caveats),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReviewVerdict":
        hint = data.get("horizon_hint")
        return cls(
            reviewer_id=data.get("reviewer_id", ""),
            reviewer_version=data.get("reviewer_version", ""),
            ran_at=data.get("ran_at", ""),
            status=data.get("status", ""),
            duration_ms=int(data.get("duration_ms") or 0),
            data_refs=list(data.get("data_refs") or []),
            findings=[Finding.from_dict(f) for f in (data.get("findings") or [])],
            proposed_invalidation=[
                ProposedInvalidation.from_dict(p) for p in (data.get("proposed_invalidation") or [])
            ],
            horizon_hint=HorizonHint.from_dict(hint) if hint else None,
            caveats=list(data.get("caveats") or []),
        )


@dataclass
class ReviewContext:
    observation: dict
    symbol: str
    name: str
    now: str
    data_dir: Path
    llm: Any = None
    prior_reviews: list[ReviewVerdict] = field(default_factory=list)


class Reviewer(Protocol):
    id: str
    version: str

    def review(self, ctx: ReviewContext) -> ReviewVerdict: ...


def validate_verdict(verdict: ReviewVerdict, dimensions: list[str]) -> list[str]:
    """返回错误信息列表；空列表表示合法。"""
    errors: list[str] = []
    if verdict.status not in STATUSES:
        errors.append(f"status 非法: {verdict.status!r}，允许 {STATUSES}")
    if not verdict.reviewer_id:
        errors.append("reviewer_id 为空")
    for index, finding in enumerate(verdict.findings):
        if finding.severity not in SEVERITIES:
            errors.append(f"findings[{index}].severity 非法: {finding.severity!r}")
        if not finding.dimension:
            errors.append(f"findings[{index}].dimension 为空")
        elif finding.dimension not in dimensions:
            errors.append(
                f"findings[{index}].dimension 未定义: {finding.dimension!r}，允许 {dimensions}"
            )
        if finding.delta is None or not isinstance(finding.delta, int):
            errors.append(f"findings[{index}].delta 必须为整数")
    # 契约硬约束：有发现却没有限制声明 = 把机械结论当结论，是本产品最容易产生的误导。
    # findings 为空时（skipped 的点评师）不要求 caveats。
    if verdict.findings and not verdict.caveats:
        codes = [f.code for f in verdict.findings]
        errors.append(
            f"caveats 为空但存在 {len(codes)} 条发现，缺少限制声明: {codes}"
        )
    if verdict.horizon_hint is not None and verdict.horizon_hint.tier not in HORIZON_TIERS:
        errors.append(f"horizon_hint.tier 非法: {verdict.horizon_hint.tier!r}")
    return errors
```

同时创建空文件 `src/agaistock/reviewers/__init__.py`。

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m unittest tests.test_contract -v
```

Expected: 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/agaistock/reviewers tests/test_contract.py
git commit -m "feat: reviewer contract with ReviewVerdict and validation"
```

---

### Task 4: 点评师注册表与执行引擎

**Files:**
- Create: `src/agaistock/reviewers/registry.py`, `src/agaistock/reviewers/engine.py`
- Create: `tests/test_registry.py`, `tests/test_engine.py`

**Interfaces:**
- Consumes: `config.load_reviewers()`（Task 1）、`ReviewContext` / `ReviewVerdict` / `validate_verdict`（Task 3）、`storage.db.insert_review`（Task 2）
- Produces:
  - `agaistock.reviewers.registry.load_reviewers(specs: list[dict] | None = None) -> list[dict]`，每项补 `instance`。
    单个点评师装载失败（模块不存在、导入期抛错）**不拖垮整轮**：该项 `instance` 是降级实例，
    并在 `error` 里记下是谁、哪个模块、原始异常是什么；降级实例在 review 时抛错，
    由引擎转成 `status="error"` 的 verdict 落库。
  - `agaistock.reviewers.registry.instantiate(spec: dict) -> Reviewer`，按 `module` 路径动态导入并解析点评师类：
    优先精确同名 `Reviewer`；只有一个 `*Reviewer` 结尾的候选时用它；多个候选且无精确同名时抛错并列出候选名。
  - `agaistock.reviewers.engine.run_one(reviewer, ctx: ReviewContext) -> ReviewVerdict`，**异常或契约校验失败都转为 `status="error"` 的 verdict**（绝不向上抛）；校验不通过的结论不落成有效结论：findings 被丢弃，只在 caveats 里留下错误。
  - `agaistock.reviewers.engine.run_reviewers(reviewers: list, ctx: ReviewContext) -> list[ReviewVerdict]`，依次执行所有点评师，返回全部结果（含失败项）。
  - `agaistock.reviewers.engine.persist(conn, observation_id: str, verdicts: list[ReviewVerdict]) -> list[dict]`，把 verdict 落库，返回落库后的字典列表。

- [ ] **Step 1: 写失败的测试**

`tests/test_registry.py`：

```python
import unittest

from agaistock.reviewers import registry


class FakeReviewer:
    id = "fake"
    version = "0.0.1"

    def review(self, ctx):
        raise AssertionError("不应被调用")


class RegistryTests(unittest.TestCase):
    def test_disabled_reviewers_are_skipped(self):
        specs = [
            {"id": "a", "enabled": True, "module": "x", "weight": 1.0},
            {"id": "b", "enabled": False, "module": "y", "weight": 1.0},
        ]
        loaded = registry.load_reviewers(specs)
        self.assertEqual([r["id"] for r in loaded], ["a"])

    def test_instantiate_imports_module_and_class(self):
        spec = {
            "id": "fake",
            "enabled": True,
            "module": "tests.test_registry",
            "weight": 1.0,
        }
        instance = registry.instantiate(spec)
        self.assertIsInstance(instance, FakeReviewer)

    def test_instantiate_raises_for_missing_module(self):
        with self.assertRaises(ImportError):
            registry.instantiate({"id": "x", "module": "no.such.module", "weight": 1.0})


if __name__ == "__main__":
    unittest.main()
```

`tests/test_engine.py`：

```python
import unittest

from agaistock.reviewers import contract, engine


class BoomReviewer:
    id = "boom"
    version = "0.1.0"

    def review(self, ctx):
        raise RuntimeError("炸了")


class OkReviewer:
    id = "ok"
    version = "0.1.0"

    def review(self, ctx):
        return contract.ReviewVerdict(
            reviewer_id="ok", reviewer_version="0.1.0", ran_at="2026-11-24T07:00:00Z",
            status="ok", duration_ms=5, data_refs=[], findings=[], proposed_invalidation=[],
            horizon_hint=None, caveats=["c"],
        )


class EngineTests(unittest.TestCase):
    def test_run_one_wraps_exception_into_error_verdict(self):
        ctx = contract.ReviewContext(
            observation={}, symbol="002378", name="章源钨业", now="t",
            data_dir=".", llm=None,
        )
        verdict = engine.run_one(BoomReviewer(), ctx)
        self.assertEqual(verdict.status, "error")
        self.assertIn("炸了", verdict.caveats[0])

    def test_run_reviewers_isolates_failures_and_keeps_both(self):
        ctx = contract.ReviewContext(
            observation={}, symbol="002378", name="章源钨业", now="t",
            data_dir=".", llm=None,
        )
        results = engine.run_reviewers([BoomReviewer(), OkReviewer()], ctx)
        statuses = sorted(r.status for r in results)
        self.assertEqual(statuses, ["error", "ok"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m unittest tests.test_registry tests.test_engine -v
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'agaistock.reviewers.registry'`

- [ ] **Step 3: 实现 registry.py**

`src/agaistock/reviewers/registry.py`：

```python
"""点评师注册表：按配置发现并实例化点评师。"""
from __future__ import annotations

import importlib

from .. import config


class _UnavailableReviewer:
    """模块导入失败时的降级点评师。

    降级实例让注册流程保持"逐个隔离"的语义：某个点评师的模块坏了，
    其它点评师照常运行，坏掉的那位在调用 review 时抛错，由引擎转成
    status='error' 的 verdict 落库。
    """

    def __init__(self, reviewer_id: str, message: str) -> None:
        self.id = reviewer_id
        self.version = "0.0.0"
        self._message = message

    def review(self, ctx):
        raise RuntimeError(self._message)


def load_reviewers(specs: list[dict] | None = None) -> list[dict]:
    """返回启用的点评师配置，每项附加 `instance`。

    单个点评师的装载故障（模块不存在、导入期抛异常、类名不明确……）不影响
    其它点评师：该项 `instance` 是降级实例，`error` 记录是谁、哪个模块、
    原始异常是什么。降级实例在 review 时抛错，由引擎转成 status='error'
    的 verdict 落库，保证"结论必须全部落库"。
    """
    specs = specs if specs is not None else config.load_reviewers()
    loaded = []
    for spec in specs:
        if not spec.get("enabled", True):
            continue
        item = dict(spec)
        try:
            item["instance"] = instantiate(spec)
        except Exception as exc:  # noqa: BLE001 —— 单个点评师坏了不能拖垮整轮
            message = (
                f"点评师 {spec.get('id', 'unknown')} 的模块 "
                f"{spec.get('module', '<未声明>')} 装载失败: {type(exc).__name__}: {exc}"
            )
            item["instance"] = _UnavailableReviewer(str(spec.get("id", "unknown")), message)
            item["error"] = message
        loaded.append(item)
    return loaded


def instantiate(spec: dict):
    """按 `module` 路径导入模块，取其中的点评师类并实例化。

    类名解析规则（不做静默猜测）：
      1. 精确同名 `Reviewer` 的类；
      2. 只有一个名字以 `Reviewer` 结尾的候选类时用它（兼容 `FakeReviewer`）；
      3. 多个候选且没有精确同名时抛错并列出候选名。

    模块缺失或导入失败时抛错（由调用方决定是否隔离）。
    """
    module_path = spec["module"]
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise ImportError(f"点评师模块 {module_path} 导入失败: {exc}") from exc
    return _reviewer_class(module, module_path)()


def _reviewer_class(module, module_path: str) -> type:
    candidates = sorted(
        name
        for name, value in vars(module).items()
        if isinstance(value, type)
        and name.endswith("Reviewer")
        and not getattr(value, "_is_protocol", False)
    )
    if "Reviewer" in candidates:
        return getattr(module, "Reviewer")
    if len(candidates) == 1:
        return getattr(module, candidates[0])
    if not candidates:
        raise ImportError(f"模块 {module_path} 中没有 Reviewer 类")
    raise ImportError(
        f"模块 {module_path} 中有多个候选点评师类（{', '.join(candidates)}），"
        "无法确定用哪一个：请把实现类命名为 Reviewer"
    )
```

- [ ] **Step 4: 实现 engine.py**

`src/agaistock/reviewers/engine.py`：

```python
"""点评师调度：逐个执行、失败隔离、结果落库。"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from .contract import ReviewContext, ReviewVerdict, validate_verdict


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dimension_names() -> list[str]:
    """评分维度名列表，来自 config/scoring.json。"""
    from .. import config

    return [item["name"] for item in config.load_scoring()["dimensions"]]


def _error_verdict(
    reviewer_id: str,
    reviewer_version: str,
    duration_ms: int,
    caveats: list[str],
) -> ReviewVerdict:
    return ReviewVerdict(
        reviewer_id=reviewer_id,
        reviewer_version=reviewer_version,
        ran_at=_now_iso(),
        status="error",
        duration_ms=duration_ms,
        data_refs=[],
        findings=[],
        proposed_invalidation=[],
        horizon_hint=None,
        caveats=list(caveats),
    )


def _validation_errors(verdict: ReviewVerdict) -> list[str]:
    """契约校验错误列表；配置读不到时也降级成一条错误，不向上抛。"""
    try:
        dimensions = _dimension_names()
    except Exception as exc:  # noqa: BLE001 —— 配置问题也要隔离
        return [f"无法读取评分维度配置: {type(exc).__name__}: {exc}"]
    return validate_verdict(verdict, dimensions)


def run_one(reviewer, ctx: ReviewContext) -> ReviewVerdict:
    """执行单个点评师；异常或契约校验失败都转为 status='error' 的 verdict，绝不向上抛。

    校验不通过的结论不落成有效结论：findings 被丢弃，只在 caveats 里留下错误。
    """
    started = time.monotonic()
    try:
        raw = reviewer.review(ctx)
    except Exception as exc:  # noqa: BLE001 —— 点评师故障必须被隔离
        return _error_verdict(
            getattr(reviewer, "id", "unknown"),
            getattr(reviewer, "version", "0.0.0"),
            int((time.monotonic() - started) * 1000),
            [f"点评师执行失败: {type(exc).__name__}: {exc}"],
        )
    duration = int((time.monotonic() - started) * 1000)
    try:
        verdict = ReviewVerdict(
            reviewer_id=raw.reviewer_id,
            reviewer_version=raw.reviewer_version,
            ran_at=raw.ran_at or _now_iso(),
            status=raw.status,
            duration_ms=duration,
            data_refs=raw.data_refs,
            findings=raw.findings,
            proposed_invalidation=raw.proposed_invalidation,
            horizon_hint=raw.horizon_hint,
            caveats=raw.caveats,
        )
    except Exception as exc:  # noqa: BLE001 —— 点评师返回了非契约对象
        return _error_verdict(
            getattr(reviewer, "id", "unknown"),
            getattr(reviewer, "version", "0.0.0"),
            duration,
            [f"点评师结果无法解析: {type(exc).__name__}: {exc}"],
        )
    errors = _validation_errors(verdict)
    if errors:
        return _error_verdict(
            verdict.reviewer_id or getattr(reviewer, "id", "unknown"),
            verdict.reviewer_version or getattr(reviewer, "version", "0.0.0"),
            duration,
            [f"点评师结果未通过契约校验: {err}" for err in errors],
        )
    return verdict


def run_reviewers(reviewers: list, ctx: ReviewContext) -> list[ReviewVerdict]:
    """依次执行所有点评师，返回全部结果（含失败项）。"""
    return [run_one(reviewer, ctx) for reviewer in reviewers]


def persist(conn, observation_id: str, verdicts: list[ReviewVerdict]) -> list[dict]:
    """把 verdict 落库，返回落库后的字典列表。"""
    from ..storage import db

    saved = []
    for verdict in verdicts:
        db.insert_review(conn, observation_id, verdict.to_dict())
        saved.append(verdict.to_dict())
    return saved
```

- [ ] **Step 5: 运行测试确认通过**

```bash
python -m unittest tests.test_registry tests.test_engine -v
```

Expected: 5 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/agaistock/reviewers tests/test_registry.py tests/test_engine.py
git commit -m "feat: reviewer registry and execution engine with failure isolation"
```

---

### Task 5: 连接器调用桥与通达信 K 线取数

**Files:**
- Create: `src/agaistock/providers/__init__.py`, `src/agaistock/providers/mcode_cli.py`, `src/agaistock/providers/tdx.py`
- Create: `tests/test_mcode_cli.py`, `tests/test_tdx.py`

**Interfaces:**
- Produces:
  - `agaistock.providers.mcode_cli.call_connector(tool: str, args: dict, timeout: int = 180) -> str`
    返回连接器返回的 **text 字段**（已剥掉外层 `[{type:"text",text:...}]` 包装）。
  - `agaistock.providers.mcode_cli.MCodedToolsMissing(RuntimeError)` —— CLI 不在 PATH 时抛出。
  - `agaistock.providers.tdx.fetch_raw_kline(symbol: str, setcode: str, period: str, want_num: int = 500) -> dict`
    返回**不复权**原始 payload（`tqFlag="0"`，含 `Rows` / `ListHead` / `AttachInfo`）。
  - `agaistock.providers.tdx.fetch_kline(symbol: str, setcode: str, period: str, want_num: int = 500, factors: list[dict] | None = None) -> dict`
    返回**后复权** payload（结构与原始 payload 相同，`Rows` 里的 `Open`/`High`/`Low`/`Close` 已是后复权价）。
    **后复权由本层自己重建**（不依赖连接器的 `tqFlag:"2"` —— 实测它对 30 分钟级别不生效，
    见 Global Constraint 16）：取不复权序列 + 复权因子表 → 逐 bar 换算。
    `factors` 可传入已取好的因子表以避免重复调用；不给则内部自己取。
    调用方无需也不能切换复权口径（Global Constraint 16/17）。
  - `agaistock.providers.tdx.fetch_adjustment_factors(symbol: str) -> list[dict]`
    拉取该标的的**复权因子**（经 `tdx_api_data` 的 `capital_flow` preset），归一化为
    `[{"ex_date": "2026-06-26", "factor": 2.6, "constant": 2.2552}, ...]`，按 `ex_date` 降序；
    该标的**确实没有**除权记录时返回 `[]`。
    **「请求成功但找不到因子表」不是空表**：连接器返回形态不稳定（Global Constraint 19），
    此时必须重试一次，仍失败**抛错**，不得静默返回 `[]`。
  - `agaistock.providers.tdx.factor_row_for(factors: list[dict], date: str) -> dict`
    取某日期生效的因子行（`ex_date ≤ date` 的最新一行，日期统一成 `YYYYMMDD` 比较）；
    早于首个 ex_date 时返回 `{"ex_date": "", "factor": 1.0, "constant": 0.0}`（恒等变换）。
  - `agaistock.providers.tdx.apply_houfuquan(payload: dict, factors: list[dict]) -> dict`
    把 payload 里 `Rows` 的 `Open`/`High`/`Low`/`Close` 换算成后复权价，返回新 payload（原 payload 不改）。
    `Volume` / `Amount` 保持原值。
  - `agaistock.providers.tdx.setcode_for(symbol: str) -> str`，按代码前缀推断市场：`6`→`"1"`，`0`/`3`→`"0"`，`4`/`8`/`9`→`"2"`（北交所含 `920xxx`）。
  - `agaistock.providers.tdx.TDX_KLINE = "connector__tdx-finance__tdx_kline"`
  - `agaistock.providers.tdx.TDX_API_DATA = "connector__tdx-finance__tdx_api_data"`
  - `agaistock.providers.tdx.to_houfuquan(price: float, factor_row: dict) -> float`
    现价（不复权/前复权）→ 后复权：`price × factor + constant`。`factor_row` 是
    `fetch_adjustment_factors` 返回的一行（`{"ex_date", "factor", "constant"}`）。
  - `agaistock.providers.tdx.to_current_price(price: float, factor_row: dict) -> float`
    后复权 → 现价：`(price − constant) / factor`。
  - `agaistock.storage.db.insert_adjustment_factors(conn, symbol, factors) -> int` / `list_adjustment_factors(conn, symbol) -> list[dict]`
    —— 复权因子落库（Task 2 存储层的扩展，见 Task 2 的 SCHEMA 与 Interfaces）。

- [ ] **Step 1: 写失败的测试**

`tests/test_mcode_cli.py`：

```python
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agaistock.providers import mcode_cli


class McodeCliTests(unittest.TestCase):
    @mock.patch("agaistock.providers.mcode_cli.subprocess.run")
    def test_call_connector_unwraps_text_field(self, fake_run):
        fake_run.return_value = mock.Mock(
            returncode=0,
            stdout=json.dumps([{"type": "text", "text": "hello"}]),
            stderr="",
        )
        result = mcode_cli.call_connector("some__tool", {"a": 1})
        self.assertEqual(result, "hello")

    @mock.patch("agaistock.providers.mcode_cli.subprocess.run")
    def test_call_connector_raises_on_non_zero_exit(self, fake_run):
        fake_run.return_value = mock.Mock(returncode=1, stdout="", stderr="boom")
        # MCodedToolsMissing 是 RuntimeError 的子类，所以只断言 RuntimeError 分不出两类错误；
        # 必须显式断言「不是缺 CLI」。
        with self.assertRaises(RuntimeError) as ctx:
            mcode_cli.call_connector("some__tool", {})
        self.assertNotIsInstance(ctx.exception, mcode_cli.MCodedToolsMissing)

    @mock.patch("agaistock.providers.mcode_cli.subprocess.run")
    def test_call_connector_uses_args_file_not_inline_json(self, fake_run):
        fake_run.return_value = mock.Mock(
            returncode=0, stdout=json.dumps([{"type": "text", "text": "ok"}]), stderr=""
        )
        mcode_cli.call_connector("some__tool", {"code": "002378"})
        command = fake_run.call_args[0][0]
        self.assertIn("--args-file", command)
        self.assertNotIn("--args ", command)

    @mock.patch("agaistock.providers.mcode_cli.subprocess.run")
    def test_call_connector_escapes_paths_with_spaces(self, fake_run):
        fake_run.return_value = mock.Mock(
            returncode=0, stdout=json.dumps([{"type": "text", "text": "ok"}]), stderr=""
        )
        # 目录必须真实存在：实现要把 args.json 写进去，把目录存在性一起 mock 掉会写崩。
        with tempfile.TemporaryDirectory() as root:
            spaced = Path(root) / "a b" / "tmp"
            spaced.mkdir(parents=True)
            with mock.patch("agaistock.providers.mcode_cli.tempfile.TemporaryDirectory") as tmp_dir:
                tmp_dir.return_value.__enter__.return_value = str(spaced)
                mcode_cli.call_connector("some__tool", {})
            args_file = spaced / "args.json"
            # args 文件确实写进了这个带空格的目录
            self.assertTrue(args_file.is_file())
        command = fake_run.call_args[0][0]
        # 含空格的路径在命令行里必须被引号包住，否则 cmd.exe 会把它拆成两个参数
        self.assertIn(f'"{args_file}"', command)

    @mock.patch("agaistock.providers.mcode_cli.subprocess.run")
    def test_call_connector_raises_missing_cli_when_command_not_found(self, fake_run):
        fake_run.return_value = mock.Mock(
            returncode=1,
            stdout="",
            stderr="'mcode-tools' is not recognized as an internal or external command",
        )
        with self.assertRaises(mcode_cli.MCodedToolsMissing):
            mcode_cli.call_connector("some__tool", {})


if __name__ == "__main__":
    unittest.main()
```

`tests/test_tdx.py`：

```python
import json
import unittest
from unittest import mock

from agaistock.providers import tdx


class TdxTests(unittest.TestCase):
    def test_setcode_for_shenzhen(self):
        self.assertEqual(tdx.setcode_for("002378"), "0")

    def test_setcode_for_shanghai(self):
        self.assertEqual(tdx.setcode_for("600519"), "1")

    def test_setcode_for_chinext(self):
        self.assertEqual(tdx.setcode_for("300750"), "0")

    def test_setcode_for_bse(self):
        self.assertEqual(tdx.setcode_for("430047"), "2")

    def test_setcode_for_bse_new_code_space(self):
        # 北交所 920xxx 是当前代码空间，连接器按 setcode=2 提供
        self.assertEqual(tdx.setcode_for("920001"), "2")

    def test_setcode_rejects_unknown_prefix(self):
        with self.assertRaises(ValueError):
            tdx.setcode_for("12345")

    @mock.patch("agaistock.providers.tdx.call_connector")
    def test_fetch_kline_requests_raw_series_and_rebuilds_houfuquan(self, fake_call):
        # 连接器的 tqFlag="2" 对 30 分钟级别不生效，所以本层取不复权原始序列自己重建
        def fake(tool, args):
            if tool == tdx.TDX_KLINE:
                self.assertEqual(args["tqFlag"], "0")
                return json.dumps(
                    {
                        "Rows": [
                            {
                                "Data": "20261124",
                                "Open": "1460.00", "High": "1470.00",
                                "Low": "1450.00", "Close": "1460.00",
                                "Volume": 100.0, "Amount": 146000.0,
                            }
                        ]
                    }
                )
            return json.dumps(
                {
                    "response": {
                        "transformed": {
                            "tables": [
                                {
                                    "name": "adjustment_factor",
                                    "rows": [
                                        {
                                            "日期": "2026-06-26",
                                            "精确复权因子": 5.627766,
                                            "精确复权常数": 1798.159313,
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                },
                ensure_ascii=False,
            )

        fake_call.side_effect = fake
        payload = tdx.fetch_kline("600519", "1", "4", want_num=1)
        row = payload["Rows"][0]
        # 1460.00 × 5.627766 + 1798.159313 = 10014.70（实测的日线后复权值）
        self.assertAlmostEqual(float(row["Close"]), 10014.70, places=2)
        self.assertAlmostEqual(float(row["Open"]), 10014.70, places=2)
        # 量额保持原值
        self.assertEqual(row["Amount"], 146000.0)
        self.assertEqual(row["Volume"], 100.0)

    @mock.patch("agaistock.providers.tdx.call_connector")
    def test_fetch_kline_uses_provided_factors_without_extra_call(self, fake_call):
        fake_call.side_effect = lambda tool, args: json.dumps(
            {
                "Rows": [
                    {
                        "Data": "20261124", "Open": "1460.00", "High": "1470.00",
                        "Low": "1450.00", "Close": "1460.00",
                        "Volume": 100.0, "Amount": 146000.0,
                    }
                ]
            }
        )
        factors = [{"ex_date": "2026-06-26", "factor": 5.627766, "constant": 1798.159313}]
        payload = tdx.fetch_kline("600519", "1", "4", want_num=1, factors=factors)
        self.assertAlmostEqual(float(payload["Rows"][0]["Close"]), 10014.70, places=2)
        # 只调了一次连接器（K 线），因子表是调用方给的
        self.assertEqual(fake_call.call_count, 1)

    def test_factor_row_for_picks_the_latest_row_not_after_the_date(self):
        factors = [
            {"ex_date": "2026-06-26", "factor": 5.627766, "constant": 1798.159313},
            {"ex_date": "2025-12-19", "factor": 5.627766, "constant": 1640.4455},
            {"ex_date": "2024-12-20", "factor": 5.627766, "constant": 1349.883934},
        ]
        # 因子表日期带连字符、K 线日期不带，比较必须归一化
        self.assertEqual(tdx.factor_row_for(factors, "20260626")["ex_date"], "2026-06-26")
        self.assertEqual(tdx.factor_row_for(factors, "20250108")["ex_date"], "2024-12-20")
        # 早于最早一行因子 → 恒等变换
        early = tdx.factor_row_for(factors, "20240102")
        self.assertEqual(early["ex_date"], "")
        self.assertEqual(early["factor"], 1.0)
        self.assertEqual(early["constant"], 0.0)

    def test_factor_row_for_before_first_ex_date_is_identity(self):
        factors = [{"ex_date": "2026-06-26", "factor": 5.627766, "constant": 1798.159313}]
        row = tdx.factor_row_for(factors, "20240102")
        self.assertEqual(row["factor"], 1.0)
        self.assertEqual(row["constant"], 0.0)

    def test_apply_houfuquan_leaves_volume_and_amount_untouched(self):
        payload = {
            "Rows": [
                {
                    "Data": "20261124", "Open": "1460.00", "High": "1470.00",
                    "Low": "1450.00", "Close": "1460.00",
                    "Volume": 100.0, "Amount": 146000.0,
                }
            ]
        }
        factors = [{"ex_date": "2026-06-26", "factor": 5.627766, "constant": 1798.159313}]
        converted = tdx.apply_houfuquan(payload, factors)
        self.assertAlmostEqual(float(converted["Rows"][0]["Close"]), 10014.70, places=2)
        self.assertEqual(converted["Rows"][0]["Volume"], 100.0)
        self.assertEqual(converted["Rows"][0]["Amount"], 146000.0)
        # 原 payload 不被就地修改
        self.assertEqual(payload["Rows"][0]["Close"], "1460.00")

    @mock.patch("agaistock.providers.tdx.call_connector")
    def test_fetch_adjustment_factors_normalizes_rows(self, fake_call):
        fake_call.return_value = (
            "tdx_api_data 请求成功\n\n"
            + json.dumps(
                {
                    "response": {
                        "transformed": {
                            "tables": [
                                {
                                    "name": "capital_flow",
                                    "rows": [{"日期": "2026-11-24", "主力净额金额(元)": -1}],
                                },
                                {
                                    "name": "adjustment_factor",
                                    "rows": [
                                        {"日期": "2026-06-26", "精确复权因子": 2.6, "精确复权常数": 2.2552},
                                        {"日期": "2025-06-06", "精确复权因子": 2.6, "精确复权常数": 1.9432},
                                    ],
                                },
                            ]
                        }
                    }
                },
                ensure_ascii=False,
            )
        )
        factors = tdx.fetch_adjustment_factors("002378")
        self.assertEqual(
            factors,
            [
                {"ex_date": "2026-06-26", "factor": 2.6, "constant": 2.2552},
                {"ex_date": "2025-06-06", "factor": 2.6, "constant": 1.9432},
            ],
        )

    @mock.patch("agaistock.providers.tdx.call_connector")
    def test_fetch_adjustment_factors_empty_when_table_has_no_rows(self, fake_call):
        fake_call.return_value = (
            "tdx_api_data 请求成功\n\n"
            + json.dumps(
                {
                    "response": {
                        "transformed": {"tables": [{"name": "adjustment_factor", "rows": []}]}
                    }
                },
                ensure_ascii=False,
            )
        )
        self.assertEqual(tdx.fetch_adjustment_factors("002378"), [])

    @mock.patch("agaistock.providers.tdx.call_connector")
    def test_fetch_adjustment_factors_raises_when_table_missing(self, fake_call):
        # 连接器返回形态不稳定：找不到因子表 != 该标的没有除权记录。
        # 必须重试一次，仍失败就抛错，不能静默返回空表。
        fake_call.return_value = (
            "tdx_api_data 请求成功\n\n"
            + json.dumps({"response": {"data": {"anything": 1}}}, ensure_ascii=False)
        )
        with self.assertRaises(RuntimeError):
            tdx.fetch_adjustment_factors("002378")
        self.assertEqual(fake_call.call_count, 2)

    def test_to_houfuquan_matches_measured_formula(self):
        # 600519 2026-06-26 的因子行：现价 1460.00 → 后复权 10014.70
        row = {"ex_date": "2026-06-26", "factor": 5.627766, "constant": 1798.159313}
        self.assertAlmostEqual(tdx.to_houfuquan(1460.0, row), 10014.70, places=2)

    def test_to_current_price_is_inverse_of_to_houfuquan(self):
        row = {"ex_date": "2026-06-26", "factor": 5.627766, "constant": 1798.159313}
        self.assertAlmostEqual(tdx.to_current_price(10014.70, row), 1460.0, places=2)
        self.assertAlmostEqual(
            tdx.to_current_price(tdx.to_houfuquan(15.54, row), row), 15.54, places=6
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m unittest tests.test_mcode_cli tests.test_tdx -v
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'agaistock.providers'`

- [ ] **Step 3: 实现 mcode_cli.py**

```python
"""调用宿主托管的连接器（mcode-tools CLI）。

Windows 约束（已实测）：
  - `mcode-tools` 是 .cmd 批处理 → subprocess 必须走 shell
  - `--args '{...}'` 的双引号会被 shell 剥离 → 必须用 --args-file
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path


class MCodedToolsMissing(RuntimeError):
    """mcode-tools CLI 不在 PATH 上。"""


# shell=True 时 cmd.exe 不会抛 FileNotFoundError，而是返回非 0 退出码并在 stderr 里
# 说明「不是内部或外部命令」。两种失败形态必须归到同一个异常类型上，否则调用方
# 只会看到笼统的 RuntimeError。标记词刻意收窄，避免把连接器自身的报错误判成缺 CLI。
_MISSING_CLI_MARKERS = (
    "is not recognized",
    "command not found",
    "不是内部或外部命令",
    "无法将",
)


def _looks_like_missing_cli(stderr: str) -> bool:
    lowered = (stderr or "").lower()
    return any(marker.lower() in lowered for marker in _MISSING_CLI_MARKERS)


def call_connector(tool: str, args: dict, timeout: int = 180) -> str:
    """调用一个连接器工具，返回其 text 字段内容。"""
    with tempfile.TemporaryDirectory() as tmp:
        args_file = Path(tmp) / "args.json"
        args_file.write_text(json.dumps(args, ensure_ascii=False), encoding="utf-8")
        argv = [
            "mcode-tools",
            "connector",
            "call",
            tool,
            "--args-file",
            str(args_file),
        ]
        # shell=True 时 Python 会把 argv 直接拼进命令行；必须先用 list2cmdline 转义，
        # 否则含空格的路径（如带空格的 %TEMP%）会被 cmd.exe 拆成多个参数。
        command = subprocess.list2cmdline(argv)
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                shell=True,
            )
        except FileNotFoundError as exc:
            raise MCodedToolsMissing(
                "未找到 mcode-tools CLI；请确认 MCode 运行时在 PATH 中"
            ) from exc

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        if _looks_like_missing_cli(stderr):
            raise MCodedToolsMissing("未找到 mcode-tools CLI；请确认 MCode 运行时在 PATH 中")
        raise RuntimeError(f"连接器 {tool} 调用失败(exit={result.returncode}): {stderr[:500]}")

    stdout = (result.stdout or "").strip()
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"连接器 {tool} 返回非 JSON: {stdout[:300]}") from exc

    if isinstance(payload, list) and payload and isinstance(payload[0], dict) and "text" in payload[0]:
        return payload[0]["text"]
    if isinstance(payload, str):
        return payload
    return stdout
```

- [ ] **Step 4: 实现 tdx.py**

```python
"""通达信取数（经由 mcode-tools 连接器）。

复权口径（D6 / Global Constraint 16）：K 线一律取**后复权**。

关键事实（实测 2026-11-24）：
  - 连接器的 `tqFlag="2"`（后复权）**只在日线/周线生效，30 分钟级别不生效**：
    600519 的 m30 给 1563.54，同一天的日线给 10014.70；002378 m30 给 15.73、日线给 42.66。
    直接用连接器的后复权，三个级别会落在两个价格空间。
  - 所以本层取 `tqFlag="0"`（不复权）原始序列 + 复权因子表，**自己重建**后复权。
    重建规则与连接器自身的后复权一致（600519 700 根日线中位相对误差 0.00003%）。
  - `Volume` / `Amount` 保持原值（与连接器后复权行为一致）。

口径在适配层收口，调用方不传、不切换。
"""
from __future__ import annotations

import json

from .mcode_cli import call_connector

TDX_KLINE = "connector__tdx-finance__tdx_kline"
TDX_QUOTES = "connector__tdx-finance__tdx_quotes"
TDX_API_DATA = "connector__tdx-finance__tdx_api_data"

# 请求连接器时固定要**不复权**原始序列，后复权由本层重建。
TQ_FLAG_RAW = "0"

# 复权因子所在的后端接口与子视图（主规格 §6.7.4）。
_ADJ_ENTRY = "TdxSharePCCW.tdxf10_gg_jyds"
_ADJ_FIXED_TAG = "zjlx"

# 需要做后复权换算的价格字段。
_PRICE_KEYS = ("Open", "High", "Low", "Close")


def setcode_for(symbol: str) -> str:
    """按代码前缀推断市场代码：沪=1 深=0 北=2。"""
    code = str(symbol).strip()
    if not code.isdigit() or len(code) != 6:
        raise ValueError(f"无法识别的证券代码: {symbol!r}")
    if code.startswith("6"):
        return "1"
    if code.startswith(("0", "3")):
        return "0"
    # 北交所：43xxxx / 83xxxx / 87xxxx 旧代码段 + 920xxx 当前代码段
    if code.startswith(("4", "8", "9")):
        return "2"
    raise ValueError(f"无法识别的证券代码前缀: {symbol!r}")


def _payload_from_text(text: str) -> dict:
    """从连接器返回文本中抽出 JSON 负载。

    返回文本形如：`<摘要>\n详细K线数据:\n{...}` —— 取第一个 `{` 起的内容。
    用 raw_decode 只解析第一个 JSON 值，容忍 JSON 之后还有尾随说明文字。
    """
    start = text.find("{")
    if start < 0:
        raise RuntimeError(f"连接器返回中找不到 JSON: {text[:200]}")
    try:
        payload, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"连接器返回的 JSON 解析失败: {text[start:][:200]}") from exc
    return payload


def _normalize_factor_rows(table: dict) -> list[dict]:
    """把 adjustment_factor 表归一化成 [{ex_date, factor, constant}]，按 ex_date 降序。"""
    factors = []
    for row in table.get("rows") or []:
        try:
            factor = float(row["精确复权因子"])
            constant = float(row["精确复权常数"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"复权因子表缺少预期列：{row}") from exc
        factors.append(
            {
                "ex_date": str(row.get("日期", "")).strip(),
                "factor": factor,
                "constant": constant,
            }
        )
    factors.sort(key=lambda item: item["ex_date"], reverse=True)
    return factors


def _find_factor_table(payload: dict) -> dict | None:
    tables = (payload.get("response") or {}).get("transformed", {}).get("tables") or []
    for table in tables:
        if table.get("name") == "adjustment_factor":
            return table
    return None


def fetch_adjustment_factors(symbol: str) -> list[dict]:
    """拉取复权因子，归一化成 [{ex_date, factor, constant}]，按 ex_date 降序。

    数据来自 tdx_api_data 的 capital_flow preset —— 同一个 preset 返回两张表，
    复权因子那张叫 adjustment_factor，列名是中文：
    日期 / 精确复权因子 / 精确复权常数。

    连接器返回形态不稳定（Global Constraint 19）：偶尔给 `response.data` 而不是
    `response.transformed.tables`。所以「找不到因子表」**不等于**「该标的没有除权记录」，
    先重试一次，仍失败就抛错 —— 静默返回空表会让后复权重建悄悄退化成不复权。
    """
    for attempt in range(2):
        text = call_connector(
            TDX_API_DATA,
            {"entry": _ADJ_ENTRY, "fixedTag": _ADJ_FIXED_TAG, "code": str(symbol)},
        )
        payload = _payload_from_text(text)
        table = _find_factor_table(payload)
        if table is not None:
            return _normalize_factor_rows(table)
    raise RuntimeError(f"拉取 {symbol} 的复权因子失败：未找到 adjustment_factor 表")


def factor_row_for(factors: list[dict], date: str) -> dict:
    """取某日期生效的因子行：ex_date ≤ date 的最新一行。

    因子表的日期带连字符（2026-06-26），K 线日期不带（20261124）——
    比较前统一成 YYYYMMDD，否则字符串比较会挑错行。
    早于首个 ex_date 的日期返回恒等变换（factor=1, constant=0）。

    **与入参顺序无关**：`fetch_adjustment_factors` 返回的是 ex_date 降序，
    这里必须自己取「匹配行里 ex_date 最大的那个」，不能靠遍历顺序碰运气。
    """
    key = str(date).replace("-", "")
    best = None
    best_key = ""
    for row in factors or []:
        row_key = str(row.get("ex_date", "")).replace("-", "")
        if not row_key or row_key > key:
            continue
        if row_key >= best_key:
            best = row
            best_key = row_key
    return best or {"ex_date": "", "factor": 1.0, "constant": 0.0}


def apply_houfuquan(payload: dict, factors: list[dict]) -> dict:
    """把 payload 里 Rows 的价格字段换算成后复权，返回新 payload（原 payload 不改）。

    后复权价(d) = 不复权价(d) × 精确复权因子 + 精确复权常数
    `Volume` / `Amount` 保持原值（与连接器后复权行为一致）。
    """
    rows = payload.get("Rows") or []
    converted = []
    for row in rows:
        if not isinstance(row, dict):
            converted.append(row)
            continue
        frow = factor_row_for(factors, row.get("Data", ""))
        factor = float(frow.get("factor", 1.0))
        constant = float(frow.get("constant", 0.0))
        new_row = dict(row)
        for key in _PRICE_KEYS:
            value = row.get(key)
            if value is None:
                continue
            try:
                new_row[key] = f"{float(value) * factor + constant:.6f}"
            except (TypeError, ValueError):
                continue
        converted.append(new_row)
    new_payload = dict(payload)
    new_payload["Rows"] = converted
    return new_payload


def fetch_raw_kline(symbol: str, setcode: str, period: str, want_num: int = 500) -> dict:
    """拉取不复权原始序列，返回原始 payload（含升序的 Rows）。"""
    text = call_connector(
        TDX_KLINE,
        {
            "code": str(symbol),
            "setcode": str(setcode),
            "period": str(period),
            "wantNum": int(want_num),
            "tqFlag": TQ_FLAG_RAW,
        },
    )
    return _payload_from_text(text)


def fetch_kline(
    symbol: str,
    setcode: str,
    period: str,
    want_num: int = 500,
    factors: list[dict] | None = None,
) -> dict:
    """拉取后复权序列（口径在适配层收口，调用方不切换）。

    `factors` 可传入已取好的因子表以避免重复调用；不给则内部自己取。
    """
    payload = fetch_raw_kline(symbol, setcode, period, want_num)
    if not (payload.get("Rows") or []):
        return payload
    factor_rows = factors if factors is not None else fetch_adjustment_factors(symbol)
    return apply_houfuquan(payload, factor_rows)


def fetch_quotes(symbol: str, setcode: str) -> dict:
    """拉取实时行情快照（现价口径，不复权）。"""
    text = call_connector(TDX_QUOTES, {"code": str(symbol), "setcode": str(setcode)})
    return _payload_from_text(text)


def to_houfuquan(price: float, factor_row: dict) -> float:
    """现价 → 后复权。

    公式（已实测）：后复权价 = 现价 × 精确复权因子 + 精确复权常数。
    `factor_row` 必须是该价格所属日期对应的那一行（当前价位用最新一行）。
    """
    return float(price) * float(factor_row["factor"]) + float(factor_row["constant"])


def to_current_price(price: float, factor_row: dict) -> float:
    """后复权 → 现价（`to_houfuquan` 的逆变换）。"""
    return (float(price) - float(factor_row["constant"])) / float(factor_row["factor"])
```

同时创建空文件 `src/agaistock/providers/__init__.py`。

- [ ] **Step 5: 运行测试确认通过**

```bash
python -m unittest tests.test_mcode_cli tests.test_tdx -v
```

Expected: 21 tests PASS（`test_mcode_cli` 5 条 + `test_tdx` 16 条）+ `test_storage` 13 条

- [ ] **Step 6: 实现复权因子落库（存储层扩展）**

Task 2 的 `src/agaistock/storage/db.py` 按 Task 2 段的 SCHEMA 与 Interfaces 增补：

- `SCHEMA` 里加 `adjustment_factors` 表（`symbol` / `ex_date` / `factor` / `constant` / `fetched_at`，主键 `(symbol, ex_date)`）。
- `insert_adjustment_factors(conn, symbol, factors) -> int`：同一 `(symbol, ex_date)` 重复写入**覆盖**（upsert），返回写入条数。
- `list_adjustment_factors(conn, symbol) -> list[dict]`：按 `ex_date` **降序**返回。

`tests/test_storage.py` 同步增补 3 条测试（见 Task 2 段）。

- [ ] **Step 7: 冒烟验证真实调用（可选但强烈建议）**

```bash
python -c "from agaistock.providers import tdx; p=tdx.fetch_kline('002378','0','4',5); print(len(p['Rows'])); print(p['Rows'][0]['Data']); print(p['Rows'][-1]['Data']); print(p['Rows'][-1]['Close'])"
```

Expected: `5` / `20261118` / `20261124` / `42.66xxxx`（**首早末晚 = 升序**；Close 是**后复权**价，不是现价 15.54）

```bash
python -c "from agaistock.providers import tdx; f=tdx.fetch_adjustment_factors('002378'); print(len(f)); print(f[0])"
```

Expected: `14` / `{'ex_date': '2026-06-26', 'factor': 2.6, 'constant': 2.2552}`

```bash
python -c "from agaistock.providers import tdx; print(tdx.fetch_kline('002378','0','2',1)['Rows'][-1]['Close'])"
```

Expected: 30 分钟级别的 Close **也是后复权**（与日线同量级，≈ 42.6）——
这一条是本次修正的关键：连接器自己的 `tqFlag:"2"` 在 30 分钟级别不生效。

- [ ] **Step 8: Commit**

```bash
git add src/agaistock/providers src/agaistock/storage/db.py tests/test_mcode_cli.py tests/test_tdx.py tests/test_storage.py
git commit -m "feat: mcode-tools connector bridge, tdx kline provider and adjustment factors"
```

> 本 Task 在实际执行中分两轮落地（复权口径在第二轮修正，见 Global Constraint 16）：
> 第一轮提交连接器桥 + 通达信 provider + 复权因子落库；第二轮把后复权改成
> **provider 层自建**（`fetch_raw_kline` + `apply_houfuquan` + `factor_row_for`），
> 并让 `fetch_adjustment_factors` 在找不到因子表时重试后抛错。
> 第二轮的提交只动 `src/agaistock/providers` 与 `tests/test_tdx.py`。

---

### Task 6: K 线适配器 —— `Rows` → 东财格式

**Files:**
- Create: `src/agaistock/providers/tdx_rows_to_em.py`
- Create: `tests/test_tdx_rows_to_em.py`

**Interfaces:**
- Consumes: `tdx.fetch_kline` 的返回（Task 5）—— **后复权序列**（`tqFlag="2"`，Global Constraint 16），本任务只做格式转换，不碰复权口径
- Produces:
  - `agaistock.providers.tdx_rows_to_em.rows_to_em_format(payload: dict) -> dict`
    返回 `{"data": {"klines": ["YYYY-MM-DD,o,c,h,l,v,a", ...], "count": int}}`，**保持升序**。
  - `agaistock.providers.tdx_rows_to_em.parse_tdx_date(value: str) -> str`

- [ ] **Step 1: 写失败的测试**

```python
import unittest

from agaistock.providers import tdx_rows_to_em


def row(date="20241104", o="7.38", h="7.40", l="6.82", c="6.98", v="897053.84", a="644506752"):
    return {
        "Data": date, "Second": "0", "Open": o, "High": h, "Low": l, "Close": c,
        "Amount": float(a), "Volume": float(v),
    }


class RowsToEmTests(unittest.TestCase):
    def test_maps_columns_to_eastmoney_field_order(self):
        result = tdx_rows_to_em.rows_to_em_format({"Rows": [row()]})
        self.assertEqual(
            result["data"]["klines"],
            ["2024-11-04,7.38,6.98,7.40,6.82,897054,644506752"],
        )

    def test_preserves_ascending_order_without_reversing(self):
        payload = {"Rows": [row(date="20241104"), row(date="20241105"), row(date="20241106")]}
        result = tdx_rows_to_em.rows_to_em_format(payload)
        dates = [k.split(",")[0] for k in result["data"]["klines"]]
        self.assertEqual(dates, ["2024-11-04", "2024-11-05", "2024-11-06"])

    def test_parse_date_accepts_compact_and_iso(self):
        self.assertEqual(tdx_rows_to_em.parse_tdx_date("20241104"), "2024-11-04")
        self.assertEqual(tdx_rows_to_em.parse_tdx_date("2024-11-04"), "2024-11-04")

    def test_raises_on_empty_rows(self):
        with self.assertRaises(ValueError):
            tdx_rows_to_em.rows_to_em_format({"Rows": []})

    def test_raises_when_row_lacks_close(self):
        broken = row()
        del broken["Close"]
        with self.assertRaises(ValueError):
            tdx_rows_to_em.rows_to_em_format({"Rows": [broken]})

    def test_skips_rows_with_unparsable_numbers(self):
        broken = row()
        broken["Close"] = "not-a-number"
        result = tdx_rows_to_em.rows_to_em_format({"Rows": [broken, row(date="20241105")]})
        self.assertEqual(result["data"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m unittest tests.test_tdx_rows_to_em -v
```

Expected: FAIL —— `ModuleNotFoundError`

- [ ] **Step 3: 实现 tdx_rows_to_em.py**

```python
"""TDX `Rows` → 东财格式。

上游 chanlun-core 的 tdx_to_em_format.py 针对旧结构（ListHead 数组 + AttachInfo 数组的数组）
编写，当前 tdx_kline 返回 `Rows` 对象数组（英文字段、升序），故重写。

关键点：
  - 字段序 东财 = date,o,c,h,l,v,a；TDX Rows 的键顺序是 o,h,l,c → 必须按名取，不可按位取
  - Rows 已是升序，**不要 reverse**
"""
from __future__ import annotations

from typing import Any

REQUIRED_KEYS = ("Data", "Open", "High", "Low", "Close")


def parse_tdx_date(value: str) -> str:
    """统一为 YYYY-MM-DD。"""
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if len(text) == 10 and "-" in text:
        return text
    if "/" in text:
        return text.replace("/", "-")
    raise ValueError(f"无法识别的日期格式: {value!r}")


def rows_to_em_format(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("Rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("payload 中没有 Rows 数据")
    klines: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        missing = [k for k in REQUIRED_KEYS if k not in row]
        if missing:
            raise ValueError(f"K 线行缺少字段 {missing}：{row}")
        try:
            date = parse_tdx_date(row["Data"])
            o = float(row["Open"])
            h = float(row["High"])
            l = float(row["Low"])
            c = float(row["Close"])
            v = float(row.get("Volume") or 0)
            a = float(row.get("Amount") or 0)
        except (TypeError, ValueError):
            continue
        klines.append(f"{date},{o:.2f},{c:.2f},{h:.2f},{l:.2f},{v:.0f},{a:.0f}")
    if not klines:
        raise ValueError("所有 K 线行都无法解析")
    return {"data": {"klines": klines, "count": len(klines)}}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m unittest tests.test_tdx_rows_to_em -v
```

Expected: 6 tests PASS

- [ ] **Step 5: 用真实数据验证（关键一步）**

```bash
python -c "from agaistock.providers import tdx, tdx_rows_to_em; p=tdx.fetch_kline('002378','0','4',20); r=tdx_rows_to_em.rows_to_em_format(p); print(r['data']['count']); print(r['data']['klines'][0]); print(r['data']['klines'][-1])"
```

Expected: `20`，首行日期早于末行日期（**升序**）

- [ ] **Step 6: Commit**

```bash
git add src/agaistock/providers/tdx_rows_to_em.py tests/test_tdx_rows_to_em.py
git commit -m "feat: tdx Rows to eastmoney kline format adapter"
```

---

### Task 7: 缠论引擎封装（三级别编排 + vendor 拷贝）

**Files:**
- Create: `src/agaistock/skills/__init__.py`, `src/agaistock/skills/anchor_chanlun/__init__.py`
- Create: `src/agaistock/skills/anchor_chanlun/engine.py`
- Create: `src/agaistock/skills/anchor_chanlun/vendor/chanlun-core/**`（整目录拷贝）
- Create: `tests/test_chanlun_engine.py`

**Interfaces:**
- Consumes: `tdx.fetch_kline`（Task 5，**后复权序列**）、`tdx_rows_to_em.rows_to_em_format`（Task 6）
  - 复权口径由 provider 层收口（Global Constraint 16）：`fetch_kline` 返回的**三个级别都在后复权空间**。
    连接器自己的 `tqFlag:"2"` 对 30 分钟级别不生效（实测 002378 m30 给 15.73、日线给 42.66），
    provider 层已改为用不复权序列 + 复权因子自行重建，因此**本任务无需再关心复权**。
  - 真实数据自检时，`levels.week.last_close` / `levels.day.last_close` / `levels.m30.last_close`
    应当**同量级**（都约等于后复权现价 42.66 量级）。若 m30 明显小一个数量级，说明复权没生效。
- Produces:
  - `agaistock.skills.anchor_chanlun.engine.LEVELS = {"week": "5", "day": "4", "m30": "2"}`
  - `agaistock.skills.anchor_chanlun.engine.LEVEL_ORDER = ("week", "day", "m30")`
  - `agaistock.skills.anchor_chanlun.engine.vendor_root() -> Path`，指向 `vendor/chanlun-core`
  - `agaistock.skills.anchor_chanlun.engine.build_structure(symbol: str, name: str, setcode: str, work_dir: Path, kline_fetcher=tdx.fetch_kline) -> dict`
    返回 **`chan_multi_level.json` 的内容**（含 `levels` / `resonance` / `interval_nesting` / `window_alignment` / `action` / `key_levels` / `caveats`）。
  - `agaistock.skills.anchor_chanlun.engine.load_analysis(work_dir: Path, level: str) -> dict`，读 `chan_analysis_<level>.json`（单级别原始分析文件，供排障与单级别调试使用）。

- [ ] **Step 1: 拷贝 vendor（只读，不改一行）**

```bash
mkdir -p src/agaistock/skills/anchor_chanlun/vendor
cp -r "C:/Users/shawn/.workbuddy/plugins/marketplaces/my-experts/plugins/chanlun-analyst/skills/chanlun-core" src/agaistock/skills/anchor_chanlun/vendor/
rm -rf src/agaistock/skills/anchor_chanlun/vendor/chanlun-core/scripts/__pycache__
```

Windows PowerShell 用：

```powershell
New-Item -ItemType Directory -Force -Path 'D:\workroom\agaistock\src\agaistock\skills\anchor_chanlun\vendor' | Out-Null
Copy-Item -Recurse -Force 'C:\Users\shawn\.workbuddy\plugins\marketplaces\my-experts\plugins\chanlun-analyst\skills\chanlun-core' 'D:\workroom\agaistock\src\agaistock\skills\anchor_chanlun\vendor\chanlun-core'
```

确认拷贝完整（`chan_analyze.py` / `chan_multi_level.py` 存在）：

```bash
python -c "from pathlib import Path; p=Path('src/agaistock/skills/anchor_chanlun/vendor/chanlun-core/scripts'); print(sorted(x.name for x in p.glob('*.py')))"
```

- [ ] **Step 2: 写失败的测试**

`tests/test_chanlun_engine.py`：

```python
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from agaistock.skills.anchor_chanlun import engine

REQUESTED_PERIODS: list[str] = []


def fake_kline(symbol, setcode, period, want_num=500):
    """造一段可识别的合成 K 线（升序），并记录被请求的 period。"""
    REQUESTED_PERIODS.append(period)
    rows = []
    for i in range(120):
        day = 1 + (i % 28)
        month = 1 + (i // 28) % 12
        base = 10 + (i % 10) * 0.3
        rows.append({
            "Data": f"2025{month:02d}{day:02d}",
            "Open": f"{base:.2f}", "High": f"{base + 0.5:.2f}",
            "Low": f"{base - 0.5:.2f}", "Close": f"{base + 0.1:.2f}",
            "Volume": 100000.0, "Amount": 1000000.0,
        })
    return {"Rows": rows, "ListHead": {"ItemHead": []}}


class ChanlunEngineTests(unittest.TestCase):
    def setUp(self):
        REQUESTED_PERIODS.clear()

    def test_vendor_scripts_are_present(self):
        scripts = engine.vendor_root() / "scripts"
        self.assertTrue((scripts / "chan_analyze.py").is_file())
        self.assertTrue((scripts / "chan_multi_level.py").is_file())

    def test_levels_map_to_tdx_periods(self):
        self.assertEqual(engine.LEVELS["week"], "5")
        self.assertEqual(engine.LEVELS["day"], "4")
        self.assertEqual(engine.LEVELS["m30"], "2")

    def test_build_structure_requests_each_level_with_its_own_period(self):
        with TemporaryDirectory() as tmp:
            engine.build_structure(
                "002378", "章源钨业", "0", Path(tmp), kline_fetcher=fake_kline
            )
        # 级别→period 的映射必须真的用到，不能只看 LEVELS 常量
        self.assertEqual(REQUESTED_PERIODS, ["5", "4", "2"])

    def test_build_structure_produces_multi_level_payload(self):
        with TemporaryDirectory() as tmp:
            work = Path(tmp)
            structure = engine.build_structure(
                "002378", "章源钨业", "0", work, kline_fetcher=fake_kline
            )
            self.assertIn("levels", structure)
            self.assertIn("resonance", structure)
            self.assertIn("caveats", structure)
            self.assertIn("day", structure["levels"])

    def test_build_structure_writes_analysis_files(self):
        with TemporaryDirectory() as tmp:
            work = Path(tmp)
            engine.build_structure("002378", "章源钨业", "0", work, kline_fetcher=fake_kline)
            self.assertTrue((work / "chan_multi_level.json").is_file())
            self.assertTrue((work / "chan_analysis_day.json").is_file())

    def test_load_analysis_reads_the_level_analysis_file(self):
        with TemporaryDirectory() as tmp:
            work = Path(tmp)
            engine.build_structure("002378", "章源钨业", "0", work, kline_fetcher=fake_kline)
            analysis = engine.load_analysis(work, "day")
            self.assertEqual(analysis["level"], "day")
            self.assertIn("summary", analysis)

    def test_load_analysis_raises_when_file_missing(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                engine.load_analysis(Path(tmp), "day")

    def test_run_script_failure_carries_the_upstream_reason(self):
        # 上游脚本只用 print() 报原因（不写 stderr），所以失败消息必须带 stdout，
        # 否则调用方只看到一个光秃秃的 exit code。
        with TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError) as ctx:
                engine._run_script("chan_analyze.py", Path(tmp), ["--level", "day"])
        # 上游 vendor 已固定版本，这条断言锁住它的报错文案
        self.assertIn("未找到 K 线文件", str(ctx.exception))

    def test_run_script_timeout_is_reported_as_runtime_error(self):
        # 超时必须转成 RuntimeError：脚本执行失败在本模块统一为 RuntimeError，
        # 调用方不必知道 subprocess.TimeoutExpired 的存在。
        with mock.patch.object(
            engine.subprocess,
            "run",
            side_effect=engine.subprocess.TimeoutExpired(
                cmd="chan_analyze.py", timeout=engine.SCRIPT_TIMEOUT
            ),
        ):
            with TemporaryDirectory() as tmp:
                with self.assertRaises(RuntimeError) as ctx:
                    engine._run_script("chan_analyze.py", Path(tmp), ["--level", "day"])
        self.assertIn("超时", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 运行测试确认失败**

```bash
python -m unittest tests.test_chanlun_engine -v
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'agaistock.skills'`

- [ ] **Step 4: 实现 engine.py**

```python
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
# 上游脚本单次分析的上限（连接器调用本身是 180s，这里留更宽的余量）
SCRIPT_TIMEOUT = 300


def vendor_root() -> Path:
    """上游 chanlun-core 的根目录。"""
    return Path(__file__).resolve().parent / "vendor" / "chanlun-core"


def _run_script(script: str, work_dir: Path, extra: list[str]) -> None:
    try:
        result = subprocess.run(
            [sys.executable, str(vendor_root() / "scripts" / script), str(work_dir), *extra],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(work_dir),
            timeout=SCRIPT_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        # 脚本执行失败统一为 RuntimeError。**注意**：engine 并不是「只抛 RuntimeError」——
        # json.JSONDecodeError / OSError 仍可能逃逸，所以隔离必须由 `except Exception` 兜住
        # （Task 4 run_one 就是这么做的）；Task 10 若要自行捕获，也只能用 except Exception。
        raise RuntimeError(f"{script} 执行超时(>{SCRIPT_TIMEOUT}s)") from exc
    if result.returncode != 0:
        # 上游脚本只用 print() 报告原因，**不写 stderr** —— 只看 stderr 会得到空消息。
        detail = ((result.stdout or "") + (result.stderr or "")).strip()
        raise RuntimeError(
            f"{script} 执行失败(exit={result.returncode}): {detail[-800:]}"
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
```

同时创建空文件 `src/agaistock/skills/__init__.py` 与 `src/agaistock/skills/anchor_chanlun/__init__.py`。

- [ ] **Step 5: 运行测试确认通过**

```bash
python -m unittest tests.test_chanlun_engine -v
```

Expected: 9 tests PASS

- [ ] **Step 6: 真实数据验证（关键一步）**

```bash
python -c "
from pathlib import Path
from tempfile import TemporaryDirectory
from agaistock.skills.anchor_chanlun import engine
with TemporaryDirectory() as t:
    s = engine.build_structure('002378','章源钨业','0', Path(t))
    print('levels:', list(s['levels'].keys()))
    print('day bias:', s['levels']['day'].get('bias'))
    print('day signal:', s['levels']['day'].get('signal'))
    print('resonance:', s.get('resonance'))
"
```

Expected: 打印出 day 级别的 bias / signal 与共振档位。

- [ ] **Step 7: Commit**

```bash
git add src/agaistock/skills tests/test_chanlun_engine.py
git commit -m "feat: vendor chanlun core and three-level structure orchestration"
```

> 上游脚本的 CLI 契约已核对（控制器实测 `chanlun-core/scripts/`）：
> `chan_analyze.py <workdir> --level <week|day|m30>` 读 `kline_<level>.json`、写 `chan_analysis_<level>.json`；
> `chan_multi_level.py <workdir> --symbol X --name Y` 读三个 `chan_analysis_*.json`、写 `chan_multi_level.json`。
> 两个脚本都会 `os.chdir(workdir)`，所以必须传 workdir **且** `cwd=work_dir`。
> 上游 `LEVEL_META` 的键就是 `week` / `day` / `m30`，与本任务的 `LEVELS` / `LEVEL_ORDER` 一致。
> 缠论上游脚本**只读不改**：拷进来之后不要改其中任何一行。

---

### Task 8: 规则层与信号生成（纪律 → findings / 证伪位 / 观察期档位）

**Files:**
- Create: `src/agaistock/skills/anchor_chanlun/rules.py`, `src/agaistock/skills/anchor_chanlun/signals.py`
- Create: `tests/test_chanlun_rules.py`

**Interfaces:**
- Consumes: `ReviewVerdict` / `Finding` / `ProposedInvalidation` / `HorizonHint`（Task 3）、`build_structure` 的返回（Task 7）
- Produces:
  - `rules.evaluate(observation: dict, structure: dict, last_close: float) -> tuple[list[Finding], list[str]]`
    返回 `(findings, caveats)`。**纯函数**，不触网、不读盘。
    **只要产出 findings，就一定同时产出至少一条 caveat**（含常驻的结构性限制声明）——
    契约把「有发现却无限制声明」判为非法结论，`engine.run_one` 会把这类结论整条丢弃。
    **价格空间**：`last_close` 与结构里的中枢上下沿（`ZD` / `ZG`）必须**在同一个价格空间**。
    生产环境两者都是**后复权**（Global Constraint 16/18）。
    本任务测试里用的 fixture 数字（`last_close 15.54`、中枢 `22.39~29.04`）是**前复权口径的示例值**，
    只用于验证规则逻辑，**不是**真实后复权数值。
  - `signals.build_invalidation(structure: dict, last_close: float) -> list[ProposedInvalidation]`
    从中枢上下沿生成证伪位（`跌破 ZD`）与确认位（`站上 ZG`）。
    **不按 `dist_pct` 的远近过滤**：远在 +44% 的中枢下沿同样是有效失效位；
    「邻近带」只用于 `rules.py` 的 `CHAN_NEARBY_SUPPLY_BAND` 规则。
    `last_close <= 0` 表示**现价未知**（取不到可比的现价）——此时措辞必须是中性的
    「现价未知，跌破 ZD 即视为判断错误」，**不得**说成「跌破下沿属于已发生的事实」。
  - `signals.build_horizon_hint(observation: dict, structure: dict, findings: list[Finding], last_close: float = 0.0) -> HorizonHint`
  - 规则常量：`rules.RULE_DELTAS`（code → delta 的映射表，便于集中调参与锁定语义）

- [ ] **Step 1: 写失败的测试**

`tests/test_chanlun_rules.py`：

```python
import unittest

from agaistock.skills.anchor_chanlun import rules, signals


def structure(**overrides):
    base = {
        "levels": {
            "week": {"bias": "up", "trend_direction": "up", "signal": "无明确买卖点",
                     "bias_zh": "偏强", "signal_detail": {"type": "无明确买卖点", "basis": "结构不明确"},
                     "window_verdict": "结构充分", "nearby_pivots": [],
                     "recent_divergence": None, "divergence_hint": None,
                     "may_be_partial": False, "last_close": 15.54},
            "day": {"bias": "down", "trend_direction": "down", "signal": "中枢下方 · 底背驰预警",
                    "bias_zh": "偏弱", "signal_detail": {"type": "中枢下方 · 底背驰预警", "basis": "价格仍在中枢之下"},
                    "window_verdict": "结构充分", "nearby_pivots": [],
                    "recent_divergence": None, "divergence_hint": None,
                    "may_be_partial": False, "last_close": 15.54},
            "m30": {"bias": "range", "trend_direction": "range", "signal": "无明确买卖点",
                    "bias_zh": "震荡", "signal_detail": {"type": "无明确买卖点", "basis": "结构不明确"},
                    "window_verdict": "结构充分", "nearby_pivots": [],
                    "recent_divergence": None, "divergence_hint": None,
                    "may_be_partial": False, "last_close": 15.54},
        },
        "resonance": {"grade": "C", "level": "级别交错", "detail": "…",
                       "same_direction": False, "conflict_level": "mixed"},
        "interval_nesting": {"verdict": "unconfirmed", "reason": "次级别尚无背驰"},
        "window_alignment": {"density_balance": "balanced", "over_wide_levels": []},
        "key_levels": {"bands": []},
        "caveats": [],
    }
    base.update(overrides)
    return base


BULLISH = {"direction": "bullish", "thesis": "还能拿半年", "confidence": 0.72}


class RulesTests(unittest.TestCase):
    def test_higher_level_denial_when_week_is_down_and_user_is_bullish(self):
        st = structure()
        st["levels"]["week"]["bias"] = "down"
        findings, _ = rules.evaluate(BULLISH, st, 15.54)
        codes = [f.code for f in findings]
        self.assertIn("CHAN_HIGHER_LEVEL_DENIES", codes)

    def test_no_higher_level_denial_when_week_is_up(self):
        findings, _ = rules.evaluate(BULLISH, structure(), 15.54)
        self.assertNotIn("CHAN_HIGHER_LEVEL_DENIES", [f.code for f in findings])

    def test_direction_conflict_against_day_signal(self):
        st = structure()
        st["levels"]["day"]["signal"] = "中枢上方 · 顶背驰预警"
        findings, _ = rules.evaluate(BULLISH, st, 15.54)
        codes = [f.code for f in findings]
        self.assertIn("CHAN_DIRECTION_CONFLICT", codes)

    def test_position_vs_trend_mismatch_is_info_only(self):
        st = structure()
        st["levels"]["week"]["bias"] = "up"
        st["levels"]["week"]["trend_direction"] = "down"
        findings, caveats = rules.evaluate(BULLISH, st, 15.54)
        matching = [f for f in findings if f.code == "CHAN_POSITION_VS_TREND"]
        self.assertTrue(matching)
        self.assertEqual(matching[0].delta, 0)
        self.assertTrue(any("位置" in c for c in caveats))

    def test_position_vs_trend_mismatch_is_detected_on_m30_level(self):
        st = structure()
        st["levels"]["m30"]["bias"] = "up"
        st["levels"]["m30"]["trend_direction"] = "down"
        findings, _ = rules.evaluate(BULLISH, st, 15.54)
        matching = [f for f in findings if f.code == "CHAN_POSITION_VS_TREND"]
        self.assertTrue(matching)
        self.assertEqual(matching[0].delta, 0)
        self.assertTrue(any("chan.levels.m30.bias" in f.evidence_ref for f in matching))

    def test_evaluate_always_returns_a_caveat_when_there_are_findings(self):
        findings, caveats = rules.evaluate(BULLISH, structure(), 15.54)
        self.assertTrue(findings)
        self.assertTrue(caveats)

    def test_every_finding_has_dimension_and_nonzero_or_zero_delta(self):
        st = structure()
        st["levels"]["week"]["bias"] = "down"
        findings, _ = rules.evaluate(BULLISH, st, 15.54)
        self.assertTrue(findings)
        for f in findings:
            self.assertIn(f.dimension, ("事实锚定", "证伪条件", "逻辑链条", "位置与时机", "一致性"))
            self.assertIsInstance(f.delta, int)

    def test_caveats_mention_divergence_must_be_rechecked(self):
        st = structure()
        st["levels"]["day"]["recent_divergence"] = {"active": True, "kind": "bottom"}
        _, caveats = rules.evaluate(BULLISH, st, 15.54)
        self.assertTrue(any("active" in c for c in caveats))

    def test_nesting_unconfirmed_produces_finding(self):
        findings, _ = rules.evaluate(BULLISH, structure(), 15.54)
        self.assertIn("CHAN_NESTING_UNCONFIRMED", [f.code for f in findings])

    def test_no_partial_caveat_when_all_levels_closed(self):
        _, caveats = rules.evaluate(BULLISH, structure(), 15.54)
        self.assertFalse(any("未收盘" in c for c in caveats))

    def test_partial_caveat_when_a_level_is_still_open(self):
        st = structure()
        st["levels"]["day"]["may_be_partial"] = True
        _, caveats = rules.evaluate(BULLISH, st, 15.54)
        self.assertTrue(any("未收盘" in c for c in caveats))


class SignalsTests(unittest.TestCase):
    def test_build_invalidation_uses_pivot_zd(self):
        st = structure()
        st["levels"]["day"]["nearby_pivots"] = [
            {"from": "2026-02-05", "to": "2026-09-22", "ZD": 22.39, "ZG": 29.04,
             "role": "recent", "dist_pct": 44.08}
        ]
        result = signals.build_invalidation(st, 15.54)
        descs = [p.desc for p in result]
        self.assertTrue(any("22.39" in d for d in descs))

    def test_build_invalidation_uses_support_band_below_price(self):
        st = structure()
        st["levels"]["day"]["nearby_pivots"] = [
            {"from": "2025-08-04", "to": "2026-02-05", "ZD": 11.84, "ZG": 14.05,
             "role": "support", "dist_pct": -9.59}
        ]
        result = signals.build_invalidation(st, 15.54)
        self.assertTrue(any(p.comparator == "below" for p in result))

    def test_build_invalidation_emits_below_level_when_price_is_inside_band(self):
        st = structure()
        st["levels"]["day"]["nearby_pivots"] = [
            {"from": "2025-08-04", "to": "2026-02-05", "ZD": 11.84, "ZG": 14.05,
             "role": "current", "dist_pct": -9.59}
        ]
        result = signals.build_invalidation(st, 13.0)
        below = [p for p in result if p.comparator == "below"]
        self.assertTrue(below)
        self.assertTrue(any("11.84" in p.desc for p in below))

    def test_build_invalidation_keeps_levels_far_below_price(self):
        # 证伪位不按「距现价远近」过滤：远在脚下的中枢下沿同样是有效的失效位。
        st = structure()
        st["levels"]["day"]["nearby_pivots"] = [
            {"from": "2023-01-04", "to": "2023-05-04", "ZD": 8.0, "ZG": 9.0,
             "role": "support", "dist_pct": -42.0}
        ]
        result = signals.build_invalidation(st, 15.54)
        self.assertTrue(any("8.0" in p.desc for p in result))

    def test_build_horizon_hint_takes_most_conservative(self):
        st = structure()
        st["levels"]["day"]["signal"] = "中枢上方 · 顶背驰预警"
        hint = signals.build_horizon_hint(BULLISH, st, [], last_close=15.54)
        self.assertEqual(hint.tier, "short")

    def test_build_horizon_hint_is_event_when_trigger_present(self):
        obs = dict(BULLISH)
        obs["trigger"] = "2026-12-01 产量公告"
        hint = signals.build_horizon_hint(obs, structure(), [], last_close=15.54)
        self.assertIn(hint.tier, ("event", "short"))

    def test_build_horizon_hint_checks_use_real_last_close(self):
        st = structure()
        st["levels"]["day"]["nearby_pivots"] = [
            {"from": "2026-02-05", "to": "2026-09-22", "ZD": 22.39, "ZG": 29.04,
             "role": "recent", "dist_pct": 44.08}
        ]
        hint = signals.build_horizon_hint(BULLISH, st, [], last_close=15.54)
        self.assertTrue(hint.checks)

    def test_build_invalidation_with_unknown_last_close_does_not_claim_it_already_broke(self):
        # last_close <= 0 = 现价未知。此时不能说「跌破下沿属于已发生的事实」。
        st = structure()
        st["levels"]["day"]["nearby_pivots"] = [
            {"from": "2026-02-05", "to": "2026-09-22", "ZD": 22.39, "ZG": 29.04,
             "role": "recent", "dist_pct": 44.08}
        ]
        items = signals.build_invalidation(st, 0.0)
        self.assertTrue(items)
        for item in items:
            self.assertNotIn("已发生的事实", item.rationale)
            if item.comparator == "below":
                self.assertIn("现价未知", item.rationale)

    def test_structural_falsification_findings_land_on_the_falsification_dimension(self):
        # 设计文档 §5.1 / 主规格 §5.3：anchor-chanlun 要同时贡献「证伪条件」与
        # 「位置与时机」两个维度。若全部发现都落在位置与时机，证伪条件（权重 25%）
        # 会恒为 no_reviewer 被剔除，总分实际只除以 15% 的权重。
        st = structure()
        st["levels"]["day"]["nearby_pivots"] = [
            {"from": "2026-02-05", "to": "2026-09-22", "ZD": 22.39, "ZG": 29.04,
             "role": "recent", "dist_pct": 44.08}
        ]
        findings, _ = rules.evaluate(BULLISH, st, 15.54)
        by_code = {f.code: f for f in findings}
        # 中枢距现价远 → 结构位证伪条件不可靠 → 归「证伪条件」
        self.assertEqual(by_code["CHAN_PIVOT_FAR_FROM_PRICE"].dimension, "证伪条件")
        # 现价在中枢内部 → 说清了失效线在哪 → 也归「证伪条件」
        st2 = structure()
        st2["levels"]["day"]["nearby_pivots"] = [
            {"from": "2025-08-04", "to": "2026-02-05", "ZD": 11.84, "ZG": 14.05,
             "role": "current", "dist_pct": -9.59}
        ]
        findings2, _ = rules.evaluate(BULLISH, st2, 13.0)
        by_code2 = {f.code: f for f in findings2}
        self.assertEqual(by_code2["CHAN_PRICE_INSIDE_PIVOT"].dimension, "证伪条件")

    def test_position_findings_stay_on_the_position_dimension(self):
        # 「位置与时机」维度的贡献不能被上面那条改动挤掉。
        # 这里逐条核对**所有会被观察到的规则码**：把一条位置类规则挪到证伪维度，
        # 会把 15% 的位置维度悄悄挪进 25% 的证伪维度（finding A 的反向风险），
        # 而 delta 最大的 CHAN_DIRECTION_CONFLICT（−18）最容易被误改。
        falsification_codes = {"CHAN_PRICE_INSIDE_PIVOT", "CHAN_PIVOT_FAR_FROM_PRICE"}
        seen: dict[str, str] = {}

        def collect(observation, st, last_close):
            findings, _ = rules.evaluate(observation, st, last_close)
            for f in findings:
                seen.setdefault(f.code, f.dimension)

        # 场景 1：看多 + 周线向下 + 日线顶背驰
        # → 高一级否决 / 仓位上限 / 顶背驰优先 / 方向冲突 / 中枢离现价远
        st = structure()
        st["levels"]["week"]["bias"] = "down"
        st["levels"]["day"]["signal"] = "中枢上方 · 顶背驰预警"
        st["levels"]["day"]["nearby_pivots"] = [
            {"from": "2023-01-04", "to": "2023-05-04", "ZD": 8.0, "ZG": 9.0,
             "role": "support", "dist_pct": -42.0},
            {"from": "2026-02-05", "to": "2026-09-22", "ZD": 22.39, "ZG": 29.04,
             "role": "recent", "dist_pct": 5.0},
        ]
        collect(BULLISH, st, 13.0)

        # 场景 2：看空 + 日线底背驰 + 周线无背书 + 窗口偏薄 + 现价在中枢内部
        # → 次买点无背书 / 窗口偏薄 / 位置≠趋势 / 现价在中枢内部
        st2 = structure()
        st2["levels"]["day"]["signal"] = "中枢下方 · 底背驰预警"
        st2["levels"]["week"]["recent_divergence"] = None
        st2["levels"]["day"]["window_verdict"] = "样本偏薄"
        st2["levels"]["m30"]["nearby_pivots"] = [
            {"from": "2025-08-04", "to": "2026-02-05", "ZD": 11.84, "ZG": 14.05,
             "role": "current", "dist_pct": -9.59},
        ]
        collect({"direction": "bearish", "thesis": "要跌", "confidence": 0.6}, st2, 13.0)

        # 证伪维度上只允许出现那两条
        for code, dimension in seen.items():
            if dimension == "证伪条件":
                self.assertIn(code, falsification_codes)
        # 其余规则码一律落在位置维度
        for code, dimension in seen.items():
            if code not in falsification_codes:
                self.assertEqual(dimension, "位置与时机")
        # 两条证伪类规则确实都被观察到了 —— 否则上面的循环是空的，等于没测
        self.assertTrue(falsification_codes.issubset(set(seen)))
        # 至少要覆盖到 delta 最重的那几条位置类规则，否则这个测试保护不到重点
        self.assertIn("CHAN_DIRECTION_CONFLICT", seen)
        self.assertIn("CHAN_HIGHER_LEVEL_DENIES", seen)
        self.assertIn("CHAN_TOP_DIVERGENCE_OVERRIDES", seen)

    def test_horizon_hint_is_capped_by_its_own_findings(self):
        # 同一份结论不能自相矛盾：finding 说「把观察期放在短线档」，
        # horizon_hint 就不能给 long。
        st = structure()
        st["levels"]["week"]["bias"] = "up"
        st["levels"]["week"]["recent_divergence"] = None
        st["levels"]["day"]["signal"] = "中枢上方 · 底背驰预警"
        findings, _ = rules.evaluate(BULLISH, st, 15.54)
        codes = [f.code for f in findings]
        self.assertIn("CHAN_SECOND_BUY_NO_BACKING", codes)
        hint = signals.build_horizon_hint(BULLISH, st, findings, last_close=15.54)
        self.assertEqual(hint.tier, "short")
        self.assertIn("降为 short", hint.rationale)

    def test_horizon_hint_keeps_long_tier_when_no_cap_applies(self):
        # 没有降档约束时，档位逻辑保持原样
        st = structure()
        st["levels"]["week"]["bias"] = "up"
        st["levels"]["week"]["recent_divergence"] = {"active": True, "kind": "bottom"}
        st["levels"]["day"]["signal"] = "中枢上方 · 底背驰预警"
        hint = signals.build_horizon_hint(BULLISH, st, [], last_close=15.54)
        self.assertEqual(hint.tier, "long")

    def test_horizon_hint_cap_survives_the_trigger_override(self):
        # 顺序要求：档位上限必须在 trigger 覆盖**之后**应用。
        # 否则「有催化剂 + 有短线级发现」会被 event 静默盖掉 ——
        # finding 说「把观察期放在短线档」，horizon_hint 却给 event。
        st = structure()
        st["levels"]["week"]["bias"] = "up"
        st["levels"]["week"]["recent_divergence"] = None
        st["levels"]["day"]["signal"] = "中枢下方 · 底背驰预警"
        obs = dict(BULLISH)
        obs["trigger"] = "2026-12-01 产量公告"
        findings, _ = rules.evaluate(obs, st, 15.54)
        self.assertIn("CHAN_SECOND_BUY_NO_BACKING", [f.code for f in findings])
        hint = signals.build_horizon_hint(obs, st, findings, last_close=15.54)
        self.assertEqual(hint.tier, "short")
        self.assertIn("降为 short", hint.rationale)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m unittest tests.test_chanlun_rules -v
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'agaistock.skills.anchor_chanlun.rules'`

- [ ] **Step 3: 实现 rules.py**

```python
"""缠论纪律 → findings / caveats。

纯函数：输入观察卡与缠论结构，输出结构化发现与限制声明。不触网、不读盘。
纪律来源：上游 chanlun-core/SKILL.md 的 25 条判读纪律。
"""
from __future__ import annotations

from typing import Any

from ...reviewers.contract import Finding

DIMENSION_POSITION = "位置与时机"
DIMENSION_FALSIFICATION = "证伪条件"

RULE_DELTAS: dict[str, int] = {
    "CHAN_HIGHER_LEVEL_DENIES": -15,
    "CHAN_POSITION_SIZE_CAP": -5,
    "CHAN_TOP_DIVERGENCE_OVERRIDES": -12,
    "CHAN_DIRECTION_CONFLICT": -18,
    "CHAN_POSITION_VS_TREND": 0,
    "CHAN_PIVOT_FAR_FROM_PRICE": -3,
    "CHAN_NEARBY_SUPPLY_BAND": -4,
    "CHAN_NESTING_UNCONFIRMED": -6,
    "CHAN_WINDOW_THIN": -2,
    "CHAN_PRICE_INSIDE_PIVOT": -5,
    "CHAN_SECOND_BUY_NO_BACKING": -6,
}

FAR_FROM_PRICE_PCT = 15.0
NEAR_BAND_PCT = 10.0

LEVEL_LABELS = {"week": "周线", "day": "日线", "m30": "30 分钟"}

# 常驻限制声明：只要给出了发现，就必须同时给出限制。
# 契约（Task 3 的 validate_verdict）把「有发现却没有限制声明」判为非法结论，
# engine.run_one 会把这类结论整条丢弃 —— 所以这里必须自己保证不为空。
STANDING_CAVEAT = (
    "本结论基于缠论结构识别：中枢、分笔与背驰窗口由上游脚本按固定规则判定，"
    "只对本次取数窗口内的结构负责；结构识别本身有窗口与样本限制，不构成投资建议。"
)


def _level(structure: dict[str, Any], name: str) -> dict[str, Any]:
    return (structure.get("levels") or {}).get(name) or {}


def _finding(code: str, severity: str, claim: str, why: str,
             evidence_ref: list[str], suggested_fix: str,
             dimension: str = DIMENSION_POSITION) -> Finding:
    return Finding(
        code=code,
        severity=severity,
        dimension=dimension,
        delta=RULE_DELTAS.get(code, 0),
        claim=claim,
        why=why,
        evidence_ref=evidence_ref,
        suggested_fix=suggested_fix,
    )


def evaluate(observation: dict, structure: dict, last_close: float) -> tuple[list[Finding], list[str]]:
    """返回 (findings, caveats)。"""
    findings: list[Finding] = []
    caveats: list[str] = []
    direction = (observation.get("direction") or "").lower()

    week = _level(structure, "week")
    day = _level(structure, "day")
    m30 = _level(structure, "m30")

    week_bias = week.get("bias")
    day_signal = day.get("signal") or ""

    # 纪律二：小级别服从大级别
    if week_bias == "down" and direction == "bullish":
        findings.append(_finding(
            "CHAN_HIGHER_LEVEL_DENIES", "high",
            f"周线当前强弱为 down，而你的主张是看多",
            "按纪律二，小级别服从大级别；周线未给出向上许可时，日线级别的看多只能定性为反弹。",
            ["chan.levels.week.bias"],
            "把主张降级为『反弹参与』，或等待周线底背驰背书后再提高仓位",
        ))
        findings.append(_finding(
            "CHAN_POSITION_SIZE_CAP", "info",
            "周线未许可向上，仓位应受限",
            "按纪律二：周线向下时只做短线轻仓或空仓。",
            ["chan.levels.week.bias"],
            "若仍要参与，按轻仓处理，并把观察期放在短线档",
        ))

    # 纪律四/八：顶背驰优先
    if "顶背驰" in day_signal:
        findings.append(_finding(
            "CHAN_TOP_DIVERGENCE_OVERRIDES", "critical",
            f"日线出现顶背驰预警（{day_signal}）",
            "顶背驰是大级别预警，不得被更小级别的买点推翻。",
            ["chan.levels.day.signal"],
            "先按减仓/观望处理，等日线级别的新结构确认",
        ))

    # 纪律二/二十一：方向冲突
    if direction == "bullish" and ("顶背驰" in day_signal or "卖点" in day_signal):
        findings.append(_finding(
            "CHAN_DIRECTION_CONFLICT", "critical",
            f"你的方向是看多，但日线买卖点判定为「{day_signal}」",
            "结构判定与主张方向相反，这是位置与时机维度上最直接的冲突。",
            ["chan.levels.day.signal"],
            "重新检查主张所依赖的依据是否已被价格结构否定",
        ))
    if direction == "bearish" and "底背驰" in day_signal:
        findings.append(_finding(
            "CHAN_DIRECTION_CONFLICT", "critical",
            f"你的方向是看空，但日线买卖点判定为「{day_signal}」",
            "结构判定与主张方向相反。",
            ["chan.levels.day.signal"],
            "重新检查主张所依赖的依据是否已被价格结构否定",
        ))

    # 纪律二十一：位置读数 ≠ 趋势性质
    # 三个级别都要看：位置/趋势背离在任何级别上都成立，只看日线会漏掉周线与 30 分钟的背离。
    for level_name, level in (("week", week), ("day", day), ("m30", m30)):
        bias = level.get("bias")
        trend = level.get("trend_direction")
        if not bias or not trend or bias == trend:
            continue
        label = LEVEL_LABELS[level_name]
        caveats.append(
            f"{label}位置读数为 {bias}，但趋势性质为 {trend}；"
            "位置读数只代表价格相对最近中枢的位置，不代表趋势已经改变"
        )
        findings.append(_finding(
            "CHAN_POSITION_VS_TREND", "info",
            f"{label}位置 {bias} 与趋势性质 {trend} 不一致",
            "价格刚站上或跌破中枢沿会翻转位置读数，但趋势性质往往未变。",
            [f"chan.levels.{level_name}.bias", f"chan.levels.{level_name}.trend_direction"],
            "读结论时以趋势性质为准，位置读数仅作参考",
        ))

    # 纪律二十二：中枢不贴近现价 → 中枢类判据降权
    for level_name, level in (("week", week), ("day", day), ("m30", m30)):
        for pivot in level.get("nearby_pivots") or []:
            dist = pivot.get("dist_pct")
            if isinstance(dist, (int, float)) and abs(dist) > FAR_FROM_PRICE_PCT:
                findings.append(_finding(
                    "CHAN_PIVOT_FAR_FROM_PRICE", "medium",
                    f"{level_name} 最近中枢距现价 {dist:.1f}%，超出 {FAR_FROM_PRICE_PCT}% 阈值",
                    "中枢不贴近现价时，「中枢上方/下方运行」这个标签对当期决策几乎没有参考价值。",
                    [f"chan.levels.{level_name}.nearby_pivots"],
                    "把判断重心转向双底/双顶结构、动能收缩或放大、MACD 交叉与成交量等不依赖中枢的读面",
                    # 归到「证伪条件」维度：本级别中枢上下沿就是结构位证伪条件，
                    # 中枢不贴近现价时这个证伪位不可靠。
                    # 设计文档 §5.1 / 主规格 §5.3 —— anchor-chanlun 要同时贡献
                    # 「证伪条件」与「位置与时机」两个维度，不能只占后者。
                    dimension=DIMENSION_FALSIFICATION,
                ))
                break

    # 纪律二十二 / 十一：旧中枢供给带
    supply_bands = []
    for level_name, level in (("week", week), ("day", day), ("m30", m30)):
        for pivot in level.get("nearby_pivots") or []:
            dist = pivot.get("dist_pct")
            if isinstance(dist, (int, float)) and 0 < dist <= NEAR_BAND_PCT:
                supply_bands.append((level_name, pivot))
    if supply_bands:
        level_name, pivot = supply_bands[0]
        findings.append(_finding(
            "CHAN_NEARBY_SUPPLY_BAND", "medium",
            f"{level_name} 头顶存在距现价 {pivot.get('dist_pct'):.1f}% 的供给带"
            f"（{pivot.get('ZD')} ~ {pivot.get('ZG')}）",
            "脚本只标注最近中枢，更早但仍在起作用的旧中枢常构成关键阻力。",
            [f"chan.levels.{level_name}.nearby_pivots"],
            "把该区间当作上方压力带纳入操作定性",
        ))

    # 纪律十三：区间套未确认
    nesting = structure.get("interval_nesting") or {}
    if nesting.get("verdict") == "unconfirmed":
        findings.append(_finding(
            "CHAN_NESTING_UNCONFIRMED", "medium",
            f"日线→30 分钟区间套未确认（{nesting.get('reason', '未说明')}）",
            "未确认的信号不构成可执行信号，需要追问未确认的具体成因。",
            ["chan.interval_nesting"],
            "确认次级别是否已出现同向背驰，否则把该信号按单级别处理",
        ))

    # 纪律九：区间套方向必须写明
    if nesting.get("verdict") in ("partial", "confirmed"):
        caveats.append(
            f"区间套为 {nesting.get('verdict')}；该结论只描述次级别是否同向印证，"
            "若印证的是顶背驰，含义是向下动能衰减得到印证，不是买入理由"
        )

    # 纪律十二：背驰失效复核
    for level_name, level in (("week", week), ("day", day), ("m30", m30)):
        divergence = level.get("recent_divergence")
        if divergence and divergence.get("active"):
            caveats.append(
                f"{level_name} 的背驰 active 标签仅表示锚点落在背驰窗口内，"
                "不代表背驰仍然成立；须复核价格是否已突破锚点、新一笔动能是否同步放大"
            )
        hint = level.get("divergence_hint")
        if hint:
            caveats.append(
                f"{level_name} 存在背驰迹象（面积比 {hint.get('area_ratio')}），"
                "迹象不能单独作为买卖点依据，但也不能漏掉"
            )

    # 纪律二十四：窗口偏薄
    for level_name, level in (("week", week), ("day", day), ("m30", m30)):
        verdict = level.get("window_verdict")
        if verdict in ("样本偏薄", "窗口偏短", "窗口偏长", "样本过密"):
            findings.append(_finding(
                "CHAN_WINDOW_THIN", "medium",
                f"{level_name} 窗口体检结论为「{verdict}」",
                "窗口结构不充分，依赖该级别中枢的关键价位置信度下降。",
                [f"chan.levels.{level_name}.window_verdict"],
                "该级别的关键价位降级使用，不要作为唯一依据",
            ))

    # 纪律十七：现价落在中枢内部
    for level_name, level in (("day", day), ("m30", m30)):
        for pivot in level.get("nearby_pivots") or []:
            zd = pivot.get("ZD")
            zg = pivot.get("ZG")
            if isinstance(zd, (int, float)) and isinstance(zg, (int, float)) and zd <= last_close <= zg:
                findings.append(_finding(
                    "CHAN_PRICE_INSIDE_PIVOT", "medium",
                    f"现价 {last_close} 落在 {level_name} 中枢 {zd}~{zg} 内部",
                    "现价在中枢内部时，该中枢上下沿就是天然决胜位。",
                    [f"chan.levels.{level_name}.nearby_pivots"],
                    f"以 {zg} 作确认线、{zd} 作失效线",
                    # 归到「证伪条件」维度：这条 finding 说的就是失效线在哪。
                    dimension=DIMENSION_FALSIFICATION,
                ))
                break

    # 纪律二十三：回调不创新低 + 大级别无背书
    if "底背驰" in day_signal and not (week.get("recent_divergence") or {}).get("kind"):
        findings.append(_finding(
            "CHAN_SECOND_BUY_NO_BACKING", "medium",
            "日线出现底背驰迹象，但周线未给出同向背驰背书",
            "按纪律二，没有大级别背书的日线结构只能支撑试探仓。",
            ["chan.levels.day.signal", "chan.levels.week.recent_divergence"],
            "按试探仓对待（不超过三成），并把观察期放在短线档",
        ))

    # 纪律二十五：盘中未收盘 —— 用上游的 may_be_partial 标志，不无条件报警
    # （实测：may_be_partial=false 表示该级别最后一根已收盘；true 才是未收盘）
    partial_levels = [
        name for name, lvl in (("week", week), ("day", day), ("m30", m30))
        if (lvl or {}).get("may_be_partial") is True
    ]
    if partial_levels:
        caveats.append(
            f"{'、'.join(partial_levels)} 的最后一根 K 线尚未收盘，"
            "MACD 柱与 DIF 都会在收盘后变化，结论需收盘后复校"
        )

    # 有发现就必须有限制声明（见 STANDING_CAVEAT 的说明）。
    if findings:
        caveats.append(STANDING_CAVEAT)

    return findings, caveats
```

- [ ] **Step 4: 实现 signals.py**

```python
"""从缠论结构生成建议的证伪条件与观察期档位提示。"""
from __future__ import annotations

from typing import Any

from ...reviewers.contract import Finding, HorizonHint, ProposedInvalidation

TOLERANCE_PCT = 0.5

# 档位的保守程度：允许的观察窗口越短 = 越保守。
# （Task 12 的 resolve_tier 用同一套语义做跨点评师取最保守）
TIER_RANK = {"short": 0, "mid": 1, "event": 1, "long": 2}

# 点评师**自己的发现**对观察期档位构成上限。
# 依据是 rules.py 每条规则的 suggested_fix 里已经写明的处置：
#   「把观察期放在短线档」/「按减仓、观望处理」/「重新检查主张是否已被否定」→ 短线
#   「按单级别处理」/「降级使用」/「不依赖中枢的读面」→ 不超过中期
# 没有这张表时，build_horizon_hint 收了 findings 参数却不用，会出现
# 「finding 说『把观察期放在短线档』，horizon_hint 却给 long」这种自相矛盾的结论。
FINDING_TIER_CAPS = {
    "CHAN_HIGHER_LEVEL_DENIES": "short",
    "CHAN_POSITION_SIZE_CAP": "short",
    "CHAN_TOP_DIVERGENCE_OVERRIDES": "short",
    "CHAN_DIRECTION_CONFLICT": "short",
    "CHAN_SECOND_BUY_NO_BACKING": "short",
    "CHAN_NESTING_UNCONFIRMED": "mid",
    "CHAN_WINDOW_THIN": "mid",
    "CHAN_PIVOT_FAR_FROM_PRICE": "mid",
}


def _cap_from_findings(findings: list[Finding]) -> str | None:
    """由发现推出档位上限（多条发现取最保守的那个）。"""
    cap: str | None = None
    for finding in findings or []:
        limit = FINDING_TIER_CAPS.get(finding.code)
        if limit is None:
            continue
        if cap is None or TIER_RANK[limit] < TIER_RANK[cap]:
            cap = limit
    return cap


def _levels(structure: dict[str, Any]) -> dict[str, Any]:
    return structure.get("levels") or {}


def _position(last_close: float, zd: float, zg: float) -> str:
    """现价相对中枢的位置：above / inside / below / unknown。

    `last_close <= 0` 表示**现价未知**（取不到可比的现价，例如复权因子缺失导致
    无法把实时行情换算到后复权空间）。这时不能假装现价在中枢下方 ——
    那会让文案说出「跌破下沿属于已发生的事实」这种假话。
    """
    if last_close <= 0:
        return "unknown"
    if last_close > zg:
        return "above"
    if last_close >= zd:
        return "inside"
    return "below"


def _below_rationale(level_name: str, position: str, zd: float, zg: float) -> str:
    """跌破中枢下沿的含义随现价位置而变，写清楚才不会被误读。"""
    if position == "unknown":
        return (
            f"现价未知（取不到可比的现价），跌破 {level_name} 中枢下沿 {zd} "
            f"（中枢区间 {zd}~{zg}）即视为判断错误"
        )
    if position == "inside":
        return f"价格跌出 {level_name} 中枢下沿 {zd} 即视为判断错误"
    if position == "above":
        return (
            f"价格已站在 {level_name} 中枢上方，跌破该支撑带下沿 {zd} 即视为判断错误"
            f"（中枢区间 {zd}~{zg}）"
        )
    return (
        f"{level_name} 中枢位于现价上方（{zd}~{zg}），跌破下沿 {zd} 属于已发生的事实，"
        "此处只作结构失效参考，不作为本次的失效判定"
    )


def build_invalidation(structure: dict, last_close: float) -> list[ProposedInvalidation]:
    """从中枢上下沿生成建议的证伪条件与确认位。

    证伪位取中枢下沿 ZD，**不按距现价的远近过滤**：一个远在 +44% 的中枢下沿
    仍然是有效的失效位（跌回去说明结构被证伪）。若用 dist_pct 当门槛，证伪位
    会被全部过滤掉，「建议的证伪条件」与观察期 checks 就永远是空的。
    「邻近带」只用于 rules.py 的 CHAN_NEARBY_SUPPLY_BAND 规则。

    跌破 ZD 在三种位置下都要给出（现价在带下 / 带内 / 带上）：
      - 带内：跌出中枢 → 结构走坏
      - 带上（支撑带在脚下）：跌破支撑带下沿 → 支撑失效
      - 带下（供给带在头顶）：条件已成立，只作结构参考
    """
    result: list[ProposedInvalidation] = []
    for level_name in ("day", "week", "m30"):
        level = _levels(structure).get(level_name) or {}
        for pivot in level.get("nearby_pivots") or []:
            zd = pivot.get("ZD")
            zg = pivot.get("ZG")
            if not isinstance(zd, (int, float)) or not isinstance(zg, (int, float)):
                continue
            if zd <= 0 or zg <= zd:
                continue
            position = _position(last_close, zd, zg)
            result.append(ProposedInvalidation(
                desc=f"跌破 {level_name} 中枢下沿 {zd}",
                source=f"chan.levels.{level_name}.nearby_pivots[].ZD",
                comparator="below",
                tolerance=TOLERANCE_PCT,
                rationale=_below_rationale(level_name, position, zd, zg),
            ))
            if position != "above":
                # 现价已经在上沿之上时，「站上 ZG」已经成立，不再作为待确认条件给出。
                result.append(ProposedInvalidation(
                    desc=f"站上 {level_name} 中枢上沿 {zg}",
                    source=f"chan.levels.{level_name}.nearby_pivots[].ZG",
                    comparator="above",
                    tolerance=TOLERANCE_PCT,
                    rationale=f"价格站上 {level_name} 中枢上沿 {zg} 视为主张被强化",
                ))
    return result


def build_horizon_hint(
    observation: dict,
    structure: dict,
    findings: list[Finding],
    last_close: float = 0.0,
) -> HorizonHint:
    """给出观察期档位上限建议（多家点评师取最保守时由上游聚合）。"""
    day = _levels(structure).get("day") or {}
    week = _levels(structure).get("week") or {}
    day_signal = day.get("signal") or ""
    week_bias = week.get("bias")

    tier = "mid"
    rationale = "结构未给出明确的强弱许可，按中期档处理"

    if week_bias == "up" and ("底背驰" in day_signal or "买点" in day_signal):
        tier = "long"
        rationale = "周线许可向上且日线给出同向信号，支持较长观察期"
    elif "顶背驰" in day_signal or "卖点" in day_signal:
        tier = "short"
        rationale = "日线给出顶背驰/卖点信号，只支持短线验证"
    elif week_bias == "down":
        tier = "short"
        rationale = "周线未许可向上，只支持短线验证"

    if observation.get("trigger"):
        tier = "event"
        rationale = f"存在明确催化剂（{observation.get('trigger')}），按事件驱动锚定"

    # 档位上限：点评师自己的发现不能被自己的观察期建议推翻。
    # （rules.py 的 suggested_fix 常写着「把观察期放在短线档」；若这里仍给 long，
    #   同一份结论里就会自相矛盾。）
    cap = _cap_from_findings(findings)
    if cap is not None and TIER_RANK.get(cap, 99) < TIER_RANK.get(tier, 0):
        rationale = f"{rationale}；受本次发现约束，观察期档位降为 {cap}"
        tier = cap

    # 必须传真实的 last_close —— 用 0.0 会让「现价是否落在中枢内部」的判断失效
    checks = [
        {
            "id": f"c{index + 1}",
            "desc": item.desc,
            "source": item.source,
            "comparator": item.comparator,
            "tolerance": item.tolerance,
        }
        for index, item in enumerate(build_invalidation(structure, last_close))
    ]

    return HorizonHint(tier=tier, rationale=rationale, checks=checks)
```

- [ ] **Step 5: 运行测试确认通过**

```bash
python -m unittest tests.test_chanlun_rules -v
```

Expected: 24 tests PASS（`RulesTests` 12 条 + `SignalsTests` 12 条）

- [ ] **Step 6: Commit**

```bash
git add src/agaistock/skills/anchor_chanlun/rules.py src/agaistock/skills/anchor_chanlun/signals.py tests/test_chanlun_rules.py
git commit -m "feat: chanlun rules layer mapping disciplines to findings and signals"
```

---

### Task 9: 措辞层与 LLM 客户端

**Files:**
- Create: `src/agaistock/llm/__init__.py`, `src/agaistock/llm/client.py`
- Create: `src/agaistock/skills/anchor_chanlun/wording.py`
- Create: `tests/test_llm_client.py`, `tests/test_wording.py`

**Interfaces:**
- Consumes: `Finding`（Task 3）
- Produces:
  - `agaistock.llm.client.LlmClient(base_url: str, api_key: str, model: str, timeout: int = 60)`，方法 `.complete(prompt: str, system: str = "") -> str`。
  - `agaistock.llm.client.from_env() -> LlmClient | None`，读 `AGAISTOCK_LLM_BASE_URL` / `AGAISTOCK_LLM_API_KEY` / `AGAISTOCK_LLM_MODEL`，缺任一返回 None。
  - `agaistock.skills.anchor_chanlun.wording.phrase(findings: list[Finding], observation: dict, llm=None, context: dict | None = None) -> list[Finding]`
    返回**新的 finding 列表**；LLM 不可用时原样返回。
    `context` 可携带缠论结构语境（`narrative` / `resonance` / `framework.discipline` / `signal_detail`），
    让 LLM 点评时有整体参照，而不是逐条孤立改写。
  - `agaistock.skills.anchor_chanlun.wording.PROTECTED = ("code", "severity", "dimension", "delta", "evidence_ref")`
    校验口径：**只校验 LLM 实际返回了的字段**。字段缺失 = LLM 没动它（不算篡改）；
    字段存在但值与原值不同 = 篡改 → 丢弃该条 LLM 输出，保留规则层原文。

- [ ] **Step 1: 写失败的测试**

`tests/test_wording.py`：

```python
import unittest

from agaistock.reviewers.contract import Finding
from agaistock.skills.anchor_chanlun import wording


def finding(**overrides):
    base = dict(
        code="CHAN_DAY_TOP_DIVERGENCE", severity="critical", dimension="位置与时机",
        delta=-12, claim="原始表述", why="原始理由",
        evidence_ref=["chan.levels.day.signal"], suggested_fix="原始建议",
    )
    base.update(overrides)
    return Finding(**base)


class FakeLlm:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def complete(self, prompt, system=""):
        self.calls.append(prompt)
        return self.response


class WordingTests(unittest.TestCase):
    def test_returns_original_when_llm_missing(self):
        original = [finding()]
        result = wording.phrase(original, {"thesis": "t"}, llm=None)
        self.assertEqual(result[0].claim, "原始表述")

    def test_applies_wording_to_claim_only(self):
        llm = FakeLlm('{"items":[{"code":"CHAN_DAY_TOP_DIVERGENCE","claim":"更口语化的表述"}]}')
        result = wording.phrase([finding()], {"thesis": "t"}, llm=llm)
        self.assertEqual(result[0].claim, "更口语化的表述")
        self.assertEqual(result[0].delta, -12)
        self.assertEqual(result[0].severity, "critical")
        self.assertEqual(result[0].dimension, "位置与时机")
        self.assertEqual(result[0].code, "CHAN_DAY_TOP_DIVERGENCE")

    def test_discards_llm_output_that_tampered_protected_fields(self):
        # 同一个 code，但 severity / dimension / delta 被改了 → 整条丢弃，保留规则层原文
        llm = FakeLlm(
            '{"items":[{"code":"CHAN_DAY_TOP_DIVERGENCE","severity":"info",'
            '"dimension":"一致性","delta":99,"claim":"篡改"}]}'
        )
        result = wording.phrase([finding()], {"thesis": "t"}, llm=llm)
        self.assertEqual(result[0].claim, "原始表述")
        self.assertEqual(result[0].delta, -12)
        self.assertEqual(result[0].severity, "critical")
        self.assertEqual(result[0].dimension, "位置与时机")

    def test_survives_llm_exception(self):
        class Boom:
            def complete(self, prompt, system=""):
                raise RuntimeError("挂了")
        result = wording.phrase([finding()], {"thesis": "t"}, llm=Boom())
        self.assertEqual(result[0].claim, "原始表述")

    def test_non_list_evidence_ref_is_treated_as_tampering_not_a_crash(self):
        # LLM 输出是不可信输入：evidence_ref 给成数字时 list(123) 会抛 TypeError，
        # 穿透「任何异常都必须降级」的硬约束 —— 整轮点评会因此变成 status=error，
        # 连规则层的 findings 一起丢掉。必须判为篡改并退回原文。
        llm = FakeLlm(
            '{"items":[{"code":"CHAN_DAY_TOP_DIVERGENCE","evidence_ref":123,"claim":"改写"}]}'
        )
        result = wording.phrase([finding()], {"thesis": "t"}, llm=llm)
        self.assertEqual(result[0].claim, "原始表述")
        self.assertEqual(result[0].evidence_ref, ["chan.levels.day.signal"])

    def test_string_evidence_ref_is_treated_as_tampering(self):
        # list("a") → ['a']。原文的 evidence_ref 必须**恰好是** ['a']，
        # 旧实现才会把字符串误判成「没篡改」而放行 —— 用别的原文（如
        # ["chan.levels.day.signal"]）时 list("a") 跟它本来就不相等，
        # 这条测试在旧实现下也会通过，等于没卡住任何东西。
        llm = FakeLlm(
            '{"items":[{"code":"CHAN_DAY_TOP_DIVERGENCE","evidence_ref":"a","claim":"改写"}]}'
        )
        original = finding(evidence_ref=["a"])
        result = wording.phrase([original], {"thesis": "t"}, llm=llm)
        self.assertEqual(result[0].claim, "原始表述")

    def test_unexpected_shape_in_the_llm_payload_degrades_to_the_original(self):
        # LLM 返回的 items 里混进一个非 dict 的元素时，整个解析段都不能抛异常 ——
        # 措辞层失败必须降级，不能影响判定。
        llm = FakeLlm('{"items":[123, null, "oops"]}')
        result = wording.phrase([finding()], {"thesis": "t"}, llm=llm)
        self.assertEqual(result[0].claim, "原始表述")
        self.assertEqual(result[0].delta, -12)

    def test_unhashable_code_in_the_llm_payload_degrades_to_the_original(self):
        # 解析段真正会崩的输入：item.get("code") 拿到一个 list 时，
        # 拿它当 dict 的键 → TypeError: unhashable type: 'list'。
        # 这一步处理的是不可信外部输入，异常一旦穿透到点评师，
        # 整轮点评会变成 status="error"，连规则层已经算好的 findings 一起丢掉。
        # （上面那条非 dict 元素的用例是回归护栏：旧实现下它就已经通过；
        #   这条才是能证明「解析段兜底」真的生效的探针。）
        llm = FakeLlm('{"items":[{"code":[],"claim":"改写"}]}')
        result = wording.phrase([finding()], {"thesis": "t"}, llm=llm)
        self.assertEqual(result[0].claim, "原始表述")
        self.assertEqual(result[0].delta, -12)

    def test_protected_fields_come_from_the_contract(self):
        # 受保护字段只能有一个来源，否则两处分叉就没人说得清「哪些字段不许 LLM 改」。
        from agaistock.reviewers import contract
        self.assertEqual(tuple(wording.PROTECTED), tuple(contract.PROTECTED_FIELDS))


if __name__ == "__main__":
    unittest.main()
```

`tests/test_llm_client.py`：

```python
import unittest

from agaistock.llm import client


class LlmClientTests(unittest.TestCase):
    def test_from_env_returns_none_when_incomplete(self):
        self.assertIsNone(client.from_env(base_url="", api_key="", model=""))

    def test_extracts_text_from_openai_shape(self):
        payload = {"choices": [{"message": {"content": "你好"}}]}
        self.assertEqual(client.extract_text(payload), "你好")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m unittest tests.test_wording tests.test_llm_client -v
```

Expected: FAIL —— `ModuleNotFoundError`

- [ ] **Step 3: 实现 llm/client.py**

```python
"""OpenAI 兼容的 LLM 客户端（仅标准库）。

密钥只从环境变量读，不入库、不写进配置文件。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


def extract_text(payload: dict) -> str:
    """从 OpenAI 兼容响应中取出文本。"""
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return message.get("content") or ""


class LlmClient:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def complete(self, prompt: str, system: str = "") -> str:
        body = {
            "model": self.model,
            "messages": (
                ([{"role": "system", "content": system}] if system else [])
                + [{"role": "user", "content": prompt}]
            ),
            "temperature": 0.3,
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return extract_text(payload)


def from_env(base_url: str | None = None, api_key: str | None = None,
             model: str | None = None) -> LlmClient | None:
    """从环境变量构造客户端；任一缺失返回 None（调用方走降级）。"""
    base_url = base_url if base_url is not None else os.environ.get("AGAISTOCK_LLM_BASE_URL", "")
    api_key = api_key if api_key is not None else os.environ.get("AGAISTOCK_LLM_API_KEY", "")
    model = model if model is not None else os.environ.get("AGAISTOCK_LLM_MODEL", "")
    if not (base_url and api_key and model):
        return None
    return LlmClient(base_url=base_url, api_key=api_key, model=model)
```

- [ ] **Step 4: 实现 wording.py**

```python
"""LLM 措辞层：只改写 claim 的自然语言表述，不动任何判定字段。

若 LLM 输出篡改了受保护字段（code/severity/dimension/delta/evidence_ref），
**丢弃该条 LLM 输出，保留规则层原文**。
"""
from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any

from ...reviewers.contract import PROTECTED_FIELDS, Finding

# 受保护字段只有一个来源：契约层已经定义了 PROTECTED_FIELDS。
# 这里直接复用，不要各写一份 —— 两处分叉会让「哪些字段不许 LLM 改」变得不可控。
PROTECTED = PROTECTED_FIELDS

SYSTEM_PROMPT = (
    "你是股票复盘助手，负责把结构化发现改写成给投资者看的中文点评。"
    "只允许改写 claim 的表述，使其更口语化、更说明『这说明什么』。"
    "不得修改 code、severity、dimension、delta、evidence_ref，不得改变判定结论，"
    "不得给出投资建议，不得预测点位。只输出 JSON。"
)


def _extract_json(text: str) -> dict | None:
    source = str(text or "").strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", source)
    body = fenced.group(1) if fenced else source
    start = body.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(body)):
        char = body[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(body[start:index + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _matches_protected(original: Finding, item: dict[str, Any]) -> bool:
    """只校验 LLM **实际返回了**的受保护字段。

    字段缺失 = LLM 没有动这个字段（不算篡改）；字段存在但值与原值不同 = 篡改。
    要求五个字段全部出现是错的：正常的措辞回复只带 code + claim，
    会被误判成篡改而整条丢弃。
    """
    for field in PROTECTED:
        if field not in item:
            continue
        current = getattr(original, field)
        proposed = item[field]
        if isinstance(current, list):
            # LLM 返回的必须是列表：
            #   list(123) → TypeError（'int' object is not iterable），会穿透「任何异常都降级」的硬约束；
            #   list("a") → ['a']，与原文 ['a'] 相等 → 字符串会被误判成「没篡改」而放行。
            if not isinstance(proposed, list) or proposed != list(current):
                return False
        elif proposed != current:
            return False
    return True


def phrase(
    findings: list[Finding],
    observation: dict,
    llm=None,
    context: dict | None = None,
) -> list[Finding]:
    """用 LLM 改写 claim；任何异常或篡改都退回规则层原文。

    `context` 可携带缠论结构的整体语境（上游已生成的 narrative / resonance / 纪律），
    让点评有整体参照而不是逐条孤立改写。
    """
    if llm is None or not findings:
        return list(findings)

    prompt = json.dumps(
        {
            "observation": {
                "thesis": observation.get("thesis", ""),
                "direction": observation.get("direction", ""),
                "timeframe": observation.get("timeframe", ""),
            },
            "structure_context": context or {},
            "findings": [
                {
                    "code": f.code,
                    "severity": f.severity,
                    "dimension": f.dimension,
                    "delta": f.delta,
                    "claim": f.claim,
                    "why": f.why,
                    "evidence_ref": list(f.evidence_ref),
                    "suggested_fix": f.suggested_fix,
                }
                for f in findings
            ],
        },
        ensure_ascii=False,
    )

    try:
        raw = llm.complete(prompt, system=SYSTEM_PROMPT)
    except Exception:  # noqa: BLE001 —— 措辞层失败必须降级，不能影响判定
        return list(findings)

    # 从这里开始的每一步都在处理**不可信的外部输入**（LLM 的原始返回）。
    # 任何一处意外都必须降级成规则层原文，不能让异常穿透到点评师 ——
    # 否则整轮点评会变成 status="error"，连规则层已经算好的 findings 一起丢掉。
    try:
        payload = _extract_json(raw)
        if not payload:
            return list(findings)

        items = payload.get("items")
        if not isinstance(items, list):
            return list(findings)

        by_code = {item.get("code"): item for item in items if isinstance(item, dict)}

        result = []
        for finding in findings:
            item = by_code.get(finding.code)
            if not isinstance(item, dict) or not _matches_protected(finding, item):
                result.append(finding)
                continue
            new_claim = str(item.get("claim") or "").strip()
            if not new_claim:
                result.append(finding)
                continue
            result.append(replace(finding, claim=new_claim))
        return result
    except Exception:  # noqa: BLE001 —— 措辞层失败必须降级，不能影响判定
        return list(findings)
```

同时创建空文件 `src/agaistock/llm/__init__.py`。

- [ ] **Step 5: 运行测试确认通过**

```bash
python -m unittest tests.test_wording tests.test_llm_client -v
```

Expected: 12 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/agaistock/llm src/agaistock/skills/anchor_chanlun/wording.py tests/test_wording.py tests/test_llm_client.py
git commit -m "feat: llm wording layer with protected field validation and fallback"
```

---

### Task 10: `anchor-chanlun` 点评师组装

**Files:**
- Create: `src/agaistock/skills/anchor_chanlun/reviewer.py`
- Create: `tests/test_anchor_chanlun_reviewer.py`

**Interfaces:**
- Consumes: `rules.evaluate` / `signals.*`（Task 8）、`wording.phrase`（Task 9）、`build_structure`（Task 7）、`ReviewContext`（Task 3）
- Produces:
  - `agaistock.skills.anchor_chanlun.reviewer.Reviewer` —— 类，含 `id = "anchor-chanlun"`、`version = "0.1.0"`、`review(ctx: ReviewContext) -> ReviewVerdict`。
  - `reviewer.fetch_last_close(symbol: str, setcode: str, structure: dict | None = None) -> float` —— 取现价，**返回后复权空间的价位**。
    优先用结构里的 `levels.day.last_close`，没有才退回实时行情接口；退回时必须用复权因子把现价换算成后复权（Global Constraint 18）。

- [ ] **Step 1: 写失败的测试**

```python
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from agaistock.reviewers.contract import Finding, ReviewContext
from agaistock.skills.anchor_chanlun import reviewer


def make_structure():
    return {
        "levels": {
            "week": {"bias": "down", "trend_direction": "down", "signal": "无明确买卖点",
                     "window_verdict": "结构充分", "nearby_pivots": [], "recent_divergence": None},
            "day": {"bias": "down", "trend_direction": "down", "signal": "中枢下方 · 底背驰预警",
                    "window_verdict": "结构充分", "nearby_pivots": [], "recent_divergence": None},
            "m30": {"bias": "range", "trend_direction": "range", "signal": "无明确买卖点",
                    "window_verdict": "结构充分", "nearby_pivots": [], "recent_divergence": None},
        },
        # 档位字母在 grade 上，level 是中文定性（见 Global Constraint 8）
        "resonance": {"grade": "C", "level": "级别交错"},
        "interval_nesting": {"verdict": "unconfirmed", "reason": "次级别尚无背驰"},
        "window_alignment": {"density_balance": "balanced", "over_wide_levels": []},
        "key_levels": {"bands": []},
        # 上游结构自己的限制声明不能是空的
        "caveats": ["上游结构识别基于固定窗口，样本偏薄时结论需降级使用"],
    }


class ReviewerTests(unittest.TestCase):
    def test_reviewer_id_and_version(self):
        r = reviewer.Reviewer()
        self.assertEqual(r.id, "anchor-chanlun")
        self.assertEqual(r.version, "0.1.0")

    def test_fetch_last_close_reads_the_price_from_the_quotes_payload(self):
        # 实测（2026-11-24）：tdx_quotes 的现价在 **HQInfo** 里，
        # 顶层根本没有 AttachInfo（那是 K 线载荷 tdx_kline 的元数据）。
        # 读错字段 → 回退路径永远静默返回「现价未知」。
        payload = {"HQInfo": {"Now": 15.54, "Close": 15.59}}
        with mock.patch.object(reviewer.tdx, "fetch_quotes", return_value=payload), \
             mock.patch.object(
                 reviewer, "_latest_factor_row",
                 return_value={"factor": 2.0, "constant": 1.0},
             ):
            value = reviewer.fetch_last_close("002378", "0")
        # 现价 15.54 → 后复权 = 15.54 × 2.0 + 1.0
        self.assertAlmostEqual(value, 32.08)

    def test_fetch_last_close_prefers_the_structure_last_close(self):
        # 结构里的 last_close 已在后复权空间，不该再调行情接口。
        structure = {"levels": {"day": {"last_close": 42.66}}}
        with mock.patch.object(reviewer.tdx, "fetch_quotes") as quotes:
            value = reviewer.fetch_last_close("002378", "0", structure)
        self.assertAlmostEqual(value, 42.66)
        quotes.assert_not_called()

    def test_fetch_last_close_returns_unknown_without_an_adjustment_factor(self):
        # 换不到因子行就**不能**返回现价 —— 它不在后复权空间，
        # 拿它去和后复权的中枢上下沿比会得出错误结论。
        payload = {"HQInfo": {"Now": 15.54}}
        with mock.patch.object(reviewer.tdx, "fetch_quotes", return_value=payload), \
             mock.patch.object(reviewer, "_latest_factor_row", return_value=None):
            self.assertEqual(reviewer.fetch_last_close("002378", "0"), 0.0)

    def test_fetch_last_close_survives_an_unexpected_payload_shape(self):
        # 行情载荷的形态不该由我们假设：容器不是 dict 时不能抛 AttributeError。
        for payload in ({}, {"HQInfo": None}, {"AttachInfo": []}, {"HQInfo": {"Now": "x"}}):
            with mock.patch.object(reviewer.tdx, "fetch_quotes", return_value=payload), \
                 mock.patch.object(
                     reviewer, "_latest_factor_row",
                     return_value={"factor": 1.0, "constant": 0.0},
                 ):
                self.assertEqual(reviewer.fetch_last_close("002378", "0"), 0.0)

    def test_review_returns_valid_verdict(self):
        structure = make_structure()
        with TemporaryDirectory() as tmp:
            ctx = ReviewContext(
                observation={"symbol": "002378", "direction": "bullish", "thesis": "还能拿半年",
                             "timeframe": "半年", "trigger": ""},
                symbol="002378", name="章源钨业", now="2026-11-24T07:30:00Z",
                data_dir=Path(tmp), llm=None,
            )
            with mock.patch.object(reviewer, "build_structure", return_value=structure), \
                 mock.patch.object(reviewer, "fetch_last_close", return_value=15.54):
                verdict = reviewer.Reviewer().review(ctx)

        self.assertEqual(verdict.reviewer_id, "anchor-chanlun")
        self.assertEqual(verdict.status, "ok")
        self.assertTrue(verdict.findings)
        # 有发现就必须有限制声明：否则契约校验不通过，engine.run_one 会把整条结论丢掉
        self.assertTrue(verdict.caveats)
        self.assertIsNotNone(verdict.horizon_hint)
        self.assertTrue(verdict.data_refs)

    def test_review_folds_contract_validation_errors_into_caveats(self):
        bad_finding = Finding(
            code="CHAN_X", severity="medium", dimension="第六感", delta=-1,
            claim="c", why="w", evidence_ref=[], suggested_fix="",
        )
        with TemporaryDirectory() as tmp:
            ctx = ReviewContext(
                observation={"symbol": "002378", "direction": "bullish", "thesis": "还能拿半年",
                             "timeframe": "半年", "trigger": ""},
                symbol="002378", name="章源钨业", now="2026-11-24T07:30:00Z",
                data_dir=Path(tmp), llm=None,
            )
            with mock.patch.object(reviewer, "build_structure", return_value=make_structure()), \
                 mock.patch.object(reviewer, "fetch_last_close", return_value=15.54), \
                 mock.patch.object(reviewer.rules, "evaluate", return_value=([bad_finding], [])):
                verdict = reviewer.Reviewer().review(ctx)

        # 校验错误不吞结论，但要显式写进 caveats
        self.assertTrue(any("契约校验" in c for c in verdict.caveats))

    def test_review_skips_when_symbol_missing(self):
        ctx = ReviewContext(
            observation={"symbol": ""}, symbol="", name="", now="t",
            data_dir=Path("."), llm=None,
        )
        verdict = reviewer.Reviewer().review(ctx)
        self.assertEqual(verdict.status, "skipped")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m unittest tests.test_anchor_chanlun_reviewer -v
```

Expected: FAIL —— `ModuleNotFoundError`

- [ ] **Step 3: 实现 reviewer.py**

```python
"""anchor-chanlun 点评师：缠论三级别结构 → 与用户观察对照 → findings / 证伪位 / 观察期档位。"""
from __future__ import annotations

import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from ...providers import tdx
from ...reviewers.contract import ReviewContext, ReviewVerdict, validate_verdict
from . import rules, signals, wording
from .engine import build_structure


def _dimension_names() -> list[str]:
    """评分维度名列表，来自 config/scoring.json。"""
    from ...config import load_scoring

    return [item["name"] for item in load_scoring()["dimensions"]]


def _validation_errors(verdict: ReviewVerdict) -> list[str]:
    """契约校验错误列表；配置读不到时也降级成一条错误，不向上抛。"""
    try:
        dimensions = _dimension_names()
    except Exception as exc:  # noqa: BLE001 —— 配置问题也要隔离
        return [f"无法读取评分维度配置: {type(exc).__name__}: {exc}"]
    return validate_verdict(verdict, dimensions)


def _latest_factor_row(symbol: str) -> dict | None:
    """取该标的最新的复权因子行（现价 → 后复权换算用）。

    点评师拿不到数据库连接（`ReviewContext` 只有 `data_dir`），所以这里直接取一次
    连接器；`fetch_adjustment_factors` 已按 ex_date 降序，第一行就是最新一行。
    取不到时返回 None —— 调用方按「无法换算」处理，不要静默当成现价。
    """
    try:
        factors = tdx.fetch_adjustment_factors(symbol)
    except Exception:  # noqa: BLE001 —— 换算失败不该让整轮点评挂掉
        return None
    return factors[0] if factors else None


def _quote_price(payload: dict) -> float:
    """从行情载荷里取现价（**不复权**口径）。

    实测（2026-11-24，`tdx_quotes` 返回 002378）：
      - 顶层键是 BaseInfo / ExtInfo / **HQInfo** / CalcInfo / ProInfo / ...
      - `HQInfo.Now` = 15.54（现价）、`HQInfo.Close` = 15.59（收盘价）
      - **没有 `AttachInfo`** —— 那是 K 线载荷 `tdx_kline` 的元数据，不是行情载荷的。
        读错字段会让回退路径永远静默返回「现价未知」。
    两个容器都试一遍，兼容两种载荷形态。
    """
    for container in ("HQInfo", "AttachInfo"):
        info = payload.get(container)
        if not isinstance(info, dict):
            continue
        for key in ("Now", "Close"):
            value = info.get(key)
            if isinstance(value, (int, float)) and value:
                return float(value)
    return 0.0


def fetch_last_close(symbol: str, setcode: str, structure: dict | None = None) -> float:
    """取现价（**后复权空间**）。

    优先用缠论结构里的 `levels.day.last_close`（上游已算好，省一次连接器调用）；
    结构里没有时才退回实时行情。

    **空间一致性（Global Constraint 16/18）**：结构里的 `last_close` 来自后复权 K 线，
    已经是后复权空间；实时行情返回的是**现价**（不复权空间），必须用复权因子换算成
    后复权再返回，否则会拿 10014 去和 1460 比。
    """
    if structure:
        for level_name in ("day", "m30", "week"):
            level = (structure.get("levels") or {}).get(level_name) or {}
            value = level.get("last_close")
            if isinstance(value, (int, float)) and value:
                return float(value)
    try:
        payload = tdx.fetch_quotes(symbol, setcode)
    except Exception:  # noqa: BLE001
        return 0.0
    price = _quote_price(payload)
    if not price:
        return 0.0
    row = _latest_factor_row(symbol)
    # 换不到因子行就**不能**返回现价 —— 它不在后复权空间，
    # 拿它去和后复权的中枢上下沿比会得出错误结论。返回 0.0 表示「未知」。
    return 0.0 if row is None else tdx.to_houfuquan(price, row)


class Reviewer:
    """缠论点评师。"""

    id = "anchor-chanlun"
    version = "0.1.0"

    def review(self, ctx: ReviewContext) -> ReviewVerdict:
        started = time.monotonic()
        symbol = ctx.symbol or (ctx.observation.get("symbol") or "")
        if not symbol:
            return ReviewVerdict(
                reviewer_id=self.id, reviewer_version=self.version,
                ran_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                status="skipped", duration_ms=0, data_refs=[], findings=[],
                proposed_invalidation=[], horizon_hint=None,
                caveats=["观察未包含证券代码，缠论点评跳过"],
            )

        try:
            setcode = tdx.setcode_for(symbol)
        except ValueError as exc:
            return ReviewVerdict(
                reviewer_id=self.id, reviewer_version=self.version,
                ran_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                status="skipped", duration_ms=0, data_refs=[], findings=[],
                proposed_invalidation=[], horizon_hint=None,
                caveats=[f"无法识别市场：{exc}"],
            )

        work_dir = Path(ctx.data_dir) / "chanlun" / symbol
        work_dir.mkdir(parents=True, exist_ok=True)

        structure = build_structure(symbol, ctx.name or symbol, setcode, work_dir)
        last_close = fetch_last_close(symbol, setcode, structure)

        findings, caveats = rules.evaluate(ctx.observation, structure, last_close)
        if ctx.llm is None:
            # 措辞层降级必须留痕，否则用户以为看到的是 LLM 改写过的表述
            caveats.append(
                "LLM 措辞层不可用（未配置 AGAISTOCK_LLM_BASE_URL / API_KEY / MODEL），"
                "点评保留规则层原文"
            )
        findings = wording.phrase(
            findings,
            ctx.observation,
            llm=ctx.llm,
            context={
                "narrative": structure.get("narrative"),
                "resonance": structure.get("resonance"),
                "discipline": (structure.get("framework") or {}).get("discipline"),
                "day_signal_detail": (structure.get("levels") or {}).get("day", {}).get("signal_detail"),
            },
        )

        invalidation = signals.build_invalidation(structure, last_close)
        hint = signals.build_horizon_hint(ctx.observation, structure, findings, last_close=last_close)

        caveats = list(caveats) + list(structure.get("caveats") or [])

        data_refs = [
            {
                "source": "tdx_kline",
                "params": {"code": symbol, "setcode": setcode, "want_num": 500},
                "window": "week/day/m30 各 500 根",
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        ]

        verdict = ReviewVerdict(
            reviewer_id=self.id,
            reviewer_version=self.version,
            ran_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            status="ok",
            duration_ms=int((time.monotonic() - started) * 1000),
            data_refs=data_refs,
            findings=findings,
            proposed_invalidation=invalidation,
            horizon_hint=hint,
            caveats=caveats,
        )

        # 与 engine.run_one 保持一致地做一次契约校验，但**不丢结论**：
        # 错误写进 caveats，让「有发现却无限制声明」这类问题可见、可追。
        errors = _validation_errors(verdict)
        if errors:
            verdict = replace(
                verdict,
                caveats=list(verdict.caveats)
                + [f"点评结论未通过契约校验: {err}" for err in errors],
            )
        return verdict
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m unittest tests.test_anchor_chanlun_reviewer -v
```

Expected: 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/agaistock/skills/anchor_chanlun/reviewer.py tests/test_anchor_chanlun_reviewer.py
git commit -m "feat: anchor-chanlun reviewer assembling rules, signals and wording"
```

---

### Task 11: 评分聚合

**Files:**
- Create: `src/agaistock/scoring.py`
- Create: `tests/test_scoring.py`

**Interfaces:**
- Consumes: `ReviewVerdict`（Task 3）、`config.load_scoring()`（Task 1）
- Produces:
  - 维度与权重**不硬编码**：`aggregate` 未显式传入 `dimensions` 时，从 `config.load_scoring()` 读取
    （模块内**没有** `DIMENSION_WEIGHTS` 常量，权重只在调用时从配置读）。
  - `agaistock.scoring.aggregate(verdicts: list[ReviewVerdict], reviewer_weights: dict[str, float] | None = None, dimensions: list[dict] | None = None) -> dict`
    返回：
    ```python
    {
      "total": float,
      "score_breakdown": [
        {"dimension": str, "weight": float, "raw": float | None, "weighted": float | None,
         "completeness": "ok" | "no_reviewer",
         "contributions": [{"reviewer_id": str, "finding_codes": [str], "delta": int, "weight": float}]}
      ],
      "scored_dimensions": [str],
      "score_denominator": float,
    }
    ```

- [ ] **Step 1: 写失败的测试**

```python
import unittest

from agaistock.reviewers.contract import Finding, ReviewVerdict
from agaistock import scoring


def verdict(reviewer_id, dimension, delta, code="X"):
    return ReviewVerdict(
        reviewer_id=reviewer_id, reviewer_version="0.1.0", ran_at="2026-11-24T07:00:00Z",
        status="ok", duration_ms=0, data_refs=[],
        findings=[Finding(code=code, severity="medium", dimension=dimension, delta=delta,
                          claim="c", why="w", evidence_ref=[], suggested_fix="")],
        proposed_invalidation=[], horizon_hint=None, caveats=[],
    )


DIMENSIONS = [
    {"name": "事实锚定", "weight": 0.25},
    {"name": "证伪条件", "weight": 0.25},
    {"name": "逻辑链条", "weight": 0.20},
    {"name": "位置与时机", "weight": 0.15},
    {"name": "一致性", "weight": 0.15},
]


class ScoringTests(unittest.TestCase):
    def test_no_reviewer_dimension_is_excluded_not_zeroed(self):
        result = scoring.aggregate([], dimensions=DIMENSIONS)
        entry = next(e for e in result["score_breakdown"] if e["dimension"] == "事实锚定")
        self.assertEqual(entry["completeness"], "no_reviewer")
        self.assertIsNone(entry["raw"])
        self.assertIsNone(entry["weighted"])
        self.assertEqual(result["score_denominator"], 0.0)

    def test_dimensions_with_findings_are_summed_across_reviewers(self):
        verdicts = [
            verdict("a", "位置与时机", -12, "A1"),
            verdict("b", "位置与时机", -8, "B1"),
        ]
        result = scoring.aggregate(verdicts, dimensions=DIMENSIONS)
        entry = next(e for e in result["score_breakdown"] if e["dimension"] == "位置与时机")
        self.assertEqual(entry["raw"], 80)  # 100 - 12 - 8
        self.assertEqual(entry["completeness"], "ok")
        self.assertEqual(len(entry["contributions"]), 2)

    def test_total_is_weighted_average_over_scored_dimensions_only(self):
        verdicts = [verdict("a", "位置与时机", -12)]
        result = scoring.aggregate(verdicts, dimensions=DIMENSIONS)
        self.assertAlmostEqual(result["total"], 88.0)
        self.assertAlmostEqual(result["score_denominator"], 0.15)
        self.assertEqual(result["scored_dimensions"], ["位置与时机"])

    def test_neutral_finding_scores_full_marks_and_is_marked_ok(self):
        verdicts = [verdict("a", "位置与时机", 0)]
        result = scoring.aggregate(verdicts, dimensions=DIMENSIONS)
        entry = next(e for e in result["score_breakdown"] if e["dimension"] == "位置与时机")
        self.assertEqual(entry["raw"], 100)
        self.assertEqual(entry["completeness"], "ok")

    def test_reviewer_weight_scales_delta(self):
        verdicts = [verdict("a", "位置与时机", -12)]
        result = scoring.aggregate(verdicts, reviewer_weights={"a": 0.5}, dimensions=DIMENSIONS)
        entry = next(e for e in result["score_breakdown"] if e["dimension"] == "位置与时机")
        self.assertEqual(entry["raw"], 94)  # 100 - 12*0.5

    def test_contributions_reference_finding_codes(self):
        verdicts = [verdict("a", "位置与时机", -12, "CHAN_X")]
        result = scoring.aggregate(verdicts, dimensions=DIMENSIONS)
        entry = next(e for e in result["score_breakdown"] if e["dimension"] == "位置与时机")
        self.assertEqual(entry["contributions"][0]["finding_codes"], ["CHAN_X"])

    def test_contribution_exposes_the_applied_delta_so_raw_can_be_reconciled(self):
        # 主规格 §5.3：每一分必须可追溯到具体 Finding。
        # 只给未缩放的 delta 时，weight != 1 的情况下展示层算不平 raw。
        verdicts = [verdict("a", "位置与时机", -12)]
        result = scoring.aggregate(verdicts, reviewer_weights={"a": 0.5}, dimensions=DIMENSIONS)
        entry = next(e for e in result["score_breakdown"] if e["dimension"] == "位置与时机")
        contribution = entry["contributions"][0]
        self.assertEqual(contribution["delta"], -12)
        self.assertEqual(contribution["applied_delta"], -6)
        # raw 必须等于 100 + 各 contribution 的 applied_delta 之和
        self.assertEqual(
            entry["raw"],
            100 + sum(c["applied_delta"] for c in entry["contributions"]),
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m unittest tests.test_scoring -v
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'agaistock.scoring'`

- [ ] **Step 3: 实现 scoring.py**

```python
"""评分聚合：把多家点评师的 findings 按固定维度汇总。

规则（设计文档 §5.2）：
  - 同一维度多家点评师的 delta 直接相加
  - 没有点评师贡献的维度从加权平均的分子分母一并剔除，并标 no_reviewer
  - 「有人点评且结论中性」(delta=0) 与「无人点评」是不同的事，不可混淆
"""
from __future__ import annotations

from typing import Any

from .reviewers.contract import ReviewVerdict


def aggregate(
    verdicts: list[ReviewVerdict],
    reviewer_weights: dict[str, float] | None = None,
    dimensions: list[dict] | None = None,
) -> dict[str, Any]:
    if dimensions is None:
        from . import config

        dimensions = config.load_scoring()["dimensions"]

    weights = reviewer_weights or {}

    breakdown: list[dict[str, Any]] = []
    numerator = 0.0
    denominator = 0.0
    scored_dimensions: list[str] = []

    for dimension in dimensions:
        name = dimension["name"]
        weight = float(dimension["weight"])
        contributions: list[dict[str, Any]] = []
        total_delta = 0.0
        for verdict in verdicts:
            reviewer_weight = float(weights.get(verdict.reviewer_id, 1.0))
            matched = [f for f in verdict.findings if f.dimension == name]
            if not matched:
                continue
            delta = sum(f.delta for f in matched)
            total_delta += delta * reviewer_weight
            contributions.append({
                "reviewer_id": verdict.reviewer_id,
                "finding_codes": [f.code for f in matched],
                # delta 是这条 finding 自己的分值；applied_delta 是乘上点评师权重后
                # 真正计入 raw 的值。两者都要给：主规格 §5.3 要求「每一分必须可追溯到
                # 具体 Finding」，展示层若只用 delta 去解释 raw，weight != 1 时算不平。
                "delta": delta,
                "applied_delta": delta * reviewer_weight,
                "weight": reviewer_weight,
            })

        if not contributions:
            breakdown.append({
                "dimension": name,
                "weight": weight,
                "raw": None,
                "weighted": None,
                "completeness": "no_reviewer",
                "contributions": [],
            })
            continue

        raw = 100.0 + total_delta
        weighted = raw * weight
        numerator += weighted
        denominator += weight
        scored_dimensions.append(name)
        breakdown.append({
            "dimension": name,
            "weight": weight,
            "raw": raw,
            "weighted": weighted,
            "completeness": "ok",
            "contributions": contributions,
        })

    total = (numerator / denominator) if denominator > 0 else 0.0

    return {
        "total": total,
        "score_breakdown": breakdown,
        "scored_dimensions": scored_dimensions,
        "score_denominator": denominator,
    }
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m unittest tests.test_scoring -v
```

Expected: 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/agaistock/scoring.py tests/test_scoring.py
git commit -m "feat: dimension scoring aggregation with completeness tracking"
```

---

### Task 12: 观察期规划

**Files:**
- Create: `src/agaistock/horizon.py`
- Create: `tests/test_horizon.py`

**Interfaces:**
- Consumes: `ReviewVerdict`（Task 3）
- Produces:
  - `agaistock.horizon.TIER_ALLOWED = {"short": (3, 5), "mid": (5, 10, 20), "long": (10, 20, 40), "event": (5, 10, 20)}`
  - `agaistock.horizon.TIER_ORDER = ("short", "mid", "event", "long")`（由严到宽）
    —— 顺序按**允许窗口**排，不按字母直觉：`event` 的窗口 (5,10,20) 与 `mid` 相同，
    都比 `long` 的 (10,20,40) 保守，所以 `event` 必须排在 `long` 前面。
    （Task 8 的 `signals.TIER_RANK` 用的是同一套语义：event 与 mid 同 rank。）
  - `agaistock.horizon.resolve_tier(verdicts: list[ReviewVerdict]) -> tuple[str | None, list[str]]`
    返回 `(档位, 各点评师给出的原始档位列表)`；多点评师取**最保守**。
  - `agaistock.horizon.plan(observation: dict, verdicts: list[ReviewVerdict], start: str, review_at: str | None = None) -> dict`
    返回 `{"tier", "review_at", "allowed_window", "rationale", "confidence", "checks", "invalidation_triggers"}`。

- [ ] **Step 1: 写失败的测试**

```python
import unittest

from agaistock.horizon import resolve_tier, plan
from agaistock.reviewers.contract import HorizonHint, ProposedInvalidation, ReviewVerdict


def verdict_with_tier(reviewer_id, tier):
    return ReviewVerdict(
        reviewer_id=reviewer_id, reviewer_version="0.1.0", ran_at="2026-11-24T07:00:00Z",
        status="ok", duration_ms=0, data_refs=[], findings=[], proposed_invalidation=[],
        horizon_hint=HorizonHint(tier=tier, rationale="r", checks=[]), caveats=[],
    )


class HorizonTests(unittest.TestCase):
    def test_resolve_tier_takes_the_most_conservative(self):
        tier, sources = resolve_tier([verdict_with_tier("a", "long"), verdict_with_tier("b", "short")])
        self.assertEqual(tier, "short")
        self.assertEqual(len(sources), 2)

    def test_resolve_tier_returns_none_without_hints(self):
        tier, sources = resolve_tier([verdict_with_tier("a", "long")])
        self.assertEqual(tier, "long")
        tier, sources = resolve_tier([])
        self.assertIsNone(tier)

    def test_plan_review_at_falls_inside_allowed_window(self):
        plan_result = plan(
            {"symbol": "002378", "thesis": "t"},
            [verdict_with_tier("a", "short")],
            start="2026-11-24",
        )
        self.assertIn(plan_result["review_at"], ("2026-11-27", "2026-12-01"))
        self.assertTrue(plan_result["allowed_window"])

    def test_plan_uses_proposed_invalidation_as_checks(self):
        verdict = ReviewVerdict(
            reviewer_id="a", reviewer_version="0.1.0", ran_at="t", status="ok", duration_ms=0,
            data_refs=[], findings=[],
            proposed_invalidation=[
                ProposedInvalidation(
                    desc="跌破 22.39", source="chan.pivot.ZD",
                    comparator="below", tolerance=0.5, rationale="结构失效位",
                )
            ],
            horizon_hint=None, caveats=[],
        )
        plan_result = plan({"symbol": "002378"}, [verdict], start="2026-11-24")
        self.assertEqual(len(plan_result["checks"]), 1)
        self.assertEqual(plan_result["checks"][0]["desc"], "跌破 22.39")
        self.assertEqual(plan_result["invalidation_triggers"], ["跌破 22.39"])

    def test_plan_checks_keep_the_rationale(self):
        # rationale 必须跟着 check 一起传到 UI：中枢在头顶时「跌破下沿」的条件已经成立，
        # 只作结构参考 —— 丢掉 rationale 就会被展示成待触发的失效条件。
        verdict = ReviewVerdict(
            reviewer_id="a", reviewer_version="0.1.0", ran_at="t", status="ok", duration_ms=0,
            data_refs=[], findings=[],
            proposed_invalidation=[
                ProposedInvalidation(
                    desc="跌破 22.39", source="chan.pivot.ZD",
                    comparator="below", tolerance=0.5, rationale="中枢位于现价上方，只作结构参考",
                )
            ],
            horizon_hint=None, caveats=[],
        )
        plan_result = plan({"symbol": "002378"}, [verdict], start="2026-11-24")
        self.assertEqual(plan_result["checks"][0]["rationale"], "中枢位于现价上方，只作结构参考")

    def test_resolve_tier_prefers_event_over_long(self):
        # event 的窗口 (5,10,20) 比 long 的 (10,20,40) 更保守，必须取 event。
        tier, sources = resolve_tier([
            verdict_with_tier("a", "event"), verdict_with_tier("b", "long"),
        ])
        self.assertEqual(tier, "event")
        self.assertEqual(len(sources), 2)

    def test_plan_without_any_hint_still_returns_structure(self):
        plan_result = plan({"symbol": "002378"}, [], start="2026-11-24")
        self.assertIn("tier", plan_result)
        self.assertIn("checks", plan_result)

    def test_explicit_review_at_on_an_allowed_offset_keeps_the_full_window(self):
        # 档位里的天数是**交易日**偏移。显式传入的日期如果正好是
        # `_trading_days_later(start, 10)` 的结果，就不该被误判成「不在档位内」
        # 而把 40 天的窗口塌缩成 10 天。
        result = plan(
            {"symbol": "002378"},
            [verdict_with_tier("a", "long")],
            start="2026-11-24",
            review_at="2026-12-08",  # 2026-11-24 起第 10 个交易日
        )
        self.assertEqual(result["review_at"], "2026-12-08")
        # 窗口没被塌缩：末位不是 review_at 本身
        self.assertNotEqual(result["allowed_window"][1], "2026-12-08")
        self.assertEqual(result["allowed_window"][0], "2026-11-24")

    def test_review_at_outside_the_allowed_offsets_falls_back_to_the_earliest(self):
        # 越界的日期必须被拉回档位内最早的那个，而且 review_at 一定要落在
        # allowed_window 之内（不能出现「返回的日期在自己的窗口之外」）。
        result = plan(
            {"symbol": "002378"},
            [verdict_with_tier("a", "long")],
            start="2026-11-24",
            review_at="2027-02-01",
        )
        self.assertEqual(result["review_at"], "2026-12-08")
        self.assertIn(result["review_at"], (
            result["allowed_window"][0],
            result["allowed_window"][1],
        ))
        self.assertEqual(result["allowed_window"][1], "2026-12-08")


if __name__ == "__main__":
    unittest.main()
```

> 注：上面的 `test_plan_uses_proposed_invalidation_as_checks` 用 `ProposedInvalidation` 实例而非 dict 传入；实现时 `plan` 需同时接受 `ReviewVerdict` 对象与 dict 形式。实现见下方。

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m unittest tests.test_horizon -v
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'agaistock.horizon'`

- [ ] **Step 3: 实现 horizon.py**

```python
"""观察期规划。

档位上限由点评师的 horizon_hint 决定，多家点评师取**最保守**。
具体 review_at 在允许档位内选取；本实现取档位内最小值（更早复校更安全）。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .reviewers.contract import ReviewVerdict

TIER_ALLOWED: dict[str, tuple[int, ...]] = {
    "short": (3, 5),
    "mid": (5, 10, 20),
    "long": (10, 20, 40),
    "event": (5, 10, 20),
}

# 保守程度排序（越靠前越保守，min() 取最保守的那个）。
# 按**允许窗口**排序，不按字母直觉：event 与 mid 的窗口完全相同 (5,10,20)，
# 都比 long 的 (10,20,40) 保守。若把 event 排到最后，就会出现
# 「有点评师说 event（最早 5 天复校）、另一个说 long（最早 10 天）」却选了 long 的怪事。
TIER_ORDER = ("short", "mid", "event", "long")


def _conservative(tier: str) -> int:
    return TIER_ORDER.index(tier) if tier in TIER_ORDER else 0


def resolve_tier(verdicts: list[ReviewVerdict]) -> tuple[str | None, list[str]]:
    """返回 (最保守档位, 各点评师给出的档位列表)。"""
    tiers: list[str] = []
    for verdict in verdicts:
        hint = verdict.horizon_hint
        if hint is None:
            continue
        tier = getattr(hint, "tier", None) or (hint.get("tier") if isinstance(hint, dict) else None)
        if tier in TIER_ALLOWED:
            tiers.append(tier)
    if not tiers:
        return None, []
    best = min(tiers, key=_conservative)
    return best, tiers


def _trading_days_later(start: date, offset: int) -> date:
    """按自然日推进后跳过周末（未处理节假日，仅作近似）。"""
    current = start
    remaining = offset
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def _trading_days_between(start: date, end: date) -> int:
    """start 之后到 end（含）之间的交易日数，与 `_trading_days_later` 同口径。

    **必须与 `_trading_days_later` 同口径**：档位里的天数是**交易日偏移**，
    而 `(end - start).days` 是**日历日差**。两个口径混用时，
    自动推导出来的那个日期（`_trading_days_later(start, 10)`）会因为
    日历日差是 14 而不是 10，被误判成「不在允许档位内」。
    """
    if end <= start:
        return 0
    current = start
    count = 0
    while True:
        current += timedelta(days=1)
        if current > end:
            return count
        if current.weekday() < 5:
            count += 1


def _proposed_items(verdicts: list[ReviewVerdict]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for verdict in verdicts:
        for item in verdict.proposed_invalidation:
            if isinstance(item, dict):
                data = item
            else:
                data = item.to_dict()
            items.append(data)
    return items


def plan(
    observation: dict,
    verdicts: list[ReviewVerdict],
    start: str,
    review_at: str | None = None,
) -> dict[str, Any]:
    tier, source_tiers = resolve_tier(verdicts)
    allowed = TIER_ALLOWED.get(tier or "", ())

    start_date = date.fromisoformat(start)
    if review_at:
        chosen = date.fromisoformat(review_at)
        # 用**交易日**偏移校验，不要用日历日差 —— 档位里的天数是交易日偏移。
        offset = _trading_days_between(start_date, chosen)
        if allowed and offset not in allowed:
            # 用户指定的日期不在允许档位内 → 落到档位内最早的那个，
            # 并同步收窄窗口，保证 review_at 一定落在 allowed_window 之内。
            allowed = (min(allowed),)
            chosen = _trading_days_later(start_date, min(allowed))
    elif allowed:
        chosen = _trading_days_later(start_date, min(allowed))
    else:
        chosen = _trading_days_later(start_date, 5)

    window_start = start_date
    window_end = _trading_days_later(start_date, max(allowed)) if allowed else chosen

    proposed = _proposed_items(verdicts)
    checks = [
        {
            "id": f"c{index + 1}",
            "desc": item.get("desc", ""),
            "source": item.get("source", ""),
            "comparator": item.get("comparator", ""),
            "tolerance": item.get("tolerance"),
            # rationale 必须一起带下来：中枢在头顶时，「跌破下沿」的条件**已经成立**，
            # 只作结构参考、不作为本次的失效判定 —— 丢掉 rationale，下游（Task 15 的 UI）
            # 会把一条已成立的条件当成待触发条件展示。
            "rationale": item.get("rationale", ""),
        }
        for index, item in enumerate(proposed)
    ]

    rationales = []
    for verdict in verdicts:
        hint = verdict.horizon_hint
        if hint is None:
            continue
        rationale = getattr(hint, "rationale", None) or (
            hint.get("rationale") if isinstance(hint, dict) else ""
        )
        if rationale:
            rationales.append(f"{verdict.reviewer_id}: {rationale}")

    return {
        "tier": tier,
        "source_tiers": source_tiers,
        "review_at": chosen.isoformat(),
        "allowed_window": [window_start.isoformat(), window_end.isoformat()],
        "rationale": "；".join(rationales) if rationales else "无点评师给出档位建议，按默认短期档处理",
        "confidence": 0.5 if tier else 0.0,
        "checks": checks,
        "invalidation_triggers": [item.get("desc", "") for item in proposed],
    }
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m unittest tests.test_horizon -v
```

Expected: 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/agaistock/horizon.py tests/test_horizon.py
git commit -m "feat: observation horizon planning with conservative tier resolution"
```

---

### Task 13: CLI 端到端

**Files:**
- Create: `src/agaistock/cli.py`
- Create: `tests/test_cli.py`

**Interfaces:**
- Consumes: `storage.db`（Task 2）、`registry` / `engine`（Task 4）、`scoring`（Task 11）、`horizon`（Task 12）、`config`（Task 1）、`llm.client.from_env`（Task 9）
- Produces CLI：
  ```
  python -m agaistock.cli review --symbol 002378 --name 章源钨业 --text "<口述原文>" [--db PATH] [--json]
  python -m agaistock.cli list [--db PATH] [--include-deleted] [--json]
  python -m agaistock.cli reviews <observation_id> [--db PATH] [--json]
  python -m agaistock.cli delete <observation_id> [--db PATH] [--json]
  ```
  `review` 的 `--json` 输出为：
  ```json
  {"observation_id": "...", "reviews": [...], "score": {...}, "horizon": {...}}
  ```
  `reviews` 的 `--json` 输出为 `{"observation_id": "...", "items": [...]}`（每项含 `verdict` 字段）。
  `list` 的 `--json` 输出为 `{"ok": true, "items": [...]}` —— **带 ok/items 外壳**，
  与 Mini App 前端 `data.items` 的既有契约一致（Task 14 的 `/api/observations` 直接透传这份负载）。

  **数据库路径优先级**：命令行 `--db` > 环境变量 `AGAISTOCK_DB` > `data/agaistock.db`。
  （Task 14 的 Mini App 后端通过 `AGAISTOCK_DB` 指定路径，因此此环境变量必须被支持。）

  **LLM 措辞层的接线**：`review` 用 `llm.client.from_env()` 构造客户端并传入 `ReviewContext.llm`。
  环境变量 `AGAISTOCK_LLM_BASE_URL` / `AGAISTOCK_LLM_API_KEY` / `AGAISTOCK_LLM_MODEL`
  缺任一 → `from_env()` 返回 `None` → 点评保留规则层原文（Task 9 的措辞层降级），
  并在 verdict 的 caveats 里留下「措辞层不可用」的痕迹。
  不接线的话，Task 9 的措辞层在成品 CLI 里就是死代码，Global Constraint 10 的保护从未生效。

- [ ] **Step 1: 写失败的测试**

```python
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agaistock import cli


class CliTests(unittest.TestCase):
    def test_list_on_empty_db_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "a.db"
            code = cli.main(["list", "--db", str(db_path), "--json"])
            self.assertEqual(code, 0)

    def test_delete_unknown_id_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "a.db"
            code = cli.main(["delete", "nope", "--db", str(db_path)])
            self.assertEqual(code, 1)

    def test_reviews_on_unknown_observation_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "a.db"
            code = cli.main(["reviews", "obs_nope", "--db", str(db_path), "--json"])
            self.assertEqual(code, 0)

    def test_db_path_env_var_is_used_when_flag_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "env.db"
            with mock.patch.dict(os.environ, {"AGAISTOCK_DB": str(db_path)}):
                cli.main(["list", "--json"])
            self.assertTrue(db_path.is_file())

    def test_review_persists_observation_and_returns_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "a.db"
            fake_verdict = {
                "reviewer_id": "anchor-chanlun", "reviewer_version": "0.1.0",
                "ran_at": "2026-11-24T07:00:00Z", "status": "ok", "duration_ms": 1,
                "data_refs": [], "findings": [], "proposed_invalidation": [],
                "horizon_hint": None, "caveats": [],
            }
            with mock.patch.object(cli, "run_reviewers", return_value=[]) as runner:
                code = cli.main([
                    "review", "--symbol", "002378", "--name", "章源钨业",
                    "--text", "还能拿半年", "--db", str(db_path), "--json",
                ])
            self.assertEqual(code, 0)

    def test_review_wires_llm_client_into_review_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "a.db"
            sentinel = object()
            captured = {}

            def fake_run_reviewers(ctx, reviewers):
                captured["ctx"] = ctx
                return []

            with mock.patch.object(cli, "run_reviewers", side_effect=fake_run_reviewers), \
                 mock.patch.object(cli.llm_client, "from_env", return_value=sentinel):
                code = cli.main([
                    "review", "--symbol", "002378", "--name", "章源钨业",
                    "--text", "还能拿半年", "--db", str(db_path), "--json",
                ])
            self.assertEqual(code, 0)
            # 措辞层必须真的接上：ctx.llm 拿到 from_env() 的返回值
            self.assertIs(captured["ctx"].llm, sentinel)

    def test_review_closes_the_db_connection_even_when_the_command_fails(self):
        # Windows 上未关闭的 sqlite 句柄会锁住 .db 文件（临时目录删除直接 PermissionError）。
        # 连接必须在 finally 里关 —— 命令中途抛异常时同样要关。
        conn = mock.MagicMock()
        with mock.patch.object(cli, "_open", return_value=conn), \
             mock.patch.object(cli.registry, "load_reviewers",
                               side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                cli.main([
                    "review", "--symbol", "002378", "--name", "章源钨业",
                    "--text", "还能拿半年", "--db", "unused.db", "--json",
                ])
        conn.close.assert_called_once_with()

    def test_list_closes_the_db_connection_even_when_it_fails(self):
        conn = mock.MagicMock()
        with mock.patch.object(cli, "_open", return_value=conn), \
             mock.patch.object(cli.db, "list_observations", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                cli.main(["list", "--db", "unused.db", "--json"])
        conn.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m unittest tests.test_cli -v
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'agaistock.cli'`

- [ ] **Step 3: 实现 cli.py**

```python
"""命令行入口：python -m agaistock.cli

子命令：
  review  记录一条观察 → 跑点评师 → 落库 → 评分 → 观察期
  list    列出观察
  delete  软删除一条观察
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from . import config, horizon as horizon_mod, scoring
from .llm import client as llm_client
from .reviewers import engine as engine_mod
from .reviewers import registry
from .storage import db

DEFAULT_DB = "data/agaistock.db"


def _default_db(db_arg: str | None) -> Path:
    if db_arg:
        return Path(db_arg)
    env_db = os.environ.get("AGAISTOCK_DB", "").strip()
    if env_db:
        return Path(env_db)
    return config.repo_root() / DEFAULT_DB


def _open(db_arg: str | None):
    path = _default_db(db_arg)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect(path)
    db.migrate(conn)
    return conn


def _parse_observation(symbol: str, name: str, text: str) -> dict:
    """极简解析：方向与时限靠关键词；真实解析由 Mini App 的 LLM 层完成。"""
    lowered = text.lower()
    direction = "neutral"
    if any(word in text for word in ("看多", "看好", "拿", "涨", "买")):
        direction = "bullish"
    elif any(word in text for word in ("看空", "跌", "卖", "减仓")):
        direction = "bearish"
    timeframe = ""
    for window in ("半年", "一年", "三个月", "一个月", "两周"):
        if window in text:
            timeframe = window
            break
    return {
        "symbol": symbol,
        "name": name,
        "direction": direction,
        "thesis": text[:80],
        "confidence": 0.0,
        "timeframe": timeframe,
        "trigger": "",
        "position": {},
        "raw_text": text,
    }


def run_reviewers(ctx, reviewers):  # pragma: no cover - 便于测试打桩
    return engine_mod.run_reviewers([r["instance"] for r in reviewers], ctx)


def cmd_review(args) -> int:
    conn = _open(args.db)
    try:
        observation = _parse_observation(args.symbol, args.name, args.text)
        observation_id = db.insert_observation(conn, observation)

        reviewers = registry.load_reviewers()
        ctx = engine_mod.ReviewContext(
            observation=observation,
            symbol=args.symbol,
            name=args.name,
            now=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            data_dir=config.repo_root() / "data",
            # 措辞层接线：环境变量没配全时 from_env() 返回 None → 点评保留规则层原文
            llm=llm_client.from_env(),
        )
        verdicts = run_reviewers(ctx, reviewers)
        saved = engine_mod.persist(conn, observation_id, verdicts)

        weights = {r["id"]: float(r.get("weight", 1.0)) for r in reviewers}
        score = scoring.aggregate(verdicts, reviewer_weights=weights)
        plan = horizon_mod.plan(observation, verdicts, start=date.today().isoformat())

        payload = {
            "observation_id": observation_id,
            "reviews": saved,
            "score": score,
            "horizon": plan,
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"观察 {observation_id}：{observation['name']} {observation['symbol']}")
            print(f"评分 {score['total']:.1f} / 100（被审维度：{'、'.join(score['scored_dimensions']) or '无'}）")
            print(f"观察期 {plan['review_at']}（档位 {plan['tier'] or '默认'}）")
            for verdict in saved:
                print(f"- {verdict['reviewer_id']} [{verdict['status']}] {len(verdict['findings'])} 条发现")
        return 0
    finally:
        # 显式关闭连接：Windows 上未关闭的 sqlite 句柄会锁住 .db 文件，
        # 临时目录清理与后续迁移都会失败（临时目录删除直接报 PermissionError）。
        # **必须放 finally** —— 命令中途抛异常（配置坏了、点评师炸了）时句柄同样会锁住文件。
        conn.close()


def cmd_list(args) -> int:
    conn = _open(args.db)
    try:
        rows = db.list_observations(conn, include_deleted=args.include_deleted)
        if args.json:
            # 带 ok/items 外壳：Mini App 前端读的是 data.items（见 Task 14 / Task 15）
            print(json.dumps({"ok": True, "items": rows}, ensure_ascii=False, indent=2))
        else:
            for row in rows:
                marker = "（已删除）" if row.get("deleted_at") else ""
                print(f"{row['id']}  {row.get('created_at')}  {row.get('name')} {row.get('symbol')}{marker}")
        return 0
    finally:
        conn.close()


def cmd_reviews(args) -> int:
    conn = _open(args.db)
    try:
        items = db.latest_reviews(conn, args.observation_id)
        payload = {"observation_id": args.observation_id, "items": items}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            for item in items:
                verdict = item.get("verdict") or {}
                print(f"{item['reviewer_id']} [{item['status']}] {len(verdict.get('findings') or [])} 条发现")
        return 0
    finally:
        conn.close()


def cmd_delete(args) -> int:
    conn = _open(args.db)
    try:
        ok = db.soft_delete_observation(conn, args.observation_id)
        if not ok:
            if args.json:
                print(json.dumps({"ok": False, "id": args.observation_id}, ensure_ascii=False))
            else:
                print(f"未找到或已删除：{args.observation_id}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"ok": True, "id": args.observation_id}, ensure_ascii=False))
        else:
            print(f"已软删除 {args.observation_id}（不参与评分与校准统计）")
        return 0
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agaistock")
    subparsers = parser.add_subparsers(dest="command", required=True)

    review = subparsers.add_parser("review", help="记录观察并跑点评")
    review.add_argument("--symbol", required=True)
    review.add_argument("--name", default="")
    review.add_argument("--text", required=True)
    review.add_argument("--db", default=None)
    review.add_argument("--json", action="store_true")
    review.set_defaults(func=cmd_review)

    listing = subparsers.add_parser("list", help="列出观察")
    listing.add_argument("--db", default=None)
    listing.add_argument("--include-deleted", action="store_true")
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(func=cmd_list)

    reviews_cmd = subparsers.add_parser("reviews", help="列出某条观察的点评结论")
    reviews_cmd.add_argument("observation_id")
    reviews_cmd.add_argument("--db", default=None)
    reviews_cmd.add_argument("--json", action="store_true")
    reviews_cmd.set_defaults(func=cmd_reviews)

    delete = subparsers.add_parser("delete", help="软删除观察")
    delete.add_argument("observation_id")
    delete.add_argument("--db", default=None)
    delete.add_argument("--json", action="store_true")
    delete.set_defaults(func=cmd_delete)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m unittest tests.test_cli -v
```

Expected: 10 tests PASS

- [ ] **Step 5: 真实跑一遍（关键一步）**

```bash
python -m agaistock.cli review --symbol 002378 --name 章源钨业 --text "章源钨业我看了三年了，钨价从去年就开始涨，公司储量排前列，明年上半年产量能翻倍。我觉得还能拿半年。"
```

Expected: 打印观察 id、评分、观察期，并列出 `anchor-chanlun` 的发现条数。

- [ ] **Step 6: Commit**

```bash
git add src/agaistock/cli.py tests/test_cli.py
git commit -m "feat: cli entry for review, list and delete"
```

---

### Task 14: Mini App 后端 API

**Files:**
- Modify: `miniapps/agaistock/miniapp/node/server.mjs`
- Create: `miniapps/agaistock/test/api.test.mjs`

**Interfaces:**
- Consumes: Task 13 的 CLI（Node 侧 spawn `python -m agaistock.cli`）
- Produces:
  - `export async function handleRoute(request, response, options = {}) -> Promise<void>`
    依赖**全部显式注入**，不从任何闭包或模块作用域里捕获宿主对象：
    - `options.context` —— 宿主 context（`/api/status` 用它的 `agent` / `capabilities`）。
    - `options.clientEntry` —— `index.html` 的文本内容（`/dashboard` 用）。
    - `options.readObservations` —— `async () => array`，旧的 JSON 文件观察库读取（`/api/status` 计数回退时用）。
    - `options.writeObservations` —— `async (list) => void`，旧 JSON 文件观察库写入（`/api/save` 用）。
    - `options.parseObservation` —— `async (rawText) => {ok, ...}`，解析草稿（`/api/parse` 用）。
    - `options.kernel` —— 可注入的内核调用函数，签名 `(args: string[]) => Promise<{code: number, stdout: string, stderr: string}>`。
      缺省时使用真实的 `runKernel`。**测试注入 fake kernel**，因此本任务不依赖真实数据库与网络。
    - `options.dbPath` —— 传给内核的数据库路径（缺省用工作区 `data/agaistock.db`）。
  - 路由：
    - `GET    /dashboard` —— 返回 `clientEntry`
    - `GET    /api/status` —— 运行时状态 + 观察数量
    - `GET    /api/observations` —— 列出观察（走内核 `list --json`），**返回 `{ok: true, items: [...]}`**
    - `POST   /api/parse` —— body `{ text }` → 解析观察卡
    - `POST   /api/save` —— body `{ draft, rawText }` → 写入旧的 JSON 文件观察库
    - `POST   /api/review` —— body `{ symbol, name, text }` → `200 {observation_id, reviews, score, horizon}`；缺 text → `400`
    - `GET    /api/observations/:id/reviews` → `200 {observation_id, items:[...]}`
    - `DELETE /api/observations/:id` → `200 {ok:true, id}`；内核返回非 0 → `404 {ok:false, error:'not_found'}`

**关键设计（不可省略）**：现有 `handle` 是 `start()` 内部的**闭包**，捕获了 `context`、
`clientEntry`、`readObservations`、`writeObservations`、`parseObservation`。
把它直接提升为模块级导出的 `handleRoute`，这些名字就变成未定义 → `/dashboard`、
`/api/parse`、`/api/save` 抛 ReferenceError → 500；而现有 `pipeline.test.mjs` 只测纯函数，
**这个破坏是静默的**。所以依赖必须由 `start()` 组装后显式传入，测试则注入 fake 依赖。

**设计要点**：Node 侧**不引入 sqlite 依赖**，所有数据库操作一律通过 Python 内核 CLI 完成 —— 这保持了「接入层是唯一接口」这条不变（主规格 D3），也避免 Node 与 Python 两套 schema 定义漂移。

- [ ] **Step 1: 写失败的测试**

`miniapps/agaistock/test/api.test.mjs`：

```javascript
import assert from 'node:assert/strict';
import test from 'node:test';

import { handleRoute } from '../miniapp/node/server.mjs';

function makeRequest(method, url, body) {
  return {
    method,
    url,
    headers: { 'content-type': 'application/json' },
    async *[Symbol.asyncIterator]() {
      if (body !== undefined) yield Buffer.from(JSON.stringify(body));
    },
  };
}

class FakeResponse {
  constructor() {
    this.statusCode = 0;
    this.headers = {};
    this.body = '';
  }
  writeHead(status, headers) {
    this.statusCode = status;
    this.headers = headers;
  }
  end(chunk) {
    this.body += chunk ?? '';
  }
  json() {
    return JSON.parse(this.body);
  }
}

function fakeKernel(result) {
  const calls = [];
  const kernel = async (args) => {
    calls.push(args);
    return { code: 0, stdout: JSON.stringify(result), stderr: '' };
  };
  kernel.calls = calls;
  return kernel;
}

test('DELETE /api/observations/:id returns 200 when kernel succeeds', async () => {
  const response = new FakeResponse();
  const kernel = fakeKernel({ ok: true, id: 'obs_123' });
  await handleRoute(
    makeRequest('DELETE', '/api/observations/obs_123'),
    response,
    { kernel, dbPath: 'test.db' },
  );
  assert.equal(response.statusCode, 200);
  assert.equal(response.json().ok, true);
  assert.ok(kernel.calls[0].includes('delete'));
  assert.ok(kernel.calls[0].includes('obs_123'));
});

test('DELETE /api/observations/:id returns 404 when kernel reports missing', async () => {
  const response = new FakeResponse();
  const kernel = async () => ({ code: 1, stdout: '', stderr: '未找到' });
  await handleRoute(
    makeRequest('DELETE', '/api/observations/obs_missing'),
    response,
    { kernel, dbPath: 'test.db' },
  );
  assert.equal(response.statusCode, 404);
  assert.equal(response.json().ok, false);
});

test('GET /api/observations/:id/reviews returns items array', async () => {
  const response = new FakeResponse();
  const kernel = fakeKernel({ observation_id: 'obs_123', items: [{ reviewer_id: 'anchor-chanlun' }] });
  await handleRoute(
    makeRequest('GET', '/api/observations/obs_123/reviews'),
    response,
    { kernel, dbPath: 'test.db' },
  );
  assert.equal(response.statusCode, 200);
  assert.ok(Array.isArray(response.json().items));
});

test('POST /api/review without text returns 400 and does not call kernel', async () => {
  const response = new FakeResponse();
  const kernel = fakeKernel({});
  await handleRoute(
    makeRequest('POST', '/api/review', {}),
    response,
    { kernel, dbPath: 'test.db' },
  );
  assert.equal(response.statusCode, 400);
  assert.equal(kernel.calls.length, 0);
});

test('POST /api/review forwards symbol, name and text to kernel', async () => {
  const response = new FakeResponse();
  const kernel = fakeKernel({ observation_id: 'obs_9', reviews: [], score: {}, horizon: {} });
  await handleRoute(
    makeRequest('POST', '/api/review', { symbol: '002378', name: '章源钨业', text: '还能拿半年' }),
    response,
    { kernel, dbPath: 'test.db' },
  );
  assert.equal(response.statusCode, 200);
  assert.equal(response.json().observation_id, 'obs_9');
  const args = kernel.calls[0];
  assert.ok(args.includes('review'));
  assert.ok(args.includes('002378'));
  assert.ok(args.includes('章源钨业'));
  assert.ok(args.includes('还能拿半年'));
});

test('POST /api/review returns 422 when kernel fails', async () => {
  const response = new FakeResponse();
  const kernel = async () => ({ code: 1, stdout: '', stderr: 'boom' });
  await handleRoute(
    makeRequest('POST', '/api/review', { symbol: '002378', name: 'x', text: 't' }),
    response,
    { kernel, dbPath: 'test.db' },
  );
  assert.equal(response.statusCode, 422);
  assert.equal(response.json().ok, false);
});

test('GET /api/observations returns the ok/items envelope the front-end reads', async () => {
  const response = new FakeResponse();
  const kernel = fakeKernel({
    ok: true,
    items: [{ id: 'obs_1', created_at: '2026-11-24T07:00:00Z', symbol: '002378' }],
  });
  await handleRoute(
    makeRequest('GET', '/api/observations'),
    response,
    { kernel, dbPath: 'test.db' },
  );
  assert.equal(response.statusCode, 200);
  const payload = response.json();
  // 前端 index.html 读的是 data.items —— 外壳不能变成裸数组
  assert.equal(payload.ok, true);
  assert.ok(Array.isArray(payload.items));
  assert.equal(payload.items[0].id, 'obs_1');
  assert.ok(kernel.calls[0].includes('list'));
});

test('GET /dashboard serves the injected client entry', async () => {
  const response = new FakeResponse();
  await handleRoute(
    makeRequest('GET', '/dashboard'),
    response,
    { clientEntry: '<html>注入的页面</html>', kernel: fakeKernel({}) },
  );
  assert.equal(response.statusCode, 200);
  assert.match(response.body, /注入的页面/);
});

test('POST /api/parse uses the injected parse helper', async () => {
  const response = new FakeResponse();
  const seen = [];
  const parseObservation = async (rawText) => {
    seen.push(rawText);
    return { ok: true, draft: { symbol: '002378' } };
  };
  await handleRoute(
    makeRequest('POST', '/api/parse', { text: '还能拿半年' }),
    response,
    { parseObservation, kernel: fakeKernel({}) },
  );
  assert.equal(response.statusCode, 200);
  assert.deepEqual(seen, ['还能拿半年']);
});

test('POST /api/save writes through the injected observation store', async () => {
  const response = new FakeResponse();
  const written = [];
  const readObservations = async () => [];
  const writeObservations = async (list) => {
    written.push(list);
  };
  await handleRoute(
    makeRequest('POST', '/api/save', { draft: { symbol: '002378' }, rawText: '还能拿半年' }),
    response,
    { readObservations, writeObservations, kernel: fakeKernel({}) },
  );
  assert.equal(response.statusCode, 200);
  assert.equal(written.length, 1);
  assert.equal(written[0][0].draft.symbol, '002378');
});
```

- [ ] **Step 2: 运行测试确认失败**

```bash
node --test miniapps/agaistock/test/api.test.mjs
```

Expected: FAIL —— `handleRoute` 未导出（当前 server.mjs 只有内联的 `handle`）

- [ ] **Step 3: 在 server.mjs 中加入内核调用与新路由**

在 `server.mjs` 顶部补充 import：

```javascript
import { spawn } from 'node:child_process';
import { join } from 'node:path';
```

在 `start()` 之前新增：

```javascript
const REPO_ROOT = join(import.meta.dirname, '..', '..', '..', '..');
const DEFAULT_DB = join(REPO_ROOT, 'data', 'agaistock.db');
const KERNEL_TIMEOUT_MS = 180000;

/**
 * 调用 Python 内核 CLI。
 *
 * Node 侧不碰 sqlite —— 数据库的唯一入口是内核（主规格 D3：接入层是唯一接口）。
 * 返回 {code, stdout, stderr}，不抛异常。
 * 带超时：三级别取数 + 点评可能跑很久，超时按失败处理，避免请求永久挂住。
 */
export function runKernel(args) {
  return new Promise((resolve) => {
    const child = spawn('python', ['-m', 'agaistock.cli', ...args], {
      cwd: REPO_ROOT,
      env: {
        ...process.env,
        PYTHONPATH: join(REPO_ROOT, 'src'),
        AGAISTOCK_DB: DEFAULT_DB,
      },
    });
    let stdout = '';
    let stderr = '';
    let settled = false;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      resolve(result);
    };
    const timer = setTimeout(() => {
      child.kill();
      finish({ code: -1, stdout, stderr: `内核调用超时（${KERNEL_TIMEOUT_MS}ms）` });
    }, KERNEL_TIMEOUT_MS);
    child.stdout.on('data', (chunk) => { stdout += chunk; });
    child.stderr.on('data', (chunk) => { stderr += chunk; });
    child.on('error', (error) => {
      clearTimeout(timer);
      finish({ code: -1, stdout: '', stderr: String(error.message) });
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      finish({ code: code ?? -1, stdout, stderr });
    });
  });
}

function parseKernelJson(stdout) {
  try {
    return JSON.parse(stdout);
  } catch {
    return null;
  }
}
```

把 `start()` 内部那个捕获了 `context` / `clientEntry` / `readObservations` / `writeObservations` /
`parseObservation` 的内联 `async function handle(request, response) {...}` **整段删掉**，
在**模块层级**新增导出的 `handleRoute`。依赖全部从 `options` 里取，取不到就用无副作用的默认值：

```javascript
/**
 * 路由处理。
 *
 * 依赖全部由调用方显式注入：模块层级上没有任何宿主对象被捕获，
 * 因此它既能在 start() 里跑，也能在测试里用 fake 依赖跑。
 */
export async function handleRoute(request, response, options = {}) {
  const {
    context = {},
    clientEntry = '',
    readObservations = async () => [],
    writeObservations = async () => {},
    parseObservation = async () => ({
      ok: false,
      error: 'UNAVAILABLE',
      message: '解析能力不可用。',
    }),
    kernel = runKernel,
    dbPath = DEFAULT_DB,
  } = options;

  const url = new URL(request.url ?? '/', 'http://miniapp.local');

  if (request.method === 'GET' && url.pathname === '/dashboard') {
    response.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
    response.end(clientEntry);
    return;
  }

  if (request.method === 'GET' && url.pathname === '/api/status') {
    sendJson(response, 200, {
      ok: true,
      agent: Boolean(context.agent),
      capabilities: {
        agentRun: context.capabilities?.has?.('agent.run') ?? null,
        speechTranscribe: context.capabilities?.has?.('speech.transcribe') ?? null,
        tool: context.capabilities?.has?.('tool') ?? null,
        hostConnector: context.capabilities?.has?.('hostConnector') ?? null,
      },
      observationCount: await countObservations(kernel, dbPath, readObservations),
    });
    return;
  }

  if (request.method === 'GET' && url.pathname === '/api/observations') {
    // 观察库以内核为准（删除也走内核，行 id 必须是内核行 id）
    const result = await kernel(['list', '--db', dbPath, '--json']);
    const payload = parseKernelJson(result.stdout);
    const items = Array.isArray(payload)
      ? payload
      : (payload && Array.isArray(payload.items) ? payload.items : []);
    // 前端读的是 data.items —— 这里必须保持 {ok, items} 外壳
    sendJson(response, 200, { ok: true, items });
    return;
  }

  if (request.method === 'POST' && url.pathname === '/api/parse') {
    const body = await readBody(request);
    const rawText = typeof body.text === 'string' ? body.text.trim() : '';
    if (!rawText) {
      sendJson(response, 400, { ok: false, error: 'EMPTY_INPUT', message: '先说点什么，或直接输入文字。' });
      return;
    }
    const result = await parseObservation(rawText);
    sendJson(response, result.ok ? 200 : 422, result);
    return;
  }

  if (request.method === 'POST' && url.pathname === '/api/save') {
    const body = await readBody(request);
    const draft = body.draft && typeof body.draft === 'object' ? body.draft : null;
    if (!draft) {
      sendJson(response, 400, { ok: false, error: 'INVALID_DRAFT', message: '没有可保存的观察卡。' });
      return;
    }
    const items = await readObservations();
    const record = {
      id: `obs_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`,
      createdAt: new Date().toISOString(),
      rawText: typeof body.rawText === 'string' ? body.rawText : '',
      draft: normalizeDraft(draft),
    };
    items.push(record);
    await writeObservations(items);
    sendJson(response, 200, { ok: true, id: record.id, total: items.length });
    return;
  }
```

紧接着（同一函数内）新增三条路由，放在 `/api/save` 之后、`404` 兜底之前：

```javascript
  if (request.method === 'POST' && url.pathname === '/api/review') {
    const body = await readBody(request);
    const text = typeof body.text === 'string' ? body.text.trim() : '';
    if (!text) {
      sendJson(response, 400, { ok: false, error: 'EMPTY_INPUT', message: '先说点什么。' });
      return;
    }
    const result = await kernel([
      'review',
      '--symbol', String(body.symbol ?? ''),
      '--name', String(body.name ?? ''),
      '--text', text,
      '--db', dbPath,
      '--json',
    ]);
    if (result.code !== 0) {
      sendJson(response, 422, {
        ok: false,
        error: 'KERNEL_FAILED',
        message: (result.stderr || '').slice(-500) || `exit=${result.code}`,
      });
      return;
    }
    const payload = parseKernelJson(result.stdout);
    if (!payload) {
      sendJson(response, 422, { ok: false, error: 'KERNEL_BAD_OUTPUT', message: result.stdout.slice(-300) });
      return;
    }
    sendJson(response, 200, payload);
    return;
  }

  if (request.method === 'GET' && url.pathname.endsWith('/reviews')) {
    const id = decodeURIComponent(url.pathname.slice('/api/observations/'.length, -'/reviews'.length));
    const result = await kernel(['reviews', id, '--db', dbPath, '--json']);
    const payload = parseKernelJson(result.stdout);
    sendJson(response, 200, payload ?? { observation_id: id, items: [] });
    return;
  }

  if (request.method === 'DELETE' && url.pathname.startsWith('/api/observations/')) {
    const id = decodeURIComponent(url.pathname.slice('/api/observations/'.length));
    const result = await kernel(['delete', id, '--db', dbPath, '--json']);
    if (result.code !== 0) {
      sendJson(response, 404, { ok: false, error: 'not_found', id });
      return;
    }
    sendJson(response, 200, { ok: true, id });
    return;
  }

  sendJson(response, 404, { error: 'not_found' });
}
```

再在模块层级加一个计数辅助函数（`/api/status` 用；内核不可用时回落到旧 JSON 文件观察库）：

```javascript
async function countObservations(kernel, dbPath, readObservations) {
  try {
    const result = await kernel(['list', '--db', dbPath, '--json']);
    const payload = parseKernelJson(result.stdout);
    if (payload && Array.isArray(payload.items)) return payload.items.length;
  } catch {
    // 内核不可用：回落到旧 JSON 文件观察库
  }
  return (await readObservations()).length;
}
```

最后把 `start()` 里的 server 创建改成**显式组装依赖**后调用 `handleRoute`
（原来的内联 `handle` 闭包已被删除）：

```javascript
  const server = createServer((request, response) => {
    void handleRoute(request, response, {
      context,
      clientEntry,
      readObservations,
      writeObservations,
      parseObservation,
      kernel: runKernel,
      dbPath: DEFAULT_DB,
    }).catch(() => {
      if (!response.headersSent) sendJson(response, 500, { error: 'internal_error' });
    });
  });
```

**路由顺序注意**：`GET /api/observations/:id/reviews` 必须放在通用的 `GET /api/observations` 之前判断，否则会被先匹配掉。

- [ ] **Step 4: 运行测试确认通过**

```bash
node --test "miniapps/agaistock/test/*.test.mjs"
```

> 注意：`node --test <目录>` 在本机（Node 24 + Windows）会把目录当成模块解析而报
> `Cannot find module ...\miniapps\agaistock\test`。必须用 glob 形式。

Expected: 全部 PASS —— 既有 `pipeline.test.mjs` 23 条 + 新增 `api.test.mjs` 10 条

- [ ] **Step 5: toolAccess 保持不声明**

当前实现用 spawn CLI 调用内核，**不需要** `toolAccess`。因此 `miniapp/miniapp.json` **保持不变**：

```json
// miniapp/miniapp.json 保持不变 —— 不加 toolAccess
```

若后续改为 `context.tool` 方式调用，必须**先探测成功**再声明 `"toolAccess": ["call"]`，不得在探测前声明。

- [ ] **Step 6: Commit**

```bash
git add miniapps/agaistock/miniapp/node/server.mjs miniapps/agaistock/test/api.test.mjs
git commit -m "feat: mini app api for review, reviews and soft delete"
```

---

### Task 15: Mini App 前端 —— 点评展示、评分展示、删除

**Files:**
- Modify: `miniapps/agaistock/miniapp/client/index.html`
- Create: `miniapps/agaistock/miniapp/client/render.mjs`（与 `index.html` 同目录，`index.html` 用 `./render.mjs` 相对引用）
- Create: `miniapps/agaistock/test/render.test.mjs`

**Interfaces:**
- Consumes: Task 14 的 API
- 复权口径提醒（Global Constraint 16/18）：点评里的中枢 / 支撑压力 / 证伪位都是**后复权空间**的价位。
  展示时若要让用户和行情软件里的现价对照，**必须**用复权因子换算（`(后复权价 − 复权常数) / 复权因子`），
  或在文案里明确标注「后复权」口径 —— 不要把后复权价位直接当成现价呈现。
- Produces:
  - `miniapps/agaistock/miniapp/client/render.mjs` 导出四个纯函数：
    - `renderReviews(reviews: Array) -> string` —— 点评师意见区块 HTML
    - `renderScore(score: object) -> string` —— 评分区块 HTML
    - `renderHorizon(plan: object) -> string` —— 观察期区块 HTML
    - `renderObservationRows(items: Array) -> string` —— 观察库表格行 HTML。
      入参是**内核行**（`id` / `created_at` / `symbol` / `name` / `direction` / `thesis` / `confidence`），
      每行带一个 `data-delete-observation="<id>"` 的删除按钮。
  - UI：
    - 解析区新增「清空」按钮
    - 观察卡区下方新增「点评师意见」折叠区
    - 新增「评分」区（五维 + 贡献来源 + `no_reviewer` 明示）
    - 新增「观察期」区
    - 观察库表格每行新增「删除」按钮（表头加一列「操作」）

**观察库的数据源变了**：Task 14 之后 `/api/observations` 走内核 `list --json`，
返回的行是**内核行**（`id` / `created_at` / `symbol` / …），不再是旧的
`{createdAt, draft}` JSON 文件记录。因此表格渲染与删除按钮都必须按内核行来写：
删除用的 id 是内核行 id（`data-delete-observation`），删除请求打到内核 `delete`。
旧 JSON 文件观察库（`observations.json`）保留给 `/api/save` 兼容，但不再是列表的数据源。

**加载顺序保证**：`render.mjs` 用 `<script type="module" src="./render.mjs">` 引入。module 脚本是 **deferred** 的，在 DOM 解析完成后、且早于 `DOMContentLoaded` 执行；而 `index.html` 里主 `<script>` 中的保存动作是**用户点击触发的异步流程**，那时 module 必定已加载完毕。因此 `window.agaistockRender` 一定可用。

> `render.mjs` 里**不能**在模块顶层直接写 `window.agaistockRender = …`：
> Node 没有 `window`，`import` 该模块就会抛 `ReferenceError: window is not defined`，
> 测试在跑第一条用例之前就全挂。挂载必须放在 `typeof window !== 'undefined'` 保护里。

- [ ] **Step 1: 写失败的前端渲染测试**

`miniapps/agaistock/test/render.test.mjs`：

```javascript
import assert from 'node:assert/strict';
import test from 'node:test';

import { renderReviews, renderScore, renderHorizon, renderObservationRows } from '../miniapp/client/render.mjs';

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

test('renderObservationRows puts the kernel row id on the delete button', () => {
  const html = renderObservationRows([
    { id: 'obs_1', created_at: '2026-11-24T07:00:00Z', symbol: '002378', thesis: 't' },
  ]);
  assert.match(html, /data-delete-observation="obs_1"/);
});
```

- [ ] **Step 2: 运行测试确认失败**

```bash
node --test miniapps/agaistock/test/render.test.mjs
```

Expected: FAIL —— `../miniapp/client/render.mjs` 不存在

- [ ] **Step 3: 新建 `miniapps/agaistock/miniapp/client/render.mjs`**

> 为了让渲染逻辑可测，把纯渲染函数抽到独立模块；`index.html` 通过 `<script type="module" src="./render.mjs">` 引入。

```javascript
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

    const invalidations = (review.proposed_invalidation || []).map((p) => `
      <li class="invalidation">
        <span>${escapeHtml(p.desc)}</span>
        <button type="button" data-adopt-invalidation="${escapeHtml(p.desc)}">采纳</button>
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
  return `
    <div class="horizon-main">
      <strong>${escapeHtml(plan.review_at)}</strong>
      <span class="muted">（档位 ${escapeHtml(plan.tier || '默认')}）</span>
    </div>
    <p class="muted">${escapeHtml(plan.rationale || '')}</p>
    ${checks ? `<div class="horizon-checks"><h4>到期检查项</h4><ul>${checks}</ul></div>` : ''}`;
}

const DIRECTION_LABEL = { bullish: '看多', bearish: '看空', neutral: '中性' };

/**
 * 观察库表格行。
 *
 * 入参是**内核行**（Task 14 之后 /api/observations 走内核 list --json）：
 * id / created_at / symbol / name / direction / thesis / confidence。
 * 删除按钮把内核行 id 放在 data-delete-observation 上，由 index.html 事件委托取出。
 */
export function renderObservationRows(items) {
  if (!Array.isArray(items) || items.length === 0) return '';
  return items.map(function (item) {
    const when = item.created_at ? new Date(item.created_at) : null;
    const timeText = when && !Number.isNaN(when.getTime())
      ? when.toLocaleString('zh-CN', { hour12: false })
      : (item.created_at || '');
    const dir = 'dir-' + (item.direction || 'neutral');
    const label = DIRECTION_LABEL[item.direction] || item.direction || '中性';
    const invalidation = Array.isArray(item.invalidation) ? item.invalidation : [];
    return '<tr>'
      + '<td class="num">' + escapeHtml(timeText) + '</td>'
      + '<td class="num">' + escapeHtml((item.symbol || '—') + (item.name ? ' ' + item.name : '')) + '</td>'
      + '<td>' + escapeHtml(item.thesis || '（未提取）') + '</td>'
      + '<td><span class="tag ' + dir + '">' + escapeHtml(label) + '</span></td>'
      + '<td class="num">' + Math.round((item.confidence || 0) * 100) + '%</td>'
      + '<td>' + (invalidation.length
          ? escapeHtml(invalidation.join('；'))
          : '<span style="color:var(--mcode-warning)">缺失</span>') + '</td>'
      + '<td><button type="button" class="ghost small" data-delete-observation="'
        + escapeHtml(item.id || '') + '">删除</button></td>'
      + '</tr>';
  }).join('');
}

// 供 index.html 的主脚本调用（module 脚本是 deferred，用户点击时必定已就绪）。
// Node 里没有 window —— 直接赋值会让 import 该模块的测试在第一条用例前就抛
// ReferenceError，所以必须先判断。
if (typeof window !== 'undefined') {
  window.agaistockRender = { renderReviews, renderScore, renderHorizon, renderObservationRows };
}
```

- [ ] **Step 4: 在 `index.html` 接入**

现有主脚本里已有的变量名（**直接复用，不要另起名字**）：

- `var rawText = document.getElementById('raw-text');`
- `var cardPanel = document.getElementById('card-panel');`
- `var obsCount = document.getElementById('obs-count');`
- `var obsRows = document.getElementById('obs-rows');`
- `var runtimeState = { speech: null, agent: null, count: 0 };`
- **草稿变量叫 `currentDraft`（不是 `draft`）** —— 写错名字会直接抛
  `ReferenceError: draft is not defined`，保存与清空流程整条断掉。
- localStorage 的 key 是 `'agaistock.draft'`（存的是 `rawText.value`，不是草稿对象）。

(a) 在 `</body>` 之前引入 module：

```html
<script type="module" src="./render.mjs"></script>
```

(b) 在现有 `<section>` 之后新增三个区块：

```html
<section aria-labelledby="h-reviews" id="reviews-section" hidden>
  <h2 id="h-reviews">点评师意见</h2>
  <div id="reviews-list"></div>
</section>
<section aria-labelledby="h-score" id="score-section" hidden>
  <h2 id="h-score">评分</h2>
  <div id="score-body"></div>
</section>
<section aria-labelledby="h-horizon" id="horizon-section" hidden>
  <h2 id="h-horizon">观察期</h2>
  <div id="horizon-body"></div>
</section>
```

(c) 「存进观察库」按钮的点击处理改为：先 `POST /api/review`，成功后用返回的 `reviews` / `score` / `horizon` 渲染三块区域：

```javascript
    // 保存并点评（草稿变量是 currentDraft）
    var payload = {
      symbol: (currentDraft && currentDraft.symbol) || '',
      name: (currentDraft && currentDraft.name) || '',
      text: rawText.value
    };
    var resp = await fetch('/api/review', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload)
    });
    var data = await resp.json();
    if (!resp.ok || data.ok === false) {
      setStatus(recordStatus, '点评失败：' + (data.message || data.error || resp.status), 'error');
      return;
    }
    var r = window.agaistockRender;
    document.getElementById('reviews-list').innerHTML = r.renderReviews(data.reviews || []);
    document.getElementById('score-body').innerHTML = r.renderScore(data.score);
    document.getElementById('horizon-body').innerHTML = r.renderHorizon(data.horizon);
    document.getElementById('reviews-section').hidden = false;
    document.getElementById('score-section').hidden = false;
    document.getElementById('horizon-section').hidden = false;
```

> `setStatus` 在现有脚本里的签名是 `setStatus(node, text, tone)`，
> 要设置状态必须传节点（`recordStatus`），不能只传两个参数。

(d) 观察库表格：**渲染改成内核行**，删除按钮用**内核行 id**。

现有渲染器遍历的是 `items.map(function (item) {…})`，元素形如 `{createdAt, draft}`；
Task 14 之后 `/api/observations` 返回的是**内核行**（`id` / `created_at` / `symbol` / `name` /
`direction` / `thesis` / `confidence`），`item.draft` 不存在了。
所以表格行改由 `render.mjs` 的纯函数渲染（可测），删除按钮的 id 放在
`data-delete-observation` 上，由 `obsRows` 上的事件委托取出。

先给表头加一列「操作」：

```html
                <tr>
                  <th scope="col">时间</th>
                  <th scope="col">标的</th>
                  <th scope="col">主张</th>
                  <th scope="col">方向</th>
                  <th scope="col">信心</th>
                  <th scope="col">证伪条件</th>
                  <th scope="col">操作</th>
                </tr>
```

再把 `loadObservations()` 里的 `obsRows.innerHTML = items.map(…)` 换成：

```javascript
              obsRows.innerHTML = window.agaistockRender.renderObservationRows(items);
```

删除按钮的事件委托（挂在 `obsRows` 上，行是重绘的，不能把监听器绑在单个按钮上）：

```javascript
        obsRows.addEventListener('click', function (event) {
          var button = event.target && event.target.closest
            ? event.target.closest('[data-delete-observation]')
            : null;
          if (!button) return;
          var id = button.getAttribute('data-delete-observation');
          if (!id) return;
          if (!confirm('删除后该观察不再参与评分与校准统计，确定吗？')) return;
          fetch('/api/observations/' + encodeURIComponent(id), { method: 'DELETE' })
            .then(function (res) {
              if (res.ok) {
                loadObservations();
              } else {
                setStatus(recordStatus, '删除失败。', 'error');
              }
            })
            .catch(function () { setStatus(recordStatus, '删除失败。', 'error'); });
        });
```

(e) 解析区新增「清空」按钮（放在「解析成观察卡」旁边）：

```javascript
    function clearDraft() {
      rawText.value = '';
      currentDraft = null;
      cardPanel.innerHTML = '';
      document.getElementById('reviews-section').hidden = true;
      document.getElementById('score-section').hidden = true;
      document.getElementById('horizon-section').hidden = true;
      try { localStorage.removeItem('agaistock.draft'); } catch (e) { /* 忽略 */ }
    }
```

> 注意：草稿变量是 `currentDraft`，localStorage 的 key 是 `'agaistock.draft'`（存的是 `rawText.value`）。
> 这两个名字都以现有 `index.html` 的实际写法为准 —— 实现时先读 `index.html` 里的草稿存取代码，沿用同样的 key。

- [ ] **Step 5: 运行测试确认通过**

```bash
node --test "miniapps/agaistock/test/*.test.mjs"
```

Expected: 全部 PASS —— `pipeline.test.mjs` 23 条 + `api.test.mjs` 10 条 + `render.test.mjs` 8 条

- [ ] **Step 6: Commit**

```bash
git add miniapps/agaistock/miniapp/client miniapps/agaistock/test
git commit -m "feat: mini app reviewer opinions, score breakdown, horizon and delete"
```

---

### Task 16: 端到端实测

**Files:**
- Modify: `miniapps/agaistock/miniapp/client/index.html`（实测中发现的样式/交互修复）
- Create: `docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md` 的实测小节（如需追加）

**Interfaces:**
- Consumes: 全部前置任务
- Produces: 一份可复现的实测结论

- [ ] **Step 1: 重新发布 Mini App**

```bash
node --check miniapps/agaistock/miniapp/node/server.mjs
```

Expected: exit 0

然后用 `miniapp` 工具：

```
miniapp { action: "publish", pluginId: "agaistock" }
miniapp { action: "open",    pluginId: "agaistock" }
```

Expected: runtime `running`，open 成功。

- [ ] **Step 2: 在 Browser 中验证全链路**

用 `mcp_browser` 的 `inspect` 打开页面后：

1. 填入口述文本：`章源钨业我看了三年了，钨价从去年就开始涨，公司储量排前列，明年上半年产量能翻倍。我觉得还能拿半年。`
2. 点击「解析成观察卡」→ 确认观察卡渲染正常
3. 点击「存进观察库」→ 确认：
   - 「点评师意见」区出现 `anchor-chanlun`
   - 至少 1 条 finding，且显示 `dimension` 与 `delta`
   - 「建议的证伪条件」区块：本轮结构识别出了中枢就出现且带「采纳」按钮；
     若本次结构里没有任何可用中枢（薄结构），该区块可以为空 —— 这时记进实测结论，
     不要把「没有证伪位」当成 bug（证伪位来自中枢上下沿，没有中枢就没有位）
   - 「判读限制」区块出现 caveats
   - 「评分」区显示总分 + 五维，其中无人点评的维度显示「无人点评」
   - 「观察期」区显示日期与档位
4. 查询 console 应无错误

- [ ] **Step 3: 验证删除**

1. 在观察库某行点「删除」→ 确认弹出提示
2. 确认后该行从列表消失
3. `python -m agaistock.cli list --db data/agaistock.db --include-deleted` 应能看到该行且标记为已删除
4. `python -m agaistock.cli list --db data/agaistock.db` 不应包含它

- [ ] **Step 4: 验证重启恢复**

```bash
miniapp { action: "publish", pluginId: "agaistock" }
miniapp { action: "open",    pluginId: "agaistock" }
```

Expected: 观察库与点评结论仍在（持久化跨重启生效）

- [ ] **Step 5: 跑全量测试**

```bash
python -m unittest discover -s tests -t . -v
node --test "miniapps/agaistock/test/*.test.mjs"
node tools/check-spec.mjs
node tools/check-spec.mjs docs/superpowers/plans/2026-11-24-reviewer-layer-and-chanlun-reviewer.md --external docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md
```

Expected: 全部通过。

> `discover` 必须带 `-t .`：少了它，测试模块会以顶层名 `test_registry` 被导入，
> 而 `tests/test_registry.py` 里的注册表又按 `tests.test_registry` 导入自己，
> 同一个类被加载两次 → `assertIsInstance` 失败（`test_registry` 2 条）。
> `node --test` 必须用 glob 形式：目录形式在本机会报
> `Cannot find module ...\miniapps\agaistock\test`。

- [ ] **Step 6: 把实测结论写回设计文档**

在设计文档末尾追加一节「实测结论（2026-11-24）」，记录：实际取到的缠论结构摘要、实际产生的 findings 列表、评分与观察期输出、删除与重启恢复的验证结果、以及**任何与本设计不一致的实际行为**（不一致必须改设计，不能改事实）。

- [ ] **Step 7: Commit**

```bash
git add miniapps/agaistock/miniapp/client docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md
git commit -m "docs: record end-to-end verification results for reviewer layer"
```

> **不要用 `git add -A`**（Global Constraint 14）：实测过程中可能有并行子代理的中间文件，
> 一把全加会把别人的半成品一起提交。只 add 上面这两个路径。

---

## Appendix A: 常用命令速查

```bash
# 安装（editable）
python -m pip install -e .

# Python 单测
python -m unittest discover -s tests -t . -v
python -m unittest tests.test_scoring -v

# Node 单测
node --test "miniapps/agaistock/test/*.test.mjs"

# 语法检查
node --check miniapps/agaistock/miniapp/node/server.mjs

# 文档自检
node tools/check-spec.mjs
node tools/check-spec.mjs docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md --external docs/superpowers/specs/2026-11-24-stock-review-app-architecture.md
node tools/check-spec.mjs docs/superpowers/plans/2026-11-24-reviewer-layer-and-chanlun-reviewer.md --external docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md

# 端到端
python -m agaistock.cli review --symbol 002378 --name 章源钨业 --text "还能拿半年"
python -m agaistock.cli list
python -m agaistock.cli delete <observation_id>

# 连接器覆盖度探测
node tools/probe/run-probe.mjs --symbol 002378 --name 章源钨业 --setcode 0
```

## Appendix B: 已知风险与对应任务

| 风险 | 对应任务 | 缓解 |
|---|---|---|
| 缠论三级别取数耗时（3 次 tdx_kline + 3 次 Python 分析） | Task 13/14/15 | 内核调用带超时（Task 14 `runKernel` 180s，超时按失败返回）；观察卡先落盘，点评失败不影响记录 |
| 上游缠论脚本与当前 `tdx_kline` 结构不兼容 | Task 6 | 新写适配器，不改上游；Task 6 Step 5 用真实数据验证 |
| 上游脚本在 Python 3.11 可能有语法/行为差异 | Task 7 | Task 7 Step 6 用真实标的跑通三级别 |
| LLM 篡改判定字段 | Task 9 | 受保护字段校验，篡改即丢弃 |
| 点评师打乱评分口径 | Task 11 | 维度固定在 `config/scoring.json` |
| 点评结论丢失 | Task 2/4 | 每次运行都落库，失败隔离 |
| Mini App Node entry 不保活 | Task 13/14/15 | 状态持续落 SQLite，重启恢复已在 Task 16 验证 |
