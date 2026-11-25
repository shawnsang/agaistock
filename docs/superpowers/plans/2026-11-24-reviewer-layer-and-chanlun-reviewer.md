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

- [x] **Step 7: Commit**

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
            # 已被 Task 20 取代（见 Task 20 小节）：改用 config.data_dir()，
            # 运行期数据落宿主的 context.dataDir，不落插件包（安装产物）
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
            print(f"评分 {score['total']:.1f} / 100（被审维度：{'、'.join(score['scored_dimensions']) or '无'}，分母 {score['score_denominator']:.2f}）")
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

再补两条覆盖「前端渲染模块」这一路（Task 15 把渲染逻辑拆到独立文件后，
页面靠 `<script type="module" src="./render.mjs">` 引入；服务端不提供这条路由就会整页静默失效）：

```javascript
test('GET /render.mjs serves the front-end module with a javascript content type', async () => {
  const response = new FakeResponse();
  await handleRoute(
    makeRequest('GET', '/render.mjs'),
    response,
    { renderModule: 'export const renderScore = () => "";\n', kernel: fakeKernel({}) },
  );
  assert.equal(response.statusCode, 200);
  assert.match(response.headers['content-type'], /javascript/);
  assert.match(response.body, /renderScore/);
});

test('GET /render.mjs returns 404 when the module was not loaded', async () => {
  const response = new FakeResponse();
  await handleRoute(
    makeRequest('GET', '/render.mjs'),
    response,
    { kernel: fakeKernel({}) },
  );
  assert.equal(response.statusCode, 404);
});
```

> 「`miniapp/client/render.mjs` 确实存在且导出了约定的四个函数」由 Task 15 的
> `render.test.mjs` 顶住（它 `import { renderReviews, renderScore, renderHorizon, renderObservationRows } from '../miniapp/client/render.mjs'`，
> 文件缺失时 import 直接抛错、整份测试文件全挂）。这里**不要**再重复一遍 ——
> Task 14 排在前、文件是 Task 15 才建的，在 Task 14 里断言文件存在会让线性执行直接失败。

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
    renderModule = '',
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

  // 前端渲染模块是**第二个静态文件**（Task 15 把 render.mjs 从 index.html 里拆出来）。
  // 宿主只把 index.html 交给 Node 进程（surface.path 是页面入口，不是静态文件服务器），
  // server.mjs 也只路由 /dashboard 与 /api/*，其余一律 404 ——
  // 不显式提供这条路由，浏览器里的 `<script type="module" src="./render.mjs">`
  // 会拿到 404，window.agaistockRender 根本不存在，整页静默失效。
  // 只白名单这一个文件，不做通用静态服务（避免路径穿越）。
  if (request.method === 'GET' && url.pathname === '/render.mjs') {
    if (!renderModule) {
      sendJson(response, 404, { error: 'not_found' });
      return;
    }
    response.writeHead(200, { 'content-type': 'text/javascript; charset=utf-8' });
    response.end(renderModule);
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
  // Task 15 把渲染逻辑拆到 render.mjs，页面用 <script type="module" src="./render.mjs"> 引入。
  // 宿主只把 index.html 交给 Node 进程（surface.path 是页面入口，不是静态文件服务器），
  // 所以 render.mjs 必须由本服务自己提供，否则页面里的 module 脚本 404、整页静默失效。
  // 读不到文件时降级成空字符串 —— 让 start() 抛错会把整个 Mini App 拖到起不来。
  let renderModule = '';
  try {
    renderModule = await readFile(join(context.pluginRoot, 'miniapp/client/render.mjs'), 'utf8');
  } catch {
    renderModule = '';
  }

  const server = createServer((request, response) => {
    void handleRoute(request, response, {
      context,
      clientEntry,
      renderModule,
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

Expected: 全部 PASS —— 既有 `pipeline.test.mjs` 23 条 + 新增 `api.test.mjs` 12 条

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

- [x] **Step 1: 重新发布 Mini App**

```bash
node --check miniapps/agaistock/miniapp/node/server.mjs
```

Expected: exit 0

然后用 `miniapp` 工具：

```
# publish 前先清掉插件包里的运行产物（宿主会把 gitignored 产物一并拷进安装目录）
python tools/clean-package-artifacts.py

miniapp { action: "publish", pluginId: "agaistock", sourcePath: "<repo>/miniapps/agaistock" }
miniapp { action: "open",    pluginId: "agaistock" }
```

Expected: runtime `running`，open 成功。

> ⚠️ **`clean-package-artifacts.py` 不能省**：在插件包目录里直跑内核且不带
> `AGAISTOCK_DB` / `AGAISTOCK_DATA_DIR` 时，`config.data_dir()` 回落到
> `repo_root()/"data"`（插件包副本里的 `repo_root()` 就是**包根**）⇒ 写出包内
> `data/agaistock.db`（空库）。而**宿主会把 gitignored 产物一并拷进安装目录**
> （实测仓库插件包与宿主持久安装目录的同名 24 个 `.pyc` **mtime 24/24 完全相同**；
> 至于「有多少个早于解包时刻」**随解包批次变化**，**不要**把某个固定数字当证据）⇒ 该空库随 publish 进安装产物，
> 宿主侧读到 0 行、真实数据却在 `context.dataDir` 的库里 → 用户会以为「一条观察都没有」。
> `python tools/clean-package-artifacts.py --check` 只检查、发现残留时退出码 1。

- [x] **Step 2: 在 Browser 中验证全链路**

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

- [x] **Step 3: 验证删除**

1. 在观察库某行点「删除」→ 确认弹出提示
2. 确认后该行从列表消失
3. `python -m agaistock.cli list --db data/agaistock.db --include-deleted` 应能看到该行且标记为已删除
4. `python -m agaistock.cli list --db data/agaistock.db` 不应包含它

- [x] **Step 4: 验证重启恢复**

```bash
miniapp { action: "publish", pluginId: "agaistock", sourcePath: "<repo>/miniapps/agaistock" }
miniapp { action: "open",    pluginId: "agaistock" }
```

Expected: 观察库与点评结论仍在（持久化跨重启生效）

- [x] **Step 5: 跑全量测试**

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

- [x] **Step 6: 把实测结论写回设计文档**

在设计文档末尾追加一节「实测结论（2026-11-24）」，记录：实际取到的缠论结构摘要、实际产生的 findings 列表、评分与观察期输出、删除与重启恢复的验证结果、以及**任何与本设计不一致的实际行为**（不一致必须改设计，不能改事实）。

- [x] **Step 7: Commit**

```bash
git add docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md docs/superpowers/specs/2026-11-24-stock-review-app-architecture.md docs/superpowers/plans/2026-11-24-reviewer-layer-and-chanlun-reviewer.md
git commit -m "docs: record end-to-end verification results for reviewer layer"
```

> **不要用 `git add -A`**（Global Constraint 14）：实测过程中可能有并行子代理的中间文件，
> 一把全加会把别人的半成品一起提交。只 add 上面这三个路径。

> **实测前置**：本任务的 Step 2/3/4 必须在 **Task 17** 之后跑。
> 首次实测（2026-11-24）暴露了两个阻塞缺陷 —— 安装后的插件包**不含 Python 内核**，
> 且 `server.mjs` 的内核桥接路径在「插件不在仓库里」时全部落空，
> 内核失败还被吞成「观察库为空」。这两个缺陷的修复见 Task 17。

---

**Task 16 完成注记（2026-11-24）**

全部 7 个 Step 已实跑通过，结论写在设计文档 **§16「端到端实测结论（2026-11-24）」**。

与本计划的三处偏离（**以实跑事实为准，已改设计**）：

1. **Step 3 的 DB 路径不是 `data/agaistock.db`**：Task 17 之后运行数据落
   `context.dataDir`（实测 `…\.minimax\v2\plugin-data\liveboards\agaistock\agaistock.db`）。
   实跑时用**安装副本自带的内核**核对了软删除语义：
   `list --include-deleted` 输出两行且被删行标「（已删除）」，默认 `list` 只输出一行。
2. **Step 1 的 `miniapp publish` 必须给 `sourcePath`**：只给 `pluginId` 时发布的是
   宿主缓存里的旧副本；实测 `restart` 也不能更新已安装副本（D29）。
3. **Step 6 的产出位置**：不是追加一节，而是新增 **§16**（4 个子节），
   并顺带把 §3.1 目录结构订正为 as-built、§15 交付清单勾选。

**实测额外挖出并已修掉的缺陷**：安装包不含内核、内核失败被吞成空列表（Task 17）；
GBK 编码崩溃、观察期落点可能落在周日（Task 18）；结构化观察没有落库、
`reviewer_version` 空串（Task 19）。

---

### Task 17: Mini App 安装包自包含 —— 内核随包走 + 内核桥接路径与失败可见性

> **来源**：Task 16（端到端实测）实测暴露的两个阻塞缺陷。
> 这个任务不新增业务能力，只让**已实现的能力在交付形态下真的能用**。

**缺陷一（Critical）：安装后的插件包里没有 Python 内核。**

宿主安装的是**整个 Mini App 包目录**（`miniapps/agaistock/`），安装后
`~/.minimax/plugins/agaistock/` 就是运行时的代码根。但包里只有
`miniapp/`（页面 + Node 入口）、`test/`、`package.json`、`icon.png` ——
**没有 `src/agaistock`，也没有 `config/`**。

于是 `python -m agaistock.cli` 在开发机能跑通，**只因为本机做过 editable 安装**
（`pip show agaistock` → `Location: ...\site-packages`，模块实际指向
`D:\workroom\agaistock\src\agaistock`）。换一台机器、或仓库挪个位置，
这个 import 立刻失效 —— 点评、评分、观察期全部不可用。

> **还有一个更隐蔽的坑**：editable 安装注册的是 **meta-path finder**，
> 优先级**高于** `PYTHONPATH`。实测：不加 `python -S` 时，即使 `PYTHONPATH`
> 指向插件自带的 `src`，`import agaistock` 命中的仍是 editable 安装那份。
> 所以「把内核复制进包里」必须配 `python -S` 才算数 ——
> `-S` 禁用 site-packages，既保证用包内那份，也把
> 「业务内核零第三方依赖」（Global Constraint 2）变成运行时硬约束。

**缺陷二（Critical）：内核桥接的路径推导只在「插件位于仓库内」时成立。**

`server.mjs` 原来写死：

```javascript
const REPO_ROOT = join(import.meta.dirname, '..', '..', '..', '..');
```

「向上 4 级」隐含了「插件根正好在仓库根下两层」这个前提。工作区里成立
（`miniapps/agaistock/miniapp/node` → 仓库根），**安装后不成立**：
`~/.minimax/plugins/agaistock/miniapp/node` 向上 4 级落到 `~/.minimax`，
于是 `PYTHONPATH=~/.minimax/src` 与 `DEFAULT_DB=~/.minimax/data/agaistock.db`
全部指向不存在的目录。实测安装副本里的 `GET /api/observations` 返回
`{"ok":true,"items":[]}` —— **内核根本没跑起来，界面却显示「一条观察都没有」。**

**缺陷三（Important）：内核失败被吞成「空列表」。**

`/api/observations` 不检查内核退出码，`stdout` 为空就得到 `items: []`。
用户看到的是「没有观察记录」，真实原因（Python 缺失 / 内核崩了 / 库打不开）
被彻底吞掉。`countObservations` 更进一步：内核不可用时**回落到旧 JSON 文件观察库**，
于是头部徽标显示 2 条、表格却显示 0 条，两个数字互相打架。

**Files:**
- Create: `tools/sync-kernel.py`（内核同步脚本）
- Create: `miniapps/agaistock/src/agaistock/**`（内核副本，由脚本生成）
- Create: `miniapps/agaistock/config/scoring.json`、`miniapps/agaistock/config/reviewers.json`（配置副本，由脚本生成）
- Create: `tests/test_kernel_vendor.py`（漂移守卫 + 自包含性测试）
- Modify: `miniapps/agaistock/miniapp/node/server.mjs`
- Modify: `miniapps/agaistock/miniapp/client/index.html`
- Modify: `miniapps/agaistock/test/api.test.mjs`

**Interfaces:**
- Consumes: `src/agaistock/**`、`config/*.json`（仓库内的权威副本）
- Produces:
  - `tools/sync-kernel.py [--check]` —— 同步 / 校验内核副本
  - `server.mjs` 导出 `runKernel(args, options)`，`options = {cwd, pythonPath, dbPath}`

> **为什么不把内核「搬进」插件包（改 `src/` 的位置）**：那会连带改
> `pyproject.toml`、editable 安装、`config.repo_root()` 语义、`data/` 位置，
> 以及计划与交接文档里成百上千处 `src/agaistock/...` 路径引用 ——
> 在 16 个任务全部落地、138 条 Python 测试全绿之后做这种大重构，风险远大于收益。
> **复制 + 漂移守卫**沿用本项目已有的上游 vendor 约定
> （`skills/anchor_chanlun/vendor/chanlun-core/**` 就是整目录拷贝 + SHA-256 一致性校验）。

- [ ] **Step 1: 写内核同步脚本 `tools/sync-kernel.py`**

```python
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
```

- [ ] **Step 2: 生成内核副本**

```bash
python tools/sync-kernel.py
python tools/sync-kernel.py --check
```

Expected: 第一条输出「已同步内核到 Mini App 包。」；第二条输出「内核副本与源一致。」，退出码 0。

生成后 `miniapps/agaistock/src/agaistock/` 与 `miniapps/agaistock/config/` 必须存在，
且**不含** `__pycache__` 与 `*.pyc`。

- [ ] **Step 3: 写漂移守卫与自包含性测试 `tests/test_kernel_vendor.py`**

```python
"""内核随包走的漂移守卫。

宿主安装的是整个 Mini App 包目录，所以 `miniapps/agaistock/src/agaistock` 与
`miniapps/agaistock/config` 必须是仓库里 `src/agaistock`、`config` 的**逐字节副本**。
副本漂了就等于交付了一个和仓库不一致的内核 —— 开发机上 CLI 用新内核、
安装后的 Mini App 用旧内核，两边行为不一致。

修法：python tools/sync-kernel.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "miniapps" / "agaistock"
SYNC = ROOT / "tools" / "sync-kernel.py"


class KernelVendorTest(unittest.TestCase):
    def test_vendored_kernel_matches_source(self):
        result = subprocess.run(
            [sys.executable, str(SYNC), "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(
            result.returncode,
            0,
            "内核副本与源不一致：\n" + result.stdout + result.stderr
            + "\n修复：python tools/sync-kernel.py",
        )

    def test_vendored_kernel_is_self_contained(self):
        """用插件根当 cwd、插件内 src 当 PYTHONPATH，必须能独立跑起来。

        这正是安装后的运行方式：PYTHONPATH 指向插件自己的 src，
        config 也从插件根读。不依赖 editable 安装。

        **必须带 `-S`**：editable 安装注册的是 meta-path finder，优先级高于
        PYTHONPATH —— 不带 `-S` 时这里会命中仓库里那份，测了个寂寞。
        """
        env = dict(os.environ)
        env["PYTHONPATH"] = str(PLUGIN_ROOT / "src")
        env.pop("AGAISTOCK_DB", None)
        result = subprocess.run(
            [
                sys.executable,
                "-S",
                "-c",
                "import agaistock, agaistock.config as c;"
                "print(agaistock.__file__);"
                "print(c.repo_root());"
                "print(len(c.load_scoring()['dimensions']))",
            ],
            cwd=PLUGIN_ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        self.assertGreaterEqual(len(lines), 3, result.stdout)
        # 必须导入的是插件里的那份副本，不是仓库里的 editable 安装
        self.assertIn("miniapps", lines[0], result.stdout)
        self.assertNotIn("site-packages", lines[0], result.stdout)
        # repo_root 必须落在插件根上，配置才能从插件内读到
        self.assertEqual(Path(lines[1]).resolve(), PLUGIN_ROOT.resolve(), result.stdout)
        # 五个评分维度必须读得到
        self.assertEqual(lines[2].strip(), "5", result.stdout)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: 改 `server.mjs` 的路径推导与内核调用**

**4.1** 把模块顶层的常量改成按**插件根**推导：

```javascript
// 插件根：<plugin>/miniapp/node -> <plugin>/miniapp -> <plugin>
// **不能**用「向上 4 级」：那只在插件位于仓库内时成立。安装后插件根在
// ~/.minimax/plugins/<id>/，向上 4 级会落到插件目录之外，内核与配置全找不到。
const PLUGIN_ROOT = join(import.meta.dirname, '..', '..');
const KERNEL_SRC = join(PLUGIN_ROOT, 'src');
const KERNEL_TIMEOUT_MS = 180000;
```

（删掉原来的 `REPO_ROOT` 与 `DEFAULT_DB` 两行。`DEFAULT_DB` 的职责改由
`start()` 从宿主给的 `context.dataDir` 决定 —— 运行数据属于运行时，不属于安装产物。）

**4.2** `runKernel` 接受可注入的运行参数：

```javascript
export function runKernel(args, options = {}) {
  const cwd = options.cwd || PLUGIN_ROOT;
  const pythonPath = options.pythonPath || KERNEL_SRC;
  const dbPath = options.dbPath || '';
  return new Promise((resolve) => {
    const env = { ...process.env, PYTHONPATH: pythonPath };
    if (dbPath) env.AGAISTOCK_DB = dbPath;
    // **必须带 `-S`**：editable 安装（`pip install -e .`）注册的是 meta-path finder，
    // 优先级**高于** PYTHONPATH —— 实测开发机上不加 `-S` 时 `import agaistock`
    // 命中的是仓库里那份，不是插件自带的副本，自包含就成了空话。
    // `-S` 同时禁用 site-packages，正好把「业务内核零第三方依赖」（Global Constraint 2）
    // 从约定变成运行时硬约束：内核一旦依赖第三方包，Mini App 会立刻报错而不是
    // 悄悄依赖用户机器上的环境。
    const child = spawn('python', ['-S', '-m', 'agaistock.cli', ...args], {
      cwd,
      env,
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
```

**4.3** `handleRoute` 的 `dbPath` 默认值改成空串（不再有插件内的默认库）：

```javascript
    kernel = runKernel,
    dbPath = '',
  } = options;
```

**4.4** `start()` 用宿主给的 `pluginRoot` 与 `dataDir`：

```javascript
export async function start(context) {
  const dataDir = context.dataDir;
  await mkdir(dataDir, { recursive: true });
  const observationsPath = join(dataDir, OBSERVATIONS_FILE);
  // 宿主给的 pluginRoot 才是权威；模块层级的推导只是兜底。
  const pluginRoot = context.pluginRoot || PLUGIN_ROOT;
  const clientEntry = await readFile(join(pluginRoot, 'miniapp/client/index.html'));
```

紧接着读渲染模块的那段（Task 14 fix 加的）里的路径也要换成 `pluginRoot`：

```javascript
  let renderModule = '';
  try {
    renderModule = await readFile(join(pluginRoot, 'miniapp/client/render.mjs'), 'utf8');
  } catch {
    renderModule = '';
  }
```

在 `createServer` 之前绑定内核与库路径：

```javascript
  // 运行数据落宿主给的数据目录，**不是**插件目录 ——
  // 插件目录是安装产物（可能被只读安装、也可能被 Host 重装覆盖），
  // dataDir 才是运行时可写、跨重启保留的数据位置。
  const dbPath = join(dataDir, 'agaistock.db');
  const kernel = (args) => runKernel(args, {
    cwd: pluginRoot,
    pythonPath: join(pluginRoot, 'src'),
    dbPath,
  });

  const server = createServer((request, response) => {
    void handleRoute(request, response, {
      context,
      clientEntry,
      renderModule,
      readObservations,
      writeObservations,
      parseObservation,
      kernel,
      dbPath,
    }).catch(() => {
      if (!response.headersSent) sendJson(response, 500, { error: 'internal_error' });
    });
  });
```

- [ ] **Step 5: 让内核失败可见（`server.mjs`）**

**5.1** `/api/observations` 不再把内核失败吞成空列表：

```javascript
  if (request.method === 'GET' && url.pathname === '/api/observations') {
    // 观察库以内核为准（删除也走内核，行 id 必须是内核行 id）
    const result = await kernel(['list', '--db', dbPath, '--json']);
    if (result.code !== 0) {
      // 内核不可用 ≠ 没有观察记录。返回空列表会让用户以为「一条都没有」，
      // 真实原因（Python 缺失 / 内核崩了 / 库打不开）被彻底吞掉。
      sendJson(response, 500, {
        ok: false,
        error: 'KERNEL_FAILED',
        message: (result.stderr || `exit=${result.code}`).slice(-500),
      });
      return;
    }
    const payload = parseKernelJson(result.stdout);
    const items = Array.isArray(payload)
      ? payload
      : (payload && Array.isArray(payload.items) ? payload.items : []);
    // 前端读的是 data.items —— 这里必须保持 {ok, items} 外壳
    sendJson(response, 200, { ok: true, items });
    return;
  }
```

**5.2** `/api/observations/:id/reviews` 同样检查退出码：

```javascript
  if (request.method === 'GET' && url.pathname.endsWith('/reviews')) {
    const id = decodeURIComponent(url.pathname.slice('/api/observations/'.length, -'/reviews'.length));
    const result = await kernel(['reviews', id, '--db', dbPath, '--json']);
    if (result.code !== 0) {
      sendJson(response, 500, {
        ok: false,
        error: 'KERNEL_FAILED',
        message: (result.stderr || `exit=${result.code}`).slice(-500),
      });
      return;
    }
    const payload = parseKernelJson(result.stdout);
    sendJson(response, 200, payload ?? { observation_id: id, items: [] });
    return;
  }
```

**5.3** `countObservations` 去掉旧 JSON 观察库的回落（Task 14 起观察库一律以内核为准，
回落会让徽标数字与表格数字互相打架）：

```javascript
async function countObservations(kernel, dbPath) {
  const result = await kernel(['list', '--db', dbPath, '--json']);
  if (result.code !== 0) return null;
  const payload = parseKernelJson(result.stdout);
  if (payload && Array.isArray(payload.items)) return payload.items.length;
  return null;
}
```

`/api/status` 里的调用改成 `await countObservations(kernel, dbPath)`，
并把返回值原样放进 `observationCount`（内核不可用时是 `null`，不是 0）。

- [ ] **Step 6: 前端显示「内核不可用」（`index.html`）**

**6.1** `refreshStatus` 里不要把 `null` 变成 0：

```javascript
              runtimeState.count = data.observationCount === null ? null : (data.observationCount || 0);
```

**6.2** `renderChip` 里 `null` 显示「不可用」：

```javascript
        function renderChip() {
          var speech = runtimeState.speech;
          var agent = runtimeState.agent;
          runtimeChip.textContent =
            (speech === true ? '语音可用' : speech === false ? '语音不可用' : '语音状态未知') + ' · ' +
            (agent === true ? 'Agent 可用' : agent === false ? 'Agent 不可用' : 'Agent 状态未知') +
            ' · ' + (runtimeState.count === null ? '观察库不可用' : '已存 ' + runtimeState.count + ' 条');
        }
```

**6.3** `loadObservations` 在 `ok === false` 时显示原因而不是空表格：

```javascript
            .then(function (data) {
              if (data && data.ok === false) {
                // 内核不可用：必须显示原因，不能显示成「一条观察都没有」。
                obsCount.textContent = '不可用';
                runtimeState.count = null;
                renderChip();
                obsEmpty.classList.remove('hidden');
                obsEmpty.textContent = '观察库不可用：' + (data.message || data.error || '未知原因');
                obsTableWrap.classList.add('hidden');
                return;
              }
              var items = (data && data.items) || [];
              obsCount.textContent = items.length;
              runtimeState.count = items.length;
              renderChip();
              if (!items.length) {
                obsEmpty.classList.remove('hidden');
                obsTableWrap.classList.add('hidden');
                return;
              }
              obsEmpty.classList.add('hidden');
              obsTableWrap.classList.remove('hidden');
              // Task 14 之后 /api/observations 返回的是内核行（不是旧的 {createdAt, draft}）。
              var render = window.agaistockRender;
              if (!render) {
                obsEmpty.classList.remove('hidden');
                obsTableWrap.classList.add('hidden');
                setStatus(recordStatus, '前端渲染模块未加载，观察库表格无法显示。', 'error');
                return;
              }
              obsRows.innerHTML = render.renderObservationRows(items);
            })
```

- [ ] **Step 7: 补 Node 测试（`api.test.mjs`）**

加三条：

```javascript
test('GET /api/observations returns 500 when the kernel fails', async () => {
  const response = new FakeResponse();
  const kernel = async () => ({ code: 1, stdout: '', stderr: 'ModuleNotFoundError: agaistock' });
  await handleRoute(
    makeRequest('GET', '/api/observations'),
    response,
    { kernel, dbPath: 'test.db' },
  );
  // 内核不可用不能伪装成「一条观察都没有」
  assert.equal(response.statusCode, 500);
  assert.equal(response.json().ok, false);
  assert.match(response.json().message, /ModuleNotFoundError/);
});

test('GET /api/observations/:id/reviews returns 500 when the kernel fails', async () => {
  const response = new FakeResponse();
  const kernel = async () => ({ code: 1, stdout: '', stderr: '内核炸了' });
  await handleRoute(
    makeRequest('GET', '/api/observations/obs_1/reviews'),
    response,
    { kernel, dbPath: 'test.db' },
  );
  assert.equal(response.statusCode, 500);
  assert.equal(response.json().ok, false);
});

test('runKernel resolves the kernel from the plugin bundle, not the repo', () => {
  // 插件根 = <plugin>/miniapp/node 向上两级；内核必须在插件自带的 src 里。
  const source = readFileSync(
    join(import.meta.dirname, '..', 'miniapp', 'node', 'server.mjs'),
    'utf8',
  );
  assert.match(source, /const PLUGIN_ROOT = join\(import\.meta\.dirname, '\.\.', '\.\.'\)/);
  assert.match(source, /const KERNEL_SRC = join\(PLUGIN_ROOT, 'src'\)/);
});
```

第三条需要补 import：

```javascript
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
```

> 第三条是**防回归**的静态断言：把 `PLUGIN_ROOT` 改回「向上 4 级」时它必须失败。
> 路径推导错了不会让任何运行时单测变红（单测不走真实内核），只能这样钉住。

- [ ] **Step 8: 跑测试确认通过**

```bash
node --test "miniapps/agaistock/test/*.test.mjs"
python -m unittest discover -s tests -t .
```

Expected: Node 48 通过（pipeline 23 + render 10 + api 15）；Python 140 通过（138 + 2）。

> `node --test` **必须用 glob 形式**：目录形式在本机会报
> `Cannot find module ...\miniapps\agaistock\test`。

- [ ] **Step 9: 发布并在安装副本上验收**

```
miniapp { action: "publish", pluginId: "agaistock", sourcePath: "<repo>/miniapps/agaistock" }
miniapp { action: "open",    pluginId: "agaistock" }
```

然后在页面上下文里验：

1. `GET /render.mjs` → 200
2. `GET /api/observations` → **不是** `items: []` 静默空，而是要么真实数据、要么带 `ok:false` 的明确错误
3. 头部徽标显示「已存 N 条」或「观察库不可用」，**不能**是「已存 0 条」而表格空白

**关键验收**：把安装副本里的 `miniapps/agaistock/src` 临时改名，确认界面**立刻显示错误**
而不是「空观察库」；改回来确认恢复。这条验的是「失败可见」，不是「功能正常」。

- [ ] **Step 10: Commit**

```bash
git add tools/sync-kernel.py tests/test_kernel_vendor.py miniapps/agaistock/src miniapps/agaistock/config miniapps/agaistock/miniapp/node/server.mjs miniapps/agaistock/miniapp/client/index.html miniapps/agaistock/test/api.test.mjs
git commit -m "feat: ship the kernel inside the mini app bundle and surface kernel failures" -- tools/sync-kernel.py tests/test_kernel_vendor.py miniapps/agaistock/src miniapps/agaistock/config miniapps/agaistock/miniapp/node/server.mjs miniapps/agaistock/miniapp/client/index.html miniapps/agaistock/test/api.test.mjs
```

> **必须用明确路径，不要 `git add -A`**（Global Constraint 14）。
> `miniapps/agaistock/src` 与 `miniapps/agaistock/config` 是本轮**新增**的目录，
> 必须显式 add 进去。

---

### Task 18: 内核健壮性与防御性修复 —— 编码崩溃、观察期落点、配置/存储校验

> **来源**：Task 16 端到端实测（第二轮）+ 最终评审的 deferred minors triage。
> 本任务不新增业务能力，只把「会在真实机器上崩掉或悄悄丢数据」的地方修掉。

**缺陷四（Critical）：Windows 中文机器上，点评流程会间歇性整轮崩掉。**

Task 16 在真实安装副本里点「存进观察库」，界面直接报：

```
点评失败：... File "cli.py", line 103, in cmd_review
  print(json.dumps(payload, ensure_ascii=False, indent=2))
UnicodeEncodeError: 'gbk' codec can't encode character '\ufffd' in position 501
```

因果链（三段，每一段都实测过）：

1. **连接器解码**：`providers/mcode_cli.py` 用 `text=True, encoding="utf-8", errors="replace"`
   读 `mcode-tools` 的 stdout。`mcode-tools` 的输出**偶尔含非法 UTF-8 字节**
   （上游数据源编码不统一），`errors="replace"` 把它们变成 **U+FFFD**。
2. **CLI 输出**：Windows 中文机器上 Python 的 stdout 编码是 **GBK**（控制台代码页）。
   `print(json.dumps(..., ensure_ascii=False))` 遇到 GBK 编不出来的 U+FFFD → `UnicodeEncodeError`。
3. **后果**：`cmd_review` 在落完 observation 之后崩在 print 上 —— 用户看到「点评失败」，
   点评、评分、观察期全部没有，但 observation 已经插进库了。

**这是间歇性的**：连接器输出含非法字节时才触发（控制器复跑 3 次只有 1 次中招），
所以它会在用户最不该遇到的时候炸。

**缺陷五（Confirmed bug）：显式 `review_at` 落在周日，且可能落在允许窗口之外。**

控制器实测：`start=2026-11-20`（周五）、`review_at=2026-11-29`（**周日**）、
tier=`short`（allowed=(3,5)）→ 选中的 `review_at` 是 **2026-11-29，周日**；
而 `allowed_window` 是 `['2026-11-20', '2026-11-27']` —— **选中的日期在窗口之外**。
交易日偏移算出来是 5（在 allowed 里）所以没触发回退，但日期本身既不是交易日、
也越过了窗口上限。

**其余（本任务的防御性修复，triage 编号见 progress.md）**
- TRIAGE-01：`config._load_json` 顶层不是 dict 时抛 AttributeError，而不是可读的 ValueError。
- TRIAGE-02：`load_reviewers` 允许空注册表静默返回 `[]` —— 等于每条观察都「无人点评」，
  看起来像正常结果。必须 fail fast。
- TRIAGE-03：config 的四条 ValueError 分支零测试覆盖。
- TRIAGE-05：`db.insert_adjustment_factors` 无 rollback —— 循环中途失败时已写入的部分
  留在事务里，会被之后无关的 commit 一起提交，复权因子表变成半截数据。
- TRIAGE-06：`db.insert_review` 的默认值绕过 NOT NULL（`""` 满足约束）。
- TRIAGE-08：`db.list_observations` 的 `ORDER BY created_at DESC` 无 tiebreak
  （`created_at` 只到秒，同秒插入顺序不确定）。
- TRIAGE-15-1：「未白名单路径仍 404」这条安全不变量没有测试锁定。
- Task 17 implementer 报的偏差 3：`obsEmpty.textContent` 被改成错误文案后**不复位**，
  内核恢复后仍显示旧的错误文案。

**Files:**
- Modify: `src/agaistock/providers/mcode_cli.py`
- Modify: `src/agaistock/cli.py`
- Modify: `src/agaistock/horizon.py`
- Modify: `src/agaistock/config.py`
- Modify: `src/agaistock/storage/db.py`
- Modify: `src/agaistock/reviewers/contract.py`
- Modify: `miniapps/agaistock/miniapp/node/server.mjs`
- Modify: `miniapps/agaistock/miniapp/client/index.html`
- Modify: `tests/test_mcode_cli.py`、`tests/test_cli.py`、`tests/test_horizon.py`、`tests/test_config.py`、`tests/test_storage.py`、`tests/test_contract.py`
- Modify: `miniapps/agaistock/test/api.test.mjs`

> **内核副本同步**：`src/agaistock/**` 与 `config/**` 改动后**必须**跑
> `python tools/sync-kernel.py`（Task 17 引入），否则 `tests/test_kernel_vendor.py`
> 的漂移守卫会红 —— 这是设计好的：副本和源必须逐字节一致。

- [ ] **Step 1: 连接器输出改成「先严格 UTF-8，再 GBK，最后才替换」**

`src/agaistock/providers/mcode_cli.py`：

```python
def _decode_output(raw: bytes) -> str:
    """解码连接器输出：先严格 UTF-8，再 GBK，最后才替换。

    `errors="replace"` 会把非法字节变成 U+FFFD，而 **U+FFFD 在 GBK 控制台里
    编不出来** —— CLI 用 print() 输出 JSON 时会直接抛 UnicodeEncodeError，
    整轮点评全废（Task 16 实测）。所以这里宁可多试一种编码，也不要产出 U+FFFD。
    """
    for encoding in ("utf-8", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")
```

`call_connector` 里的子进程调用改成拿字节（不再用 `text=True`）：

```python
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                timeout=timeout,
                shell=True,
            )
        except FileNotFoundError as exc:
            raise MCodedToolsMissing(
                "未找到 mcode-tools CLI；请确认 MCode 运行时在 PATH 中"
            ) from exc

    stdout = _decode_output(result.stdout or b"").strip()
    stderr = _decode_output(result.stderr or b"").strip()

    if result.returncode != 0:
        if _looks_like_missing_cli(stderr):
            raise MCodedToolsMissing("未找到 mcode-tools CLI；请确认 MCode 运行时在 PATH 中")
        raise RuntimeError(f"连接器 {tool} 调用失败(exit={result.returncode}): {stderr[:500]}")

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"连接器 {tool} 返回非 JSON: {stdout[:300]}") from exc
```

> 注意：`stderr` 的解码也要走 `_decode_output`，否则错误信息里又会出现 U+FFFD。

- [ ] **Step 2: CLI 强制 UTF-8 输出（管道）/ 放宽错误处理（终端）**

`src/agaistock/cli.py`，在 `main()` 之前加：

```python
def _force_utf8_stdio() -> None:
    """管道场景强制 UTF-8，终端场景只放宽 errors。

    Windows 中文机器上 Python 的 stdout 编码是 GBK（控制台代码页）。
    CLI 用 print() 输出 JSON 时，遇到一个 GBK 编不出来的字符（实测：连接器
    输出里的 U+FFFD）就会抛 UnicodeEncodeError —— 用户看到的是「点评失败」，
    整轮点评全废。

    - **管道**（stdout 不是 TTY）：JSON 是给 Node 侧解析的机器间通道，
      必须 UTF-8，不能受控制台代码页影响。
    - **终端**（是 TTY）：保留控制台编码（否则中文会变乱码），
      只把 errors 放宽成 replace —— 宁可显示一个替换字符，也不能崩。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            if stream.isatty():
                reconfigure(errors="replace")
            else:
                reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            # 流已关闭或不支持重配置：不能因此让命令失败
            pass
```

`main()` 里第一行调用它：

```python
def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
```

- [ ] **Step 3: Node 侧双保险**

`miniapps/agaistock/miniapp/node/server.mjs` 的 `runKernel`：

```javascript
    const env = { ...process.env, PYTHONPATH: pythonPath, PYTHONIOENCODING: 'utf-8' };
    if (dbPath) env.AGAISTOCK_DB = dbPath;
    const child = spawn('python', ['-S', '-m', 'agaistock.cli', ...args], {
      cwd,
      env,
      encoding: 'utf8',
    });
```

> `PYTHONIOENCODING=utf-8` 让内核的 stdout 无论控制台代码页是什么都是 UTF-8；
> `encoding: 'utf8'` 让 Node 按 UTF-8 读子进程输出。两层都要 ——
> 内核侧修了（Step 2）只是让 CLI 单独用也安全，这里再兜一层底。

- [ ] **Step 4: 观察期落点修正（周末 + 窗口越界）**

`src/agaistock/horizon.py`，加一个交易日推进函数：

```python
def _next_trading_day(day: date) -> date:
    """把日期推进到下一个交易日（周末顺延；节假日未处理，仅作近似）。"""
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day
```

`plan()` 里把用户指定的日期先推进到交易日，**再**算偏移：

```python
    start_date = date.fromisoformat(start)
    if review_at:
        # 先推进到交易日再算偏移：结算日落在周末毫无意义。
        # 而且推进后偏移可能冲出 allowed —— 下面那条回退分支会把它收回来，
        # 保证 review_at 既是非交易日、也一定落在 allowed_window 之内。
        chosen = _next_trading_day(date.fromisoformat(review_at))
        # 用**交易日**偏移校验，不要用日历日差 —— 档位里的天数是交易日偏移。
        offset = _trading_days_between(start_date, chosen)
        if allowed and offset not in allowed:
            # 用户指定的日期不在允许档位内 → 落到档位内最早的那个，
            # 并同步收窄窗口，保证 review_at 一定落在 allowed_window 之内。
            allowed = (min(allowed),)
            chosen = _trading_days_later(start_date, min(allowed))
```

- [ ] **Step 5: config 的可读报错 + 空注册表 fail fast**

`src/agaistock/config.py`：

```python
def _load_json(relative_path: str) -> dict:
    """读仓库内的 JSON 配置。

    顶层不是 JSON 对象时要给**可读**的错：直接 `.get()` 会抛 AttributeError，
    用户看到的是一段没有上下文的栈回溯，而不是「配置文件坏了」。
    """
    path = repo_root() / relative_path
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(
            f"{relative_path} 顶层必须是 JSON 对象，实际是 {type(data).__name__}"
        )
    return data
```

`load_reviewers()` 里加空注册表的检查：

```python
    reviewers = data.get("reviewers")
    if not isinstance(reviewers, list):
        raise ValueError("config/reviewers.json 缺少 reviewers")
    if not reviewers:
        # 空注册表 = 产品核心功能整体失效。静默返回 [] 会让每条观察都
        # 「无人点评」，看起来像正常结果 —— 必须 fail fast。
        raise ValueError("config/reviewers.json 的 reviewers 为空：没有点评师就没有点评")
```

- [ ] **Step 6: db 的 rollback、NOT NULL 与排序 tiebreak**

`src/agaistock/storage/db.py`：

**6.1** `insert_adjustment_factors` 加 rollback：

```python
def insert_adjustment_factors(
    conn: sqlite3.Connection, symbol: str, factors: list[dict[str, Any]]
) -> int:
    """写入复权因子；同一 (symbol, ex_date) 重复写入覆盖。

    任何一条失败都必须回滚：否则已写入的部分会留在事务里，
    被之后无关的 commit 一起提交 —— 复权因子表变成半截数据，
    而复权价是后复权口径的地基。
    """
    fetched_at = _now()
    try:
        for item in factors:
            conn.execute(
                """INSERT INTO adjustment_factors
                   (symbol, ex_date, factor, constant, fetched_at)
                   VALUES (?,?,?,?,?)
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
    except Exception:
        conn.rollback()
        raise
    return len(factors)
```

**6.2** `insert_review` 不再用默认值绕过 NOT NULL：

```python
def insert_review(conn: sqlite3.Connection, observation_id: str, verdict: dict[str, Any]) -> str:
    """落一条点评结论。

    reviewer_id / reviewer_version / status 是**必填**的：它们不是「有则存之」的可选列 ——
    latest_reviews 靠 reviewer_id 分组取最新一版，空的 reviewer_id 会分出一个
    伪分组；空的 status 会让「这条点评成功还是失败」无从判断。
    """
    for field in ("reviewer_id", "reviewer_version", "status"):
        if not str(verdict.get(field, "") or "").strip():
            raise ValueError(f"点评结论缺少必填字段 {field}: {verdict.get('reviewer_id', '')}")
    review_id = _new_id("rev")
    conn.execute(
        """INSERT INTO reviews
           (id, observation_id, reviewer_id, reviewer_version, ran_at, status,
            duration_ms, verdict_json, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            review_id,
            observation_id,
            verdict["reviewer_id"],
            verdict["reviewer_version"],
            verdict.get("ran_at", ""),
            verdict["status"],
            int(verdict.get("duration_ms") or 0),
            json.dumps(verdict, ensure_ascii=False),
            _now(),
        ),
    )
    conn.commit()
    return review_id
```

**6.3** `list_observations` 加 tiebreak：

```python
    sql += " ORDER BY created_at DESC, rowid DESC"
```

> `created_at` 只到秒：同一秒内插入两条时，没有 tiebreak 的顺序是不确定的，
> 列表会在两次刷新之间自己变。加 `rowid DESC` 后「后插入的排前面」，
> 与「新的在前」的语义一致。

- [ ] **Step 7: 契约层补 reviewer_version 校验（让坏点评师被隔离，而不是整轮崩）**

`src/agaistock/reviewers/contract.py` 的 `validate_verdict` 里，紧跟着 reviewer_id 那一行加：

```python
    if not verdict.reviewer_id:
        errors.append("reviewer_id 为空")
    if not verdict.reviewer_version:
        errors.append("reviewer_version 为空")
```

> **为什么在契约层加、而不是只靠 db 层**：db 层现在会抛 ValueError，但 `persist()`
> 在 `run_one` 的异常隔离**之外** —— 抛出来就是整轮点评失败。
> 在契约层拦下来，坏结论会变成 `status="error"` 的 verdict（逐点评师隔离），
> db 层只是最后一道兜底。

- [ ] **Step 8: 前端错误文案复位**

`miniapps/agaistock/miniapp/client/index.html` 的 `loadObservations` 里，
在成功分支补一句复位：

```javascript
              var items = (data && data.items) || [];
              obsCount.textContent = items.length;
              runtimeState.count = items.length;
              renderChip();
              // 内核恢复后要把上一次的错误文案清掉，否则会一直显示旧错误。
              obsEmpty.textContent = '还没有观察记录。';
```

- [ ] **Step 9: 补测试**

**9.1 `tests/test_mcode_cli.py`** —— 连接器解码：

```python
class DecodeOutputTest(unittest.TestCase):
    def test_prefers_utf8(self):
        from agaistock.providers.mcode_cli import _decode_output
        self.assertEqual(_decode_output("章源钨业".encode("utf-8")), "章源钨业")

    def test_falls_back_to_gbk_instead_of_replacement_char(self):
        from agaistock.providers.mcode_cli import _decode_output
        # b'\xd5\xc5' 是「章」的 GBK 字节：非法 UTF-8，但合法 GBK。
        # 老实现 errors="replace" 会把它变成 U+FFFD —— 那正是崩掉整轮点评的元凶。
        decoded = _decode_output(b"\xd5\xc5")
        self.assertEqual(decoded, "章")
        self.assertNotIn("\ufffd", decoded)

    def test_replacement_char_only_as_last_resort(self):
        from agaistock.providers.mcode_cli import _decode_output
        # 既不是合法 UTF-8 也不是合法 GBK 的字节：只能替换，但不能抛。
        self.assertIsInstance(_decode_output(b"\x80"), str)
```

**9.2 `tests/test_cli.py`** —— CLI 在管道里遇到 U+FFFD 不崩：

```python
    def test_json_output_survives_unencodable_char(self):
        """Windows 中文机器上 stdout 是 GBK：输出里有一个 GBK 编不出来的字符时，
        整条命令不能崩。"""
        import subprocess
        import sys
        from agaistock.storage import db

        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "t.db"
            conn = db.connect(db_path)
            db.migrate(conn)
            db.insert_observation(conn, {
                "symbol": "002378",
                "name": "章\ufffd源钨业",
                "direction": "bullish",
                "thesis": "含替换字符的主张\ufffd",
                "raw_text": "原始文本",
            })
            conn.close()
            env = dict(os.environ)
            env["PYTHONPATH"] = str(repo_root / "src")
            env["PYTHONIOENCODING"] = ""  # 故意清掉，逼 CLI 自己处理
            result = subprocess.run(
                [sys.executable, "-m", "agaistock.cli", "list", "--db", str(db_path), "--json"],
                cwd=repo_root, env=env, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(len(payload["items"]), 1)
            self.assertIn("\ufffd", payload["items"][0]["name"])
```

> 这条测试跑的是**真实子进程**（不是 mock），所以它真的经过「GBK stdout 打印
> 一个编不出来的字符」这条路径。`PYTHONIOENCODING=""` 是为了让环境不替我们
> 兜底 —— 正是要验 CLI 自己能不能扛住。
> `json` / `os` / `tempfile` / `Path` 本文件已经 import 了，`db` 在方法内单独 import。

**9.3 `tests/test_horizon.py`** —— 周末落点（沿用文件里已有的 `verdict_with_tier`）：

```python
    def test_explicit_review_at_on_weekend_lands_on_trading_day(self):
        # 2026-11-29 是周日：结算日不能落在非交易日。
        # 推进到交易日后偏移可能冲出 allowed —— 回退分支必须把它收回来，
        # 保证 review_at 既是非交易日、也落在 allowed_window 之内。
        from datetime import date
        plan_result = plan(
            {"symbol": "002378", "thesis": "t"},
            [verdict_with_tier("a", "short")],
            start="2026-11-20",
            review_at="2026-11-29",
        )
        chosen = date.fromisoformat(plan_result["review_at"])
        self.assertLess(chosen.weekday(), 5, "review_at 不能落在周末")
        start, end = plan_result["allowed_window"]
        self.assertGreaterEqual(chosen, date.fromisoformat(start))
        self.assertLessEqual(chosen, date.fromisoformat(end))
```

> `verdict_with_tier(reviewer_id, tier)` 是本文件里已有的模块级函数，直接用，
> 不要另造一个。

**9.4 `tests/test_config.py`** —— config 的六条分支（本文件现在没有临时配置helper，要加一个）：

```python
import json
import tempfile
import unittest
from pathlib import Path

from agaistock import config


def with_config(filename, content, func):
    """把 config 的仓库根临时指向一个只含指定配置文件的临时目录。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "config").mkdir()
        (root / "config" / filename).write_text(content, encoding="utf-8")
        original = config.repo_root
        config.repo_root = lambda: root
        try:
            return func()
        finally:
            config.repo_root = original
```

```python
    def test_non_dict_top_level_raises_value_error(self):
        # 顶层是数组时不能抛 AttributeError，要给可读的 ValueError。
        with self.assertRaises(ValueError):
            with_config("scoring.json", "[1, 2, 3]", config.load_scoring)

    def test_scoring_missing_dimensions_raises(self):
        with self.assertRaises(ValueError):
            with_config("scoring.json", '{"other": 1}', config.load_scoring)

    def test_scoring_dimension_missing_field_raises(self):
        payload = json.dumps({"dimensions": [{"name": "事实锚定"}]})
        with self.assertRaises(ValueError):
            with_config("scoring.json", payload, config.load_scoring)

    def test_reviewers_missing_registry_raises(self):
        with self.assertRaises(ValueError):
            with_config("reviewers.json", '{"other": 1}', config.load_reviewers)

    def test_reviewer_missing_field_raises(self):
        payload = json.dumps({"reviewers": [{"id": "anchor-chanlun"}]})
        with self.assertRaises(ValueError):
            with_config("reviewers.json", payload, config.load_reviewers)

    def test_empty_reviewer_registry_fails_fast(self):
        # 空注册表 = 产品核心功能整体失效，必须报错而不是静默返回 []。
        with self.assertRaises(ValueError):
            with_config("reviewers.json", '{"reviewers": []}', config.load_reviewers)
```

> `config.repo_root` 是模块级函数，`_load_json` 内部按 `repo_root()` 调用，
> 所以临时替换 `config.repo_root` 就能把配置指向临时目录 —— 已有测试
> `test_load_scoring_returns_five_fixed_dimensions` 之类仍然读真实配置，不受影响。

**9.5 `tests/test_storage.py`** —— db 的三条（沿用文件里已有的 `make_conn()` / `verdict()`）：

```python
    def test_adjustment_factor_write_rolls_back_on_failure(self):
        # 第二条因子缺 ex_date → 整体失败，第一条也不能留在事务里。
        conn = make_conn()
        with self.assertRaises(KeyError):
            db.insert_adjustment_factors(conn, "002378", [
                {"ex_date": "2026-01-01", "factor": 1.0, "constant": 0.0},
                {"factor": 1.0, "constant": 0.0},
            ])
        count = conn.execute("SELECT COUNT(*) FROM adjustment_factors").fetchone()[0]
        self.assertEqual(count, 0, "失败后必须回滚，不能留下半截数据")

    def test_insert_review_rejects_empty_reviewer_id(self):
        conn = make_conn()
        with self.assertRaises(ValueError):
            db.insert_review(conn, "obs_1", {
                "reviewer_id": "", "reviewer_version": "0.1.0", "status": "ok",
            })

    def test_list_observations_tiebreak_is_stable(self):
        # 两条 created_at 完全相同：顺序必须确定（后插入的在前）。
        conn = make_conn()
        for index in range(2):
            db.insert_observation(conn, {
                "id": f"obs_{index}", "symbol": "002378", "name": "x",
                "created_at": "2026-11-24T10:00:00+00:00", "direction": "bullish",
            })
        first = [row["id"] for row in db.list_observations(conn)]
        second = [row["id"] for row in db.list_observations(conn)]
        self.assertEqual(first, second)
        self.assertEqual(first, ["obs_1", "obs_0"])
```

**9.6 `tests/test_contract.py`** —— reviewer_version（沿用文件里已有的 `contract.` 调用风格）：

```python
    def test_empty_reviewer_version_is_rejected(self):
        verdict = contract.ReviewVerdict(
            reviewer_id="anchor-chanlun",
            reviewer_version="",
            ran_at="2026-11-24T07:30:00Z",
            status="ok",
            duration_ms=0,
            data_refs=[],
            findings=[],
            proposed_invalidation=[],
            horizon_hint=None,
            caveats=[],
        )
        errors = contract.validate_verdict(verdict, ["位置与时机"])
        self.assertTrue(any("reviewer_version" in err for err in errors))
```

**9.7 `miniapps/agaistock/test/api.test.mjs`** —— 非白名单路径仍 404：

```javascript
test('paths outside the whitelist still return 404', async () => {
  // 「只白名单这一个文件」是本服务的安全不变量：换成通用静态服务就会路径穿越。
  for (const path of ['/index.html', '/client/render.mjs', '/etc/passwd', '/render.mjs/']) {
    const response = new FakeResponse();
    await handleRoute(
      makeRequest('GET', path),
      response,
      { renderModule: 'export const renderScore = () => "";\n', kernel: fakeKernel({}) },
    );
    assert.equal(response.statusCode, 404, `${path} 必须 404`);
  }
});
```

- [ ] **Step 10: 同步内核副本并跑全量测试**

```bash
python tools\sync-kernel.py
python tools\sync-kernel.py --check
python -m unittest discover -s tests -t .
node --test "miniapps/agaistock/test/*.test.mjs"
node --check miniapps/agaistock/miniapp/node/server.mjs
```

Expected: Python 全绿（138 + 新增用例）；Node 49 通过（48 + 1 条 404 不变量）。

> **忘了 `python tools\sync-kernel.py` 的话**，`tests/test_kernel_vendor.py`
> 的漂移守卫会红 —— 那不是误报，是真的漂了（内核副本里的旧代码会继续被运行）。

- [ ] **Step 11: 在真实安装副本上复验编码崩溃已修**

用 Task 17 的验收办法（`.tmp/` 下起真实服务），并**故意**在 payload 里塞一个
GBK 编不出来的字符，确认 `list --json` 不再抛 UnicodeEncodeError。

- [ ] **Step 12: Commit**

```bash
git add src/agaistock miniapps/agaistock/src miniapps/agaistock/config tests miniapps/agaistock/miniapp/node/server.mjs miniapps/agaistock/miniapp/client/index.html miniapps/agaistock/test/api.test.mjs tools/sync-kernel.py
git commit -m "fix: survive unencodable output, land observation reviews on trading days, harden config and storage" -- src/agaistock miniapps/agaistock/src miniapps/agaistock/config tests miniapps/agaistock/miniapp/node/server.mjs miniapps/agaistock/miniapp/client/index.html miniapps/agaistock/test/api.test.mjs
```

> `src/agaistock` 与 `miniapps/agaistock/src` **必须一起提交** ——
> 它们是同一份代码的两个副本，漂了漂移守卫就会红。

---

### Task 19: 结构化观察落库 —— 接住接入层的解析结果，别再丢掉

> **来源**：最终评审 TRIAGE-14（Task 16 实测 + 设计文档 §7 界面样例比对）。

**问题：用户看得到富观察卡，存下来却什么都没了。**

Task 16 实测（安装副本里走完整条链路）：

| 阶段 | 用户看到的东西 |
|---|---|
| 「解析成观察卡」 | 标的 002378 章源钨业 · 主张 · **看多 75%** · 依据 5 条（事实 2 · 假设 3） · **证伪条件：钨价跌回去年年底的水平** |
| 「存进观察库」之后 | 观察库那一行：信心 **0%** · 证伪条件 **缺失** |

原因在链路上：前端「存进观察库」只发 `{symbol, name, text}`，
**LLM 解析出来的结构化草稿被整个丢掉**；内核 `cli._parse_observation` 用关键词启发式
重新解析一遍 —— 方向靠「看多/看空/拿/涨」猜、时限靠「半年/一年」猜、
`confidence` **写死 0.0**，`evidence` 和 `invalidation` 根本没有落库的地方
（`observations` 表没有这两列）。

设计文档 §7 的界面样例明确要求「看多 72%」「依据 4 条（事实 2 · 假设 2）」
「⚠ 缺少证伪条件」—— 现在一条都对不上。而且「认知档案 / 校准统计」依赖用户
自报的信心与判断标准，信心恒为 0 就等于这个能力永远做不了。

**本任务把「结构化记录」这半条链补上**：接入层解析出的观察进内核、落库、显示出来。

**Files:**
- Modify: `src/agaistock/storage/db.py`（表结构 + 迁移 + 读写）
- Modify: `src/agaistock/cli.py`（接受结构化观察）
- Modify: `src/agaistock/reviewers/engine.py`（Task 18 引入的回归：空版本号）
- Modify: `miniapps/agaistock/miniapp/node/server.mjs`（把草稿传给内核）
- Modify: `miniapps/agaistock/miniapp/client/index.html`（把草稿发出去）
- Modify: `miniapps/agaistock/miniapp/client/render.mjs`（展示依据条数；采纳按钮改禁用）
- Modify: `tests/test_storage.py`、`tests/test_cli.py`、`tests/test_engine.py`
- Modify: `miniapps/agaistock/test/api.test.mjs`、`miniapps/agaistock/test/render.test.mjs`
- Modify: `docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md`（采纳路径的后续约定）

> **内核副本同步**：改完 `src/agaistock/**` 必须跑 `python tools/sync-kernel.py`，
> 否则 `tests/test_kernel_vendor.py` 的漂移守卫会红。

- [ ] **Step 0: 先修 Task 18 引入的一处回归：空版本号的点评师会让整轮崩掉**

`src/agaistock/reviewers/engine.py` 里三处 `getattr(reviewer, "version", "0.0.0")`
只在属性**不存在**时用默认版本；属性存在但为空串时拿到的是 `""`。
Task 18 之后 `db.insert_review` 把 `reviewer_version` 变成必填（空值抛 ValueError），
而落库在异常隔离**之外** —— 于是「一个点评师定义的版本号是空的」会从
「这一条点评是 error」升级成「整轮点评崩掉」。

加一个统一的取值函数（放在 `_error_verdict` 前面）：

```python
def _reviewer_version(reviewer) -> str:
    """点评师版本号；空值用默认版本。

    空版本号会被 db.insert_review 拒绝落库（reviewer_version 是必填），
    而落库在异常隔离之外 —— 不能让「一个点评师定义有问题」变成「整轮崩掉」。
    """
    version = getattr(reviewer, "version", "")
    return str(version).strip() or "0.0.0"
```

把 engine.py 里那三处 `getattr(reviewer, "version", "0.0.0")` 全换成
`_reviewer_version(reviewer)`。

测试（`tests/test_engine.py`，沿用本文件里 `contract.ReviewContext(...)` 的写法）：

```python
    def test_error_verdict_with_empty_reviewer_version_is_still_persistable(self):
        # 版本号为空串的点评师：结论落库时 reviewer_version 是必填，
        # 不能让「定义有问题」升级成「整轮崩」。
        class EmptyVersionReviewer:
            id = "empty-version"
            version = ""

            def review(self, ctx):
                raise RuntimeError("炸了")

        ctx = contract.ReviewContext(
            observation={}, symbol="002378", name="章源钨业", now="t",
            data_dir=".", llm=None,
        )
        verdict = engine.run_one(EmptyVersionReviewer(), ctx)
        self.assertEqual(verdict.status, "error")
        self.assertTrue(verdict.reviewer_version, "版本号不能是空串")
```

- [ ] **Step 1: `observations` 表加两列 + 补列迁移**

`src/agaistock/storage/db.py` 的 `SCHEMA` 里，`observations` 的定义加两列
（放在 `position_json` 之后、`raw_text` 之前）：

```sql
    position_json     TEXT,
    evidence_json     TEXT,
    invalidation_json TEXT,
    raw_text          TEXT,
```

> **光改 CREATE TABLE 不够**：`CREATE TABLE IF NOT EXISTS` 不会给**已存在**的表加列。
> 开发机上已经建好的 `data/agaistock.db`、用户装过的旧版本，都是老结构 ——
> 必须有一条 ALTER 迁移。

在 `migrate()` 里补列迁移：

```python
# 新增列用 ALTER TABLE 补齐：CREATE TABLE IF NOT EXISTS 不会给已存在的表加列。
_MIGRATIONS = (
    ("observations", "evidence_json", "TEXT"),
    ("observations", "invalidation_json", "TEXT"),
)


def _migrate_columns(conn: sqlite3.Connection) -> None:
    """给已存在的表补上新增的列（幂等）。"""
    for table, column, declaration in _MIGRATIONS:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
```

`migrate()` 改成：

```python
def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate_columns(conn)
    conn.commit()
```

- [ ] **Step 2: `insert_observation` 存这两列，`list_observations` 读回来**

`insert_observation` 的 INSERT 列表与参数里加两列，值分别是
`json.dumps(observation.get("evidence") or [], ensure_ascii=False)` 和
`json.dumps(observation.get("invalidation") or [], ensure_ascii=False)`。

`list_observations` 改成把 JSON 列解析成数组再返回（前端 `renderObservationRows`
读的就是 `item.invalidation` 这个**数组**）：

```python
def _load_json_list(raw: str | None) -> list:
    """把 JSON 列读成列表；坏数据当成空列表，不能让整张表读不出来。"""
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def list_observations(conn: sqlite3.Connection, include_deleted: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT * FROM observations"
    if not include_deleted:
        sql += " WHERE deleted_at IS NULL"
    sql += " ORDER BY created_at DESC, rowid DESC"
    rows = []
    for row in conn.execute(sql):
        item = dict(row)
        item["evidence"] = _load_json_list(item.pop("evidence_json", None))
        item["invalidation"] = _load_json_list(item.pop("invalidation_json", None))
        rows.append(item)
    return rows
```

> `item.pop("evidence_json")` 把原始 JSON 字符串换掉：对外只暴露解析好的数组，
> 免得前端拿到字符串还要自己 parse 一遍。

- [ ] **Step 3: 内核接受结构化观察（但不盲信草稿）**

`src/agaistock/cli.py`：

**3.1** `review` 子命令加参数：

```python
    review.add_argument("--observation-file", default=None,
                        help="接入层解析出的结构化观察（JSON 文件）")
```

**3.2** 新增两个函数（放在 `_parse_observation` 后面）：

```python
def _observation_from_draft(draft: dict, symbol: str, name: str, text: str) -> dict:
    """把接入层（Mini App 的 LLM 层）解析出的结构化观察转成内核的观察行。

    **不盲信草稿**：每个字段都校验，不合法的退回关键词解析的结果。
    理由：草稿来自模型输出，可能缺字段、类型不对、信心越界；
    而观察记录是后面评分与校准的输入，不能带脏数据进去。
    """
    fallback = _parse_observation(symbol, name, text)
    direction = draft.get("direction")
    if direction not in ("bullish", "bearish", "neutral"):
        direction = fallback["direction"]
    raw_confidence = draft.get("confidence")
    confidence = (
        float(raw_confidence)
        if isinstance(raw_confidence, (int, float)) and not isinstance(raw_confidence, bool)
        else fallback["confidence"]
    )
    confidence = min(1.0, max(0.0, confidence))
    thesis = str(draft.get("thesis") or "").strip() or fallback["thesis"]
    evidence = []
    for item in draft.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        item_text = str(item.get("text") or "").strip()
        if not item_text:
            continue
        item_type = item.get("type")
        evidence.append({
            "text": item_text,
            "type": item_type if item_type in ("fact", "assumption") else "assumption",
        })
    invalidation = [
        str(item).strip()
        for item in (draft.get("invalidation") or [])
        if str(item or "").strip()
    ]
    position = draft.get("position")
    return {
        "symbol": symbol or fallback["symbol"],
        "name": name or str(draft.get("name") or "").strip() or fallback["name"],
        "direction": direction,
        "thesis": thesis[:200],
        "confidence": confidence,
        "timeframe": str(draft.get("timeframe") or "").strip() or fallback["timeframe"],
        "trigger": str(draft.get("trigger") or "").strip() or fallback["trigger"],
        "position": position if isinstance(position, dict) else {},
        "evidence": evidence,
        "invalidation": invalidation,
        "raw_text": text,
    }


def _load_structured_observation(path: str | None, symbol: str, name: str, text: str) -> dict:
    """有结构化观察文件就用它，没有就退回关键词解析。"""
    if not path:
        return _parse_observation(symbol, name, text)
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"结构化观察文件不存在: {file_path}")
    draft = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(draft, dict):
        raise ValueError(f"结构化观察文件顶层必须是 JSON 对象: {file_path}")
    return _observation_from_draft(draft, symbol, name, text)
```

**3.3** `cmd_review` 里把

```python
        observation = _parse_observation(args.symbol, args.name, args.text)
```

改成

```python
        observation = _load_structured_observation(
            args.observation_file, args.symbol, args.name, args.text
        )
```

- [ ] **Step 4: Mini App 把草稿传给内核**

**4.1** `miniapps/agaistock/miniapp/node/server.mjs`：

- `handleRoute` 的 options 解构加 `dataDir = ''`；
- 在解构之后算出草稿目录：`const draftDir = dataDir || dirname(dbPath);`（`dirname` 从 `node:path` 导入）；
- `/api/review` 分支里，把草稿写成临时文件再传给内核：

```javascript
  if (request.method === 'POST' && url.pathname === '/api/review') {
    const body = await readBody(request);
    const text = typeof body.text === 'string' ? body.text.trim() : '';
    if (!text) {
      sendJson(response, 400, { ok: false, error: 'EMPTY_INPUT', message: '先说点什么。' });
      return;
    }
    // 结构化观察（接入层 LLM 解析出来的草稿）写文件传给内核：
    // 命令行长度有上限（Windows 约 32K），口述原文可能很长，不能拼在 argv 里。
    const draft = body.observation && typeof body.observation === 'object' ? body.observation : null;
    let draftPath = '';
    if (draft) {
      draftPath = join(
        draftDir,
        `observation-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}.json`,
      );
      await writeFile(draftPath, JSON.stringify(draft), 'utf8');
    }
    try {
      const args = [
        'review',
        '--symbol', String(body.symbol ?? ''),
        '--name', String(body.name ?? ''),
        '--text', text,
        '--db', dbPath,
        '--json',
      ];
      if (draftPath) args.push('--observation-file', draftPath);
      const result = await kernel(args);
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
    } finally {
      // 草稿是临时文件：内核跑完就删，不留在宿主数据目录里。
      if (draftPath) {
        await rm(draftPath, { force: true }).catch(() => undefined);
      }
    }
  }
```

- `node:fs/promises` 的 import 里补 `rm`；`node:path` 的 import 里补 `dirname`；
- `start()` 里给 `handleRoute` 传 `dataDir`。

**4.2** `miniapps/agaistock/miniapp/client/index.html` 的保存按钮：

```javascript
              var payload = {
                symbol: (currentDraft && currentDraft.symbol) || '',
                name: (currentDraft && currentDraft.name) || '',
                text: rawText.value,
                // 把接入层解析出的结构化观察一起送过去 —— 内核要靠它落库用户的
                // 依据、证伪条件和信心，否则这些信息在这里就丢了。
                observation: currentDraft || null
              };
```

- [ ] **Step 5: 观察库展示真实值**

**5.1** `miniapps/agaistock/miniapp/client/render.mjs` 的 `renderObservationRows`：
读 `item.evidence`，在主张单元格里加一行「依据 N 条」：

```javascript
    const evidence = Array.isArray(item.evidence) ? item.evidence : [];
    const invalidation = Array.isArray(item.invalidation) ? item.invalidation : [];
```

主张单元格改成：

```javascript
      + '<td>' + escapeHtml(item.thesis || '（未提取）')
      + (evidence.length ? '<div class="sub">依据 ' + evidence.length + ' 条</div>' : '')
      + '</td>'
```

> 信心与证伪条件两列**不用改** —— 它们读的就是 `item.confidence` 和
> `item.invalidation`，之前之所以恒为 0%/缺失，是内核没存这两样东西（Step 1–3 修掉了）。

**5.2** 「采纳」按钮改成**禁用**并说明原因：

```javascript
      + '<button type="button" disabled title="采纳需要观察版本链，本轮未实现">采纳</button>'
```

> **为什么先禁用**：设计文档 §6.3 要求「采纳」写入 `observation.invalidation`
> 且是**新版本行 + supersedes_id**（观察记录只追加不修改）。当前存储模型没有
> 观察版本链，直接改数组会破坏「观察记录只追加不修改」这条不变量。
> 一个点了没反应的按钮比一个明确禁用的按钮更糟 —— 禁用 + 说明 + 写进设计文档的
> 后续约定，三件事一起做。

- [ ] **Step 6: 补测试**

**6.1 `tests/test_storage.py`**：

```python
    def test_insert_observation_stores_evidence_and_invalidation(self):
        conn = make_conn()
        db.insert_observation(conn, {
            "symbol": "002378", "name": "章源钨业", "direction": "bullish",
            "thesis": "钨价上涨", "confidence": 0.75,
            "evidence": [{"text": "钨价从去年就开始涨", "type": "fact"}],
            "invalidation": ["钨价跌回去年年底的水平"],
        })
        row = db.list_observations(conn)[0]
        self.assertEqual(row["confidence"], 0.75)
        self.assertEqual(row["invalidation"], ["钨价跌回去年年底的水平"])
        self.assertEqual(row["evidence"][0]["type"], "fact")

    def test_migration_adds_columns_to_existing_table(self):
        # 老库没有这两列：migrate() 必须补上。
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE observations (id TEXT PRIMARY KEY, symbol TEXT NOT NULL, "
            "created_at TEXT NOT NULL, deleted_at TEXT)"
        )
        conn.commit()
        db.migrate(conn)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(observations)")}
        self.assertIn("evidence_json", columns)
        self.assertIn("invalidation_json", columns)
```

**6.2 `tests/test_cli.py`**：

```python
    def test_review_accepts_structured_observation(self):
        # 接入层的结构化草稿要能落库：信心/依据/证伪条件不能丢。
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "a.db"
            draft_path = Path(tmp) / "draft.json"
            draft_path.write_text(json.dumps({
                "symbol": "002378", "name": "章源钨业",
                "thesis": "钨价上涨叠加产量翻倍",
                "direction": "bullish", "confidence": 0.75,
                "evidence": [{"text": "钨价从去年就开始涨", "type": "fact"}],
                "invalidation": ["钨价跌回去年年底的水平"],
                "timeframe": "半年", "trigger": "明年上半年产量翻倍",
            }, ensure_ascii=False), encoding="utf-8")
            # 本文件**没有** review 的既有用例（review 会连真实行情源、很慢），
            # 这里把点评师列表 mock 成空 —— 只验「草稿被内核接收并落库」。
            with mock.patch.object(cli.registry, "load_reviewers", return_value=[]):
                code = cli.main([
                    "review", "--symbol", "002378", "--name", "章源钨业",
                    "--text", "还能拿半年", "--observation-file", str(draft_path),
                    "--db", str(db_path), "--json",
                ])
            self.assertEqual(code, 0)
            conn = db.connect(db_path)
            rows = db.list_observations(conn)
            conn.close()
            self.assertEqual(rows[0]["confidence"], 0.75)
            self.assertEqual(rows[0]["invalidation"], ["钨价跌回去年年底的水平"])
            self.assertEqual(rows[0]["thesis"], "钨价上涨叠加产量翻倍")
            self.assertEqual(rows[0]["evidence"][0]["type"], "fact")

    def test_structured_observation_clamps_confidence(self):
        # 草稿里的信心越界要被夹住，不能直接进库。
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "a.db"
            draft_path = Path(tmp) / "draft.json"
            draft_path.write_text(
                json.dumps({"confidence": 3.5, "direction": "看多"}), encoding="utf-8"
            )
            with mock.patch.object(cli.registry, "load_reviewers", return_value=[]):
                code = cli.main([
                    "review", "--symbol", "002378", "--text", "还能拿半年",
                    "--observation-file", str(draft_path),
                    "--db", str(db_path), "--json",
                ])
            self.assertEqual(code, 0)
            conn = db.connect(db_path)
            rows = db.list_observations(conn)
            conn.close()
            self.assertEqual(rows[0]["confidence"], 1.0)
            # direction 非法（"看多" 不是 bullish/bearish/neutral）→ 退回关键词解析
            self.assertIn(rows[0]["direction"], ("bullish", "bearish", "neutral"))
```

> `mock` 与 `json` 本文件已经 import 了；`db` 用 `from agaistock.storage import db`
> 在方法内 import。`cli.registry` 是 `agaistock.reviewers.registry` 模块（cli 里 `from .reviewers import registry`），
> 用 `mock.patch.object(cli.registry, "load_reviewers", return_value=[])` 把它 mock 成空列表，
> 点评师就不会真跑。

**6.3 `miniapps/agaistock/test/api.test.mjs`**：

```javascript
test('POST /api/review forwards the structured observation to the kernel', async () => {
  const response = new FakeResponse();
  const kernel = fakeKernel({ observation_id: 'obs_9', reviews: [], score: {}, horizon: {} });
  await handleRoute(
    makeRequest('POST', '/api/review', {
      symbol: '002378', name: '章源钨业', text: '还能拿半年',
      observation: { confidence: 0.75, invalidation: ['钨价跌回去年年底的水平'] },
    }),
    response,
    { kernel, dbPath: 'test.db', dataDir: '' },
  );
  assert.equal(response.statusCode, 200);
  const args = kernel.calls[0];
  assert.ok(args.includes('--observation-file'), '必须把结构化观察传给内核');
});
```

**6.4 `miniapps/agaistock/test/render.test.mjs`**：

```javascript
test('renderObservationRows shows the real confidence and invalidation', () => {
  const html = renderObservationRows([{
    id: 'obs_1', created_at: '2026-11-24T07:00:00Z', symbol: '002378', name: '章源钨业',
    direction: 'bullish', thesis: '钨价上涨', confidence: 0.75,
    evidence: [{ text: '钨价从去年就开始涨', type: 'fact' }],
    invalidation: ['钨价跌回去年年底的水平'],
  }]);
  assert.match(html, /75%/);
  assert.match(html, /钨价跌回去年年底的水平/);
  assert.match(html, /依据 1 条/);
});
```

- [ ] **Step 7: 同步内核副本、跑全量测试**

```bash
python tools\sync-kernel.py
python tools\sync-kernel.py --check
python -m unittest discover -s tests -t .
node --test "miniapps/agaistock/test/*.test.mjs"
```

- [ ] **Step 8: 写回设计文档（采纳路径的后续约定）**

在设计文档 §6.3「证伪条件的采纳路径」下面补一段：

> **当前实现（2026-11-24）**：「采纳」按钮暂时**禁用**。观察记录目前没有版本链
> （`supersedes_id`），而采纳会修改已存在的观察记录 —— 与「观察记录只追加不修改」
> 的不变量冲突。下一轮补观察版本链时再启用。点评师的 `proposed_invalidation`
> 依然**不会自动写入** observation（§2.2 硬约束），这一点不变。

- [ ] **Step 9: Commit**

```bash
git add src/agaistock miniapps/agaistock/src miniapps/agaistock/config tests miniapps/agaistock/miniapp/node/server.mjs miniapps/agaistock/miniapp/client/index.html miniapps/agaistock/miniapp/client/render.mjs miniapps/agaistock/test/api.test.mjs miniapps/agaistock/test/render.test.mjs docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md
git commit -m "feat: persist the structured observation from the parsing layer" -- src/agaistock miniapps/agaistock/src miniapps/agaistock/config tests miniapps/agaistock/miniapp/node/server.mjs miniapps/agaistock/miniapp/client/index.html miniapps/agaistock/miniapp/client/render.mjs miniapps/agaistock/test/api.test.mjs miniapps/agaistock/test/render.test.mjs docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md
```

### Task 20: 缠论分析工作目录落 `dataDir` —— 别把运行产物写进安装产物

> **来源**：Task 16 的最终独立评审（verifier）finding F4。评审方核对真实运行库与
> 安装副本时发现：设计文档 §16.2 第 3 条「运行数据必须落 `context.dataDir`」
> **过宽** —— 只有**数据库**落 `dataDir`，**缠论分析工作目录仍写在插件包自己的
> `data/` 下**。

**缺陷（Minor，但属结构性错位）**

`cli.py` 构造 `ReviewContext` 时写死：

```python
data_dir=config.repo_root() / "data",
```

`config.repo_root()` 是 `Path(__file__).resolve().parents[2]` —— 在**仓库内**指向仓库根，
在**安装副本**里指向**包根**（`…\Temp\mavis-miniapp-XXXXXX\package\`）。
于是 `reviewer.py` 的

```python
work_dir = Path(ctx.data_dir) / "chanlun" / symbol
work_dir.mkdir(parents=True, exist_ok=True)
```

在安装副本里就变成 `…\package\data\chanlun\<symbol>\` —— **运行产物写进了安装产物**。

两条后果：

1. **污染安装产物**：上游脚本产出的 K 线与结构 JSON 落进插件包目录
   （安装副本的 `package/data/chanlun/002378/` 下有 8 个文件；来源见下面的注）。
   `data/` 已被 `.gitignore` 忽略，所以这些文件**不随包发布**，但每次运行都会在
   安装目录里重新生成一批。
   > **来源说明**：这 8 个 `data/chanlun/002378/*.json` 是**运行时写的** ——
   > 判定依据是**内容与时间**：宿主 `context.dataDir` 下那 8 个 JSON 的 mtime
   > （`2026-11-24T14:34Z` 一带）与仓库根 `data/chanlun/002378/` 下那 8 个
   > （`2026-11-24T11:18Z` 一带）**不同** ⇒ 不是同一批拷过去的。
   > ⚠️ **不要**用「某个目录在不在」当证据 —— 宿主**会连 `data/` 目录一起拷**
   > （实测宿主的安装目录里出现过 `data/agaistock.db`，mtime 与「在包目录直跑内核」
   > 写出的时刻同一秒）。publish 前跑 `python tools/clean-package-artifacts.py` 清理。
   > ⚠️ 但**不要**把这条推广成「宿主不会拷 gitignored 产物」—— **那个一般命题是成立的**：
   > 实测仓库插件包 `miniapps/agaistock/src/agaistock/**` 的 24 个 `.pyc` 与宿主持久安装目录
   > `~/.minimax/plugins/agaistock/src/agaistock/**` 的 24 个 `.pyc` **mtime 24/24 完全相同**
   > （连亚秒都一致）⇒ 这批 `.pyc` **只能是宿主拷进去的**（`__pycache__` 是 gitignored 产物）。
   > 至于「有多少个早于解包时刻」**随解包批次变化**（实测 19/24 ~ 24/24），
   > **不要**把某个固定数字当证据 —— 决定性的是「mtime 逐个完全相同」这一条。
   > ⇒ **来源不可泛化**：文件计数、某个 `.pyc` 的 mtime，都不能用来推断别的文件的来源。
   > 缺陷本身由**代码 + 只读安装复现**证明，不靠文件计数。
2. **只读安装会直接崩**：`work_dir.mkdir(parents=True, exist_ok=True)` 在只读目录上抛
   `PermissionError` → 点评师整体失败 → 正是 Task 17 想根除的那类「内核失败被隐藏」。

> **这不是「缓存」**：`build_structure()` 每次都重新拉三级别 K 线、重写 `kline_*.json`、
> 重跑上游脚本，**从不复用**既有文件。它只是**中间产物暂存区** —— 所以
> 「缓存跨重装保留」这条收益本来就不存在。要修的是**位置**，不是命中率。

**修法**：与数据库完全对称 —— 数据库走 `AGAISTOCK_DB` 环境变量，工作目录走
`AGAISTOCK_DATA_DIR` 环境变量，都由 Node 侧从 `context.dataDir` 派生。

**Files:**
- Modify: `src/agaistock/config.py`（新增 `data_dir()`）
- Modify: `src/agaistock/cli.py`（`ReviewContext.data_dir` 改用 `config.data_dir()`）
- Modify: `miniapps/agaistock/miniapp/node/server.mjs`（导出 `buildKernelEnv()`，`runKernel` 与 `start()` 用它）
- Modify: `tests/test_config.py`（`data_dir()` 的 3 条行为）
- Modify: `tests/test_cli.py`（`ReviewContext.data_dir` 取自环境变量）
- Modify: `miniapps/agaistock/test/api.test.mjs`（内核子进程拿得到 `AGAISTOCK_DATA_DIR`）
- Modify: `miniapps/agaistock/src/agaistock/**`（由 `tools/sync-kernel.py` 生成）

**Interfaces:**
- Consumes: `context.dataDir`（宿主给的）
- Produces:
  - `agaistock.config.data_dir() -> Path` —— `AGAISTOCK_DATA_DIR` 优先，否则 `repo_root()/"data"`
  - `server.mjs` 新导出 `buildKernelEnv(options) -> object`
  - `runKernel(args, options)` 的 `options` 新增 `dataDir`

- [ ] **Step 1: 写测试（RED）**

`tests/test_config.py` 追加（该文件已 `import os` / `from unittest import mock`；没有就先补）：

```python
class DataDirTest(unittest.TestCase):
    def test_env_var_wins(self):
        with mock.patch.dict(os.environ, {"AGAISTOCK_DATA_DIR": "/tmp/host-data"}):
            self.assertEqual(config.data_dir(), Path("/tmp/host-data"))

    def test_falls_back_to_repo_data_dir(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(config.data_dir(), config.repo_root() / "data")

    def test_blank_env_var_is_treated_as_unset(self):
        with mock.patch.dict(os.environ, {"AGAISTOCK_DATA_DIR": "   "}):
            self.assertEqual(config.data_dir(), config.repo_root() / "data")
```

> `mock.patch.dict(os.environ, {}, clear=True)` 会清空整个环境变量 —— 在 Windows 上
> 可能让 `Path` 解析出问题；更稳的写法是 `clear=False` + 先 `os.environ.pop`。
> **实现者选一种能稳定通过的方式，但三条行为语义必须一致。**

`tests/test_cli.py` 追加（照抄同文件里已有的
`test_review_wires_llm_client_into_review_context` 捕获 ctx 的写法）：

```python
    def test_review_data_dir_comes_from_the_host_env_var(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "a.db"
            captured = {}

            def fake_run_reviewers(ctx, reviewers):
                captured["ctx"] = ctx
                return []

            with mock.patch.object(cli, "run_reviewers", side_effect=fake_run_reviewers), \
                 mock.patch.dict(os.environ, {"AGAISTOCK_DATA_DIR": tmp}):
                code = cli.main([
                    "review", "--symbol", "002378", "--name", "章源钨业",
                    "--text", "还能拿半年", "--db", str(db_path), "--json",
                ])
            self.assertEqual(code, 0)
            self.assertEqual(captured["ctx"].data_dir, Path(tmp))
```

`miniapps/agaistock/test/api.test.mjs`：把顶部的 server.mjs 导入改成具名导入两个函数，
再在文件末尾追加两条测试。

```javascript
// 顶部：原来只 import handleRoute，现在多带一个 buildKernelEnv
import { handleRoute, buildKernelEnv } from '../miniapp/node/server.mjs';
```

```javascript
// 文件末尾追加（该文件已 import assert / test）
test('the kernel gets the host data dir, not the installed package dir', () => {
  const env = buildKernelEnv({ dbPath: 'D:\\host\\data\\agaistock.db', dataDir: 'D:\\host\\data' });
  assert.equal(env.AGAISTOCK_DB, 'D:\\host\\data\\agaistock.db');
  assert.equal(env.AGAISTOCK_DATA_DIR, 'D:\\host\\data');
});

test('the kernel env never invents a data dir on its own', () => {
  const env = buildKernelEnv({});
  assert.equal(env.AGAISTOCK_DATA_DIR, undefined);
});

test('a blank data dir is not a usable path', () => {
  const env = buildKernelEnv({ dataDir: '' });
  assert.equal(env.AGAISTOCK_DATA_DIR, undefined);
});
```

- [ ] **Step 2: `config.data_dir()`**

`src/agaistock/config.py` —— 加 `import os`，并在 `repo_root()` 之后加：

```python
DATA_DIR_ENV = "AGAISTOCK_DATA_DIR"


def data_dir() -> Path:
    """运行期数据目录（数据库之外的可写工作区）。

    宿主（Mini App 的 Node 侧）通过 `AGAISTOCK_DATA_DIR` 指向 `context.dataDir`。
    插件目录是**安装产物**：可能被宿主重装覆盖，也可能以只读方式安装 ——
    运行期产物不能写在那里。

    未设置时退回 `repo_root()/"data"`（仓库内直接跑 CLI 的开发场景）。
    """
    override = os.environ.get(DATA_DIR_ENV, "").strip()
    if override:
        return Path(override)
    return repo_root() / "data"
```

- [ ] **Step 3: `cli.py` 改用它**

`src/agaistock/cli.py` 第 152 行：

```python
            data_dir=config.data_dir(),
```

- [ ] **Step 4: `server.mjs` 传 `AGAISTOCK_DATA_DIR`**

把 env 的组装抽成可测的纯函数，`runKernel` 与 `start()` 都用它：

```javascript
/**
 * 组装内核子进程的环境变量。
 *
 * 运行期的两样东西都必须落宿主给的数据目录（`context.dataDir`）：
 *  - 数据库：AGAISTOCK_DB
 *  - 缠论分析工作目录：AGAISTOCK_DATA_DIR
 * 插件目录是**安装产物**（可能被重装覆盖，也可能只读安装），运行产物不能写在那里。
 */
export function buildKernelEnv(options = {}) {
  const env = {
    ...process.env,
    PYTHONPATH: options.pythonPath || KERNEL_SRC,
    PYTHONIOENCODING: 'utf-8',
  };
  if (options.dbPath) env.AGAISTOCK_DB = options.dbPath;
  if (options.dataDir) env.AGAISTOCK_DATA_DIR = options.dataDir;
  return env;
}
```

`runKernel`：把 env 的组装交给 `buildKernelEnv`，并多取一个 `dataDir`。

原来这两行（在 `return new Promise(...)` 之后）：

```javascript
    const env = { ...process.env, PYTHONPATH: pythonPath, PYTHONIOENCODING: 'utf-8' };
    if (dbPath) env.AGAISTOCK_DB = dbPath;
```

**替换成一行**：

```javascript
    const env = buildKernelEnv({ pythonPath, dbPath, dataDir });
```

并且在 `const dbPath = options.dbPath || '';` **后面加一行**：

```javascript
  const dataDir = options.dataDir || '';
```

`start()` 里把 `dataDir` 传进去：

```javascript
  const kernel = (args) => runKernel(args, {
    cwd: pluginRoot,
    pythonPath: join(pluginRoot, 'src'),
    dbPath,
    dataDir,
  });
```

- [ ] **Step 5: 同步内核副本、跑全量测试**

```bash
python tools\sync-kernel.py
python tools\sync-kernel.py --check
python -m unittest discover -s tests -t .
node --test "miniapps/agaistock/test/*.test.mjs"
```

- [ ] **Step 6: 写回设计文档**

设计文档两处要改：

- **§16.2 第 3 条**：把「**数据库**必须落 `context.dataDir`」改成
  「**运行期产物（数据库 + 缠论分析工作目录）都落 `context.dataDir`**」，
  并**删掉**「缓存每次重装要重算」那句（`build_structure` 每次都重算，本来就不复用，
  这条收益本来就不存在）。同时把那条 ⚠️ 例外说明删掉。
- **§16.4**：删掉「缠论分析缓存仍写在插件包里」这条（已修），
  其余条目（观察版本链、`contract.py`、`engine.py`、`persist()`、`mcp/`、上游 resonance）
  **保持不动**。

- [ ] **Step 7: Commit**

```bash
git add src/agaistock miniapps/agaistock/src miniapps/agaistock/config tests miniapps/agaistock/miniapp/node/server.mjs miniapps/agaistock/test/api.test.mjs docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md
git commit -m "fix: keep the chanlun work dir out of the installed package" -- src/agaistock miniapps/agaistock/src miniapps/agaistock/config tests miniapps/agaistock/miniapp/node/server.mjs miniapps/agaistock/test/api.test.mjs docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md
```

> **不要用 `git add -A`**（Global Constraint 14）。内核副本目录必须与源一起提交，
> 否则 `tests/test_kernel_vendor.py` 的漂移守卫会红。

- [ ] **Step 8: 重新发布并实测验证**

```bash
miniapp { action: "publish", pluginId: "agaistock", sourcePath: "<repo>/miniapps/agaistock" }
miniapp { action: "open",    pluginId: "agaistock" }
```

跑一次点评，然后确认：
- 安装副本的 `package/data/` 下**没有**新生成 `chanlun/` 目录
- 宿主数据目录 `…\plugin-data\liveboards\agaistock\` 下**有** `chanlun/002378/`

---

### Task 20 · fix round 1 — 补上 `start()` 接线的回归护栏 + 让内核 env 不受宿主环境影响

> ⚠️ **本小节已被 fix round 2 取代**：`buildKernelOptions` 与那条源码断言
> （「start() wires the kernel through buildKernelOptions」）**都删了** ——
> 它们只锚在「调用点字面量存在」，验证不了数据流。护栏改成**行为断言**，
> 见下面 `### Task 20 · fix round 2` 小节。**别照着本小节的写法实现。**

> **来源**：Task 20 的独立终审（verifier）—— **0 Critical / 0 Important，2 Minor + 4 Nit**。
> 控制器已**独立复现**两个 Minor（不是采信评审自报）。

**Minor 1（必须修）：`context.dataDir → runKernel → AGAISTOCK_DATA_DIR` 这段接线没有任何测试护栏。**

终审做了 8 组变异，把 `start()` 里的 `dataDir` 去掉、或改成传 `pluginRoot`，**两套测试都仍然全绿**。
控制器独立复现（`.tmp/task20-fix/check_m6_m7.py` —— **仅本地脚本，被 `.gitignore`
忽略，不在仓库里**，后来人无法直接复跑，只能照下面的描述重建）：

```
M6: start() 不再传 dataDir          *** 漏过（测试仍全绿）***  ℹ tests 54 | ℹ pass 54 | ℹ fail 0
M7: start() 传 pluginRoot 而不是 dataDir  *** 漏过（测试仍全绿）***  ℹ tests 54 | ℹ pass 54 | ℹ fail 0
```

这是整个修复的**核心** —— 一旦有人改 `start()` 忘了带 `dataDir`，缺陷会**静默复活**，而且没有一条测试会红。

**Minor 2（必须修）：两条 Node 断言不是封闭的，且它本身是个隐患。**

`buildKernelEnv` 展开 `process.env`，所以宿主环境里若已有 `AGAISTOCK_DATA_DIR`，即使 `options.dataDir` 为空，
它也会**被继承进内核**。终审与控制器都实测：

```
$env:AGAISTOCK_DATA_DIR='D:\ambient\host\data'; node --test "miniapps/agaistock/test/*.test.mjs"
ℹ tests 54 / ℹ pass 52 / ℹ fail 2
```

这不只是「测试不稳」—— **内核的环境变量不该由宿主的 ambient env 决定**。宿主里残留一个旧路径，
内核就会写到错误的地方，而且没有任何测试会提醒。

**修法**

1. `server.mjs` 抽出 `buildKernelOptions(context, pluginRoot)`：**由它独占
   `context.dataDir → {dbPath, dataDir}` 的映射**，一处说了算。`start()` 改用它。
2. `buildKernelEnv` **显式清掉**宿主环境里继承来的 `AGAISTOCK_DB` / `AGAISTOCK_DATA_DIR`
   （当 option 没给时），内核 env 完全由 option 决定 → 隐患与测试不稳一起解决。
3. 补测试（见 Step 1）。
4. 文档订正 4 条（见 Step 4）。

**Files:**
- Modify: `miniapps/agaistock/miniapp/node/server.mjs`
- Modify: `miniapps/agaistock/test/api.test.mjs`
- Modify: `docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md`
- Modify: `docs/superpowers/plans/2026-11-24-reviewer-layer-and-chanlun-reviewer.md`

**Interfaces:**
- Consumes: `context.dataDir`（宿主给的）
- Produces:
  - `server.mjs` 新导出 `buildKernelOptions(context, pluginRoot) -> {cwd, pythonPath, dbPath, dataDir}`
  - `buildKernelEnv(options)` 的语义收紧：**只认 option，不认宿主 ambient env**

- [ ] **Step 1: 写测试（RED）**

`miniapps/agaistock/test/api.test.mjs`：顶部改成具名导入三个函数。

```javascript
import { handleRoute, buildKernelEnv, buildKernelOptions } from '../miniapp/node/server.mjs';
```

在文件末尾追加：

```javascript
test('the kernel options carry the host data dir, not the plugin dir', () => {
  const context = { dataDir: 'D:\\host\\data', pluginRoot: 'D:\\pkg' };
  const opts = buildKernelOptions(context, 'D:\\pkg');
  assert.equal(opts.dataDir, 'D:\\host\\data');
  assert.equal(opts.dbPath, join('D:\\host\\data', 'agaistock.db'));
  assert.notEqual(opts.dataDir, 'D:\\pkg');
});

test('the kernel env is decided by the options, not by the host environment', () => {
  // 宿主环境里残留同名变量时，内核也**不能**继承它 —— 否则宿主一个旧路径
  // 就能把内核写到别处（曾经让本文件两条断言在 ambient env 下 fail 2）。
  process.env.AGAISTOCK_DATA_DIR = 'D:\\ambient\\host\\data';
  process.env.AGAISTOCK_DB = 'D:\\ambient\\host\\data\\agaistock.db';
  try {
    const bare = buildKernelEnv({});
    assert.equal(bare.AGAISTOCK_DATA_DIR, undefined);
    assert.equal(bare.AGAISTOCK_DB, undefined);
    const explicit = buildKernelEnv({ dbPath: 'D:\\x\\a.db', dataDir: 'D:\\x' });
    assert.equal(explicit.AGAISTOCK_DATA_DIR, 'D:\\x');
    assert.equal(explicit.AGAISTOCK_DB, 'D:\\x\\a.db');
  } finally {
    delete process.env.AGAISTOCK_DATA_DIR;
    delete process.env.AGAISTOCK_DB;
  }
});

test('start() wires the kernel through buildKernelOptions', () => {
  // 堵住「绕过 helper 直接手写 options」这条路。
  // ⚠️ 断言必须锚在**调用点**上：只写 /buildKernelOptions\(context, pluginRoot\)/
  // 会连函数**定义**（export function buildKernelOptions(context, pluginRoot) {）
  // 一起匹配上，于是「调用点被换成别的参数」这种变异照样漏过 —— 控制器实测过。
  const source = readFileSync(
    join(import.meta.dirname, '..', 'miniapp', 'node', 'server.mjs'),
    'utf8',
  );
  assert.match(source, /const kernelOptions = buildKernelOptions\(context, pluginRoot\);/);
});
```

> 该文件已 `import { readFileSync } from 'node:fs'` 与 `import { join } from 'node:path'`（源码断言先例见
> 同文件里 `runKernel resolves the kernel from the plugin bundle, not the repo` 一条）。

- [ ] **Step 2: `server.mjs` 抽出 `buildKernelOptions`**

在 `buildKernelEnv` **上面**加：

```javascript
/**
 * 内核子进程的启动参数。
 *
 * **由这里独占 `context.dataDir → {dbPath, dataDir}` 的映射** —— 数据库与
 * 缠论分析工作目录都必须落宿主给的数据目录，不能落插件目录（安装产物，
 * 可能被重装覆盖，也可能只读安装）。一处说了算，别在别处再拼一遍。
 */
export function buildKernelOptions(context, pluginRoot) {
  const dataDir = context.dataDir;
  return {
    cwd: pluginRoot,
    pythonPath: join(pluginRoot, 'src'),
    dbPath: join(dataDir, 'agaistock.db'),
    dataDir,
  };
}
```

`buildKernelEnv` 改成**先清掉继承来的同名变量**：

```javascript
export function buildKernelEnv(options = {}) {
  const env = {
    ...process.env,
    PYTHONPATH: options.pythonPath || KERNEL_SRC,
    PYTHONIOENCODING: 'utf-8',
  };
  // 内核的运行路径**只由宿主显式给的 option 决定**。不能让宿主环境里残留的
  // 同名变量继承进内核 —— 否则宿主里一个旧路径就能把内核写到别处。
  delete env.AGAISTOCK_DB;
  delete env.AGAISTOCK_DATA_DIR;
  if (options.dbPath) env.AGAISTOCK_DB = options.dbPath;
  if (options.dataDir) env.AGAISTOCK_DATA_DIR = options.dataDir;
  return env;
}
```

- [ ] **Step 3: `start()` 改用 `buildKernelOptions`**

`start()` 里现在的：

```javascript
  const dbPath = join(dataDir, 'agaistock.db');
  const kernel = (args) => runKernel(args, {
    cwd: pluginRoot,
    pythonPath: join(pluginRoot, 'src'),
    dbPath,
    dataDir,
  });
```

**替换成**：

```javascript
  const kernelOptions = buildKernelOptions(context, pluginRoot);
  const dbPath = kernelOptions.dbPath;
  const kernel = (args) => runKernel(args, kernelOptions);
```

> `dbPath` 变量后面还要传给 `handleRoute`，别删。

- [ ] **Step 4: 文档订正（4 条 Nit）**

1. **设计文档 §3.1** 的「（包内**没有**运行数据目录）」那一行补一句：
   包内**仍会在运行时累积 `__pycache__` 字节码**（无害：只读安装时 CPython 容忍 `.pyc` 写失败，
   终审实测内核仍 exit 0 且输出 JSON 有效）。「没有运行数据目录」说的是**数据**，不是字节码。
2. **本计划 Task 20 小节**里「上游脚本产出的 K 线与结构 JSON 落进插件包目录」
   收窄来源声明。
   > ⚠️ **本条在 fix round 1 没有执行，而且它写下来的来源判断本身是错的**：
   > 文件数是 **8** 个不是 9 个；**来源判断不可判定**（见 fix round 2 Step 3 第 3 条与
   > fix round 3 Step 3 第 1 条）。
   > 缺陷本身由**代码 + 只读安装复现**证明（不复现时 `work_dir.mkdir` 抛 `PermissionError`），
   > 不靠文件计数。
3. **本计划较早任务小节**（Task 13 的 CLI 段，约第 5029 行）残留的
   `data_dir=config.repo_root() / "data",` 片段要加一句「**已被 Task 20 取代**（见 Task 20 小节）」，
   免得有人照着它实现。
4. **设计文档 §16.4** 加两条已知限制：
   - `AGAISTOCK_DATA_DIR` 若给的是**相对路径**，会按内核 cwd 解析（安装副本里 cwd 就是包根）→
     将来要加绝对路径守卫；宿主目前总是给绝对路径，暂不可达。
   - 回落值 `repo_root()/"data"` 在**安装副本里指向包内** —— 环境变量是唯一的护栏，
     宿主侧一旦回归，缺陷会静默复活。（`buildKernelOptions` 把映射收到一处 + 源码断言，
     只能挡住本仓库内的改动，挡不住宿主回归。）

- [ ] **Step 5: 跑全量测试**

```bash
python -m unittest discover -s tests -t .
node --test "miniapps/agaistock/test/*.test.mjs"
node --check miniapps/agaistock/miniapp/node/server.mjs
node tools\check-spec.mjs docs\superpowers\plans\2026-11-24-reviewer-layer-and-chanlun-reviewer.md --external docs\superpowers\specs\2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md --external docs\superpowers\specs\2026-11-24-stock-review-app-architecture.md
```

**额外的封闭性验证（必做）**：

```bash
$env:AGAISTOCK_DATA_DIR='D:\ambient\host\data'; node --test "miniapps/agaistock/test/*.test.mjs"
```

预期：**57/57 全绿**（修之前这里是 52/54、fail 2；加了 3 条新测试后总数从 54 变成 57）。

**并重跑变异检查**（`.tmp/task20-fix/check_m6_m7.py` —— **仅本地脚本，被 `.gitignore`
忽略，不在仓库里**；控制器已把变异更新成下面三种「真实回归」形态）：

| 变异 | 期望被哪条测试抓住 |
|---|---|
| `buildKernelOptions` 不再给 `dataDir` | 「the kernel options carry the host data dir…」 |
| `start()` 绕过 helper、手写 options | 「start() wires the kernel through buildKernelOptions」 |
| `buildKernelOptions` 用 `pluginRoot` 而不是 `context.dataDir` | 「the kernel options carry the host data dir…」 |

预期：**三种全部被捕获**（修之前终审的 M6/M7 两种全部漏过）。

> ⚠️ 断言必须锚在**调用点**上。只写 `/buildKernelOptions\(context, pluginRoot\)/` 会连
> 函数**定义**一起匹配上，变异照样漏过 —— 控制器实测踩过这个坑。

- [ ] **Step 6: Commit**

```bash
git add miniapps/agaistock/miniapp/node/server.mjs miniapps/agaistock/test/api.test.mjs docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md docs/superpowers/plans/2026-11-24-reviewer-layer-and-chanlun-reviewer.md
git commit -m "fix: guard the host data dir wiring and make the kernel env hermetic" -- miniapps/agaistock/miniapp/node/server.mjs miniapps/agaistock/test/api.test.mjs docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md docs/superpowers/plans/2026-11-24-reviewer-layer-and-chanlun-reviewer.md
```

> **不要用 `git add -A`**（Global Constraint 14）。
> 本轮**不改** `src/agaistock/**` —— 若你确实需要改内核源码，必须先跑
> `python tools/sync-kernel.py` 并把内核副本一起提交。

---

### Task 20 · fix round 2 — 把「调用点字面量」护栏换成**行为**护栏

> **来源**：Task 20 fix round 1 的 scoped 复审（verifier）—— **PASS-WITH-NITS**，
> 0 Critical / 0 Important，但有 **3 个 Minor + 3 个 Nit**。
> 控制器已独立复核每个结论（评审方的变异脚本在 `.tmp\task20-fix-review\`，控制器自己又跑了一轮）。

> **控制器已预验证本节**：本节的代码被抽到沙盒副本
> （`.tmp\task20-fix2\sandbox\agaistock\`）**实跑过** —— 原型 58 条测试全绿；
> 再打上 13 组变异（M8/M9/M14/M15/M16/C4 + 7 组额外回归形态），
> **13 组全部被护栏捕获，且每组红的是护栏集合里的测试**（不是无关测试碰巧红）。
> 实现时若测试名与本节写法一致，这套判据可直接复用。

> ⚠️ **本小节已被 fix round 3/4/5 补充**：默认内核工厂、`start()` 局部 `dataDir`、
> argv `--db` 通道（`handleRoute` 层）、**argv 拼接点（最后一公里）**四处盲区已补
> （见下面 `### Task 20 · fix round 3` / `### fix round 4` / `### fix round 5` 小节）——
> **别照着本小节 Step 2e 的默认实现写法实现**（它没把 `deps.spawnFn` 透传下去）。
> **断言要落在 `runKernel` 的 `spawnFn` 边界** —— 那里抓到的 argv 就是进程实际收到的参数，
> 任何上游层（`handleRoute`、默认内核工厂、`runKernel` 自身）的动手脚都躲不掉。

**Minor 1（headline）：fix round 1 的源码断言只锚定「调用点字面量存在」，没有验证数据流。**

评审方自己写的变异脚本给出 17 组结果，其中 **6 组漏过**（57/57 全绿）：

| # | 变异 | 结果 |
|---|---|---|
| M8 | `start()` 保留 helper 调用，但在 `runKernel` 处 `{...kernelOptions, dataDir: pluginRoot}` | **漏过** |
| M9 | 同上，改为覆写 `dbPath` | **漏过** |
| M14 | `start()` 里 `delete kernelOptions.dataDir` | **漏过** |
| M15 | `start()` 里 `kernelOptions.dataDir = pluginRoot` | **漏过** |
| M16 | `start()` 里 `kernelOptions.dbPath = join(pluginRoot,'agaistock.db')` | **漏过** |
| C4 | 诱饵：保留 helper 调用但丢弃结果，真正用的是手写 options | **漏过** |

**M8/M14/M15 会把内核的 `AGAISTOCK_DATA_DIR` 指回插件目录 —— 正是 Task 20 要消灭的那个缺陷复活。**
评审方用真实内核子进程证实了 M8 的危害：

```
pristine : {"AGAISTOCK_DATA_DIR": "D:\\host\\data", "AGAISTOCK_DB": "D:\\host\\data\\agaistock.db"}
M8 形态  : {"AGAISTOCK_DATA_DIR": "D:\\pkg"}   ← 插件目录
```

**根因**：`buildKernelOptions(context, pluginRoot)` 返回一个**中间对象**，
`start()` 把它交给 `runKernel`。在这个中间对象上做的任何改动，行为断言都看不见 ——
fix round 1 的三条测试全都测的是**纯函数**，没有一个测到「`start()` 实际怎么用它」。

**Minor 2**：§16.4 新增限制的括号写「源码断言……**只能挡住本仓库内的改动**」——
这句**高估了护栏**：M14/M15/M16 正是本仓库内的改动，且全部漏过。

**Minor 3**：计划里的「`package/data/chanlun/002378/` 下有 **9 个文件**」**数字错了** ——
上游脚本产出集合是 **8** 个（`kline_<level>`×3 + `chan_analysis_<level>`×3 + `chan_analysis.json` +
`chan_multi_level.json`）。控制器复核：宿主 `dataDir\chanlun\002378\` 实测 **8** 个，
`src/agaistock/data/chanlun/002378/`（仓库里那份）实测也是 **8** 个。
且该句引用的证据「安装副本里 `.pyc` 的 mtime 与仓库里的一致」**在现存安装副本上不成立**
（安装副本 24 个 `.pyc`，与仓库 mtime 相同的 **0** 个）。

**Nit 3**：fix round 1 的 hermeticity 测试 `finally` 是 `delete process.env.*`，
会抹掉运行者本已存在的 ambient 值（应该**保存 → 还原**）。

**Nit 4**：`start()` 与 `buildKernelOptions` 各自读了一次 `context.dataDir`，将来只改一处就会分叉。

**Nit 5**：计划里指向 `.tmp/task20-fix/check_m6_m7.py` —— 该文件被 `.gitignore` 忽略，不在仓库里。

---

**修法：取消「中间对象」，让 env 由 context 直接算出，并把护栏换成三条行为断言。**

- `buildKernelEnv(context, pluginRoot)` —— **唯一一处决定内核运行路径的地方**，直接吃 context。
- `runKernel(args, context, pluginRoot, spawnFn)` —— env 在**最后一次**从 context 算出，
  中间没有任何可被覆写的对象。`spawnFn` 作为注入点，让测试能观测到**真实**子进程收到的 env。
- `start(context, deps)` —— `deps.createKernel` 是注入点，测试能观测到 `start()` 递给内核的
  context / pluginRoot / dbPath **原样**。
- 删掉 `buildKernelOptions` 与 fix round 1 那条源码断言（它们验证不了数据流）。

**Files:**
- Modify: `miniapps/agaistock/miniapp/node/server.mjs`
- Modify: `miniapps/agaistock/test/api.test.mjs`
- Modify: `docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md`
- Modify: `docs/superpowers/plans/2026-11-24-reviewer-layer-and-chanlun-reviewer.md`

**Interfaces:**
- Consumes: `context.dataDir`、`context.pluginRoot`（宿主给的）
- Produces:
  - `kernelDbPath(context) -> string` —— **一处**算出数据库路径
  - `buildKernelEnv(context, pluginRoot) -> object` —— 内核子进程的最终 env
  - `runKernel(args, context, pluginRoot, spawnFn)` —— `spawnFn` 是注入点
  - `start(context, deps)` —— `deps.createKernel` 是注入点；返回值多一个 `port`

- [ ] **Step 1: 改测试（RED）**

> ⚠️ **本步必须先处理 fix round 1 留下的旧测试**，否则 import 里的 `buildKernelOptions`
> 消失会**让整个测试文件加载失败**（57 条全红），而不是「按预期红」。

**1a) 改 import（第 6 行）**：

```javascript
import { handleRoute, buildKernelEnv, kernelDbPath, runKernel, start } from '../miniapp/node/server.mjs';
```

**1b) 删掉两条依赖 `buildKernelOptions` 的旧测试**：

- `test('the kernel options carry the host data dir, not the plugin dir', ...)` —— 整个删掉
  （`buildKernelOptions` 本轮被删除，功能由 `kernelDbPath` + `buildKernelEnv` 接管）。
- `test('start() wires the kernel through buildKernelOptions', ...)` —— 整个删掉
  （它是 fix round 1 的**源码断言**护栏，正是本轮要消灭的东西）。

**1c) 改写两条还活着的旧测试**（签名变了）：

- `test('the kernel env is decided by the options, not by the host environment', ...)`
  → 新签名是 `buildKernelEnv(context, pluginRoot)`，原来的 `buildKernelEnv({ dbPath, dataDir })`
  **不再合法**（`dbPath` 不再是入参）。改成：

```javascript
test('the kernel env is decided by the host context, not by the host environment', () => {
  // 宿主环境里残留同名变量时，内核也**不能**继承它 —— 否则宿主一个旧路径
  // 就能把内核写到别处（曾经让本文件两条断言在 ambient env 下 fail 2）。
  // ⚠️ finally 必须**保存 → 还原**，不能直接 delete —— delete 会抹掉运行者
  // 本来就有的 ambient 值（fix round 1 的 Nit 3）。
  const previousDir = process.env.AGAISTOCK_DATA_DIR;
  const previousDb = process.env.AGAISTOCK_DB;
  process.env.AGAISTOCK_DATA_DIR = 'D:\\ambient\\host\\data';
  process.env.AGAISTOCK_DB = 'D:\\ambient\\host\\data\\agaistock.db';
  try {
    const bare = buildKernelEnv({}, 'D:\\pkg');
    assert.equal(bare.AGAISTOCK_DATA_DIR, undefined);
    assert.equal(bare.AGAISTOCK_DB, undefined);
    const explicit = buildKernelEnv({ dataDir: 'D:\\x' }, 'D:\\pkg');
    assert.equal(explicit.AGAISTOCK_DATA_DIR, 'D:\\x');
    assert.equal(explicit.AGAISTOCK_DB, join('D:\\x', 'agaistock.db'));
  } finally {
    if (previousDir === undefined) delete process.env.AGAISTOCK_DATA_DIR;
    else process.env.AGAISTOCK_DATA_DIR = previousDir;
    if (previousDb === undefined) delete process.env.AGAISTOCK_DB;
    else process.env.AGAISTOCK_DB = previousDb;
  }
});
```

- `test('the kernel gets the host data dir, not the installed package dir', ...)`、
  `test('the kernel env never invents a data dir on its own', ...)`、
  `test('a blank data dir is not a usable path', ...)` —— **三条都保留**，
  但签名要补上第二个参数 `pluginRoot`（不传也能过，默认值是 `PLUGIN_ROOT`；
  显式传 `D:\\pkg` 更好断言）：

```javascript
test('the kernel gets the host data dir, not the installed package dir', () => {
  const env = buildKernelEnv({ dataDir: 'D:\\host\\data' }, 'D:\\pkg');
  assert.equal(env.AGAISTOCK_DATA_DIR, 'D:\\host\\data');
  assert.equal(env.AGAISTOCK_DB, 'D:\\host\\data\\agaistock.db');
});

test('the kernel env never invents a data dir on its own', () => {
  const env = buildKernelEnv({}, 'D:\\pkg');
  assert.equal(env.AGAISTOCK_DATA_DIR, undefined);
});

test('a blank data dir is not a usable path', () => {
  const env = buildKernelEnv({ dataDir: '' }, 'D:\\pkg');
  assert.equal(env.AGAISTOCK_DATA_DIR, undefined);
});
```

**1d) 在文件末尾追加三条**行为护栏测试（加上 1c 里改写的那条 ambient 测试，
这一层一共四条行为断言，覆盖三层：env 纯函数 / 真实 spawn 路径 / `start()` 注入点）：

```javascript
// ---- 内核运行路径的三层行为护栏 ----
// 上一轮的护栏只锚在「调用点字面量存在」，没验证数据流：把 helper 的结果在
// 传给 runKernel 之前覆写掉，测试照样全绿（评审方用 M8 复现过，会把内核的
// AGAISTOCK_DATA_DIR 指回插件目录）。这四条全部改成**行为断言**。

test('the kernel env puts both runtime paths in the host data dir', () => {
  const env = buildKernelEnv({ dataDir: 'D:\\host\\data' }, 'D:\\pkg');
  assert.equal(env.AGAISTOCK_DATA_DIR, 'D:\\host\\data');
  assert.equal(env.AGAISTOCK_DB, kernelDbPath({ dataDir: 'D:\\host\\data' }));
  assert.equal(env.AGAISTOCK_DB, join('D:\\host\\data', 'agaistock.db'));
  assert.equal(env.PYTHONPATH, join('D:\\pkg', 'src'));
});

test('the kernel subprocess actually receives the host data dir', async () => {
  // 走真实的 runKernel 路径，只把 spawn 换掉 —— 观测子进程**真的**收到的 env。
  const captured = [];
  const fakeChild = {
    stdout: { on() {} },
    stderr: { on() {} },
    kill() {},
    on(event, handler) {
      if (event === 'close') setImmediate(() => handler(0));
    },
  };
  await runKernel(
    ['list', '--db', 'x.db', '--json'],
    { dataDir: 'D:\\host\\data' },
    'D:\\pkg',
    (command, argv, options) => {
      captured.push({ command, argv, env: options.env });
      return fakeChild;
    },
  );
  assert.equal(captured.length, 1);
  assert.equal(captured[0].env.AGAISTOCK_DATA_DIR, 'D:\\host\\data');
  assert.equal(captured[0].env.AGAISTOCK_DB, join('D:\\host\\data', 'agaistock.db'));
  assert.equal(captured[0].env.PYTHONPATH, join('D:\\pkg', 'src'));
});

test('start() hands the host context to the kernel unchanged', async () => {
  // 堵住「在 helper 之后覆写」这一类：只要 start() 递给内核的不是宿主给的
  // context 原样，这条就红。start() 若绕过 createKernel 直接调 runKernel，
  // 下面的 seen 会是空的 —— 一样红。
  const seen = [];
  const pluginRoot = join(import.meta.dirname, '..');
  const dataDir = join(import.meta.dirname, '..', '..', '..', '.tmp', 'task20-fix2-test-data');
  const context = {
    dataDir,
    pluginRoot,
    listen: { port: 0, host: '127.0.0.1' },
    signal: new AbortController().signal,
  };
  const handle = await start(context, {
    createKernel: (ctx, root, dbPath) => (args) => {
      seen.push({ ctx, root, dbPath, args });
      return Promise.resolve({ code: 0, stdout: '{"items":[]}', stderr: '' });
    },
  });
  try {
    const response = await fetch(`http://127.0.0.1:${handle.port}/api/observations`);
    assert.equal(response.status, 200);
  } finally {
    await handle.dispose();
  }
  assert.ok(seen.length > 0, '内核必须真的被调用，且拿到宿主给的 context');
  assert.equal(seen[0].ctx.dataDir, dataDir);
  assert.equal(seen[0].root, pluginRoot);
  assert.equal(seen[0].dbPath, join(dataDir, 'agaistock.db'));
});
```

> `import.meta.dirname` 在本文件里指向 `miniapps/agaistock/test/`，所以 `join(import.meta.dirname, '..')`
> 就是插件根 `miniapps/agaistock`；`start()` 会从那里读 `miniapp/client/index.html` 与
> `miniapp/client/render.mjs`（真实文件都在）。`listen.port = 0` 让 OS 分配一个空闲端口；
> `start()` 的返回值里新增了 `port` 字段，测试要用它拼 URL（Node ≥18 有全局 `fetch`，
> 本仓库 Node 24）。
> `dataDir` 用仓库根 `.tmp/` 下的目录 —— `start()` 会 `mkdir` 它，测试跑完可留着（`.tmp/` 已 gitignore）。

- [ ] **Step 2: `server.mjs` 改造成 context 驱动**

**a) 新增 `kernelDbPath`，并把 `buildKernelEnv` 改成吃 context：**

```javascript
/**
 * 内核数据库路径 —— **一处**说了算。
 *
 * 数据库与缠论分析工作目录都必须落宿主给的数据目录（`context.dataDir`），
 * 不能落插件目录（安装产物，可能被重装覆盖，也可能只读安装）。
 */
export function kernelDbPath(context = {}) {
  return context.dataDir ? join(context.dataDir, 'agaistock.db') : '';
}

/**
 * 内核子进程的环境变量 —— **唯一一处决定内核运行路径的地方**。
 *
 * 直接吃宿主的 context：调用方**拿不到**中间对象，也就无法在传给内核之前
 * 把路径改成别的（上一轮正是栽在这里：源码断言只看得到「调用点字面量」，
 * 看不到数据流）。
 *
 * 内核的运行路径**只由宿主的 context 决定**：宿主环境里残留的同名变量一律
 * 先清掉，否则宿主一个旧路径就能把内核写到别处。
 */
export function buildKernelEnv(context = {}, pluginRoot = PLUGIN_ROOT) {
  const env = {
    ...process.env,
    PYTHONPATH: join(pluginRoot, 'src'),
    PYTHONIOENCODING: 'utf-8',
  };
  delete env.AGAISTOCK_DB;
  delete env.AGAISTOCK_DATA_DIR;
  if (context.dataDir) {
    env.AGAISTOCK_DB = kernelDbPath(context);
    env.AGAISTOCK_DATA_DIR = context.dataDir;
  }
  return env;
}
```

> ⚠️ **保留 `const KERNEL_SRC = join(PLUGIN_ROOT, 'src');`** ——
> 现有测试 `runKernel resolves the kernel from the plugin bundle, not the repo`
> 断言这条字面量存在，删了它那条测试会红（那条测试本身是好的，它守的是
> 「插件根推导方式」而不是「路径映射」）。
> `kernelDbPath` 的 `context.dataDir` 为空时返回 `''`（不是抛错）——
> `join(undefined, ...)` 会抛 TypeError，宿主少给一个字段就崩在启动路径上不合适。

**b) `runKernel` 改成吃 context，并把 `spawn` 变成注入点：**

```javascript
export function runKernel(args, context = {}, pluginRoot = PLUGIN_ROOT, spawnFn = spawn) {
  const cwd = pluginRoot;
  const env = buildKernelEnv(context, pluginRoot);
  return new Promise((resolve) => {
    // **必须带 `-S`**：editable 安装（`pip install -e .`）注册的是 meta-path finder，
    // 优先级**高于** PYTHONPATH —— 实测开发机上不加 `-S` 时 `import agaistock`
    // 命中的是仓库里那份，不是插件自带的副本，自包含就成了空话。
    // `-S` 同时禁用 site-packages，正好把「业务内核零第三方依赖」（Global Constraint 2）
    // 从约定变成运行时硬约束：内核一旦依赖第三方包，Mini App 会立刻报错而不是
    // 悄悄依赖用户机器上的环境。
    const child = spawnFn('python', ['-S', '-m', 'agaistock.cli', ...args], {
      cwd,
      env,
      encoding: 'utf8',
    });
    ...（其余不变：stdout/stderr 收集、超时、close/error 处理）
  });
}
```

**c) 删掉 `buildKernelOptions`**（它的职责被 `buildKernelEnv` + `kernelDbPath` 接管，
中间对象正是这一轮要消灭的东西）。

**d) `handleRoute` 的默认 kernel**：原来是 `kernel = runKernel`，新签名下会丢掉 dataDir。
→ 改成解构后兜底：

```javascript
  const {
    context = {},
    ...
    kernel: injectedKernel,
    dbPath = '',
    dataDir = '',
  } = options;
  // 默认内核也走 context 驱动：只有宿主给了 dataDir 才带上运行路径。
  const kernel = injectedKernel || ((args) => runKernel(args, { dataDir }));
```

**e) `start(context, deps)`**：

```javascript
export async function start(context, deps = {}) {
  ...
  // 运行数据落宿主给的数据目录，**不是**插件目录 ——
  // 插件目录是安装产物（可能被只读安装、也可能被 Host 重装覆盖），
  // dataDir 才是运行时可写、跨重启保留的数据位置。
  // 数据库路径由 kernelDbPath 一处说了算（不再有可被覆写的中间对象）。
  const dbPath = kernelDbPath(context);

  // 内核工厂可注入：测试要能观测 start() 到底把什么递给了内核。
  // 默认实现把**宿主的 context 原样**传给 runKernel —— 中间不再有任何
  // 可被改写路径的对象，上一轮的缺陷（M8/M9/M14/M15/M16）因此无处可藏。
  const createKernel = deps.createKernel
    || ((ctx, root) => (args) => runKernel(args, ctx, root));
  const kernel = createKernel(context, pluginRoot, dbPath);
  ...
  return { dispose, port: server.address()?.port };
}
```

> `server.address()` 在 listen 完成后才有值；`start()` 里已经 `await` 过 listen，
> 所以直接取即可。`port` 是给测试拼 URL 用的，宿主只解构 `{ dispose }` 不受影响。
> `dbPath` **只算一次**（fix round 1 的 Nit 4：两处各读一遍 `context.dataDir`，
> 将来只改一处就会分叉）。

- [ ] **Step 3: 文档订正（Minor 2 / Minor 3 + 3 个 Nit）**

1. **设计文档 §16.4** 的括号：「源码断言……只能挡住本仓库内的改动」→
   改成如实描述现在的三层行为护栏（env 纯函数 / 真实 spawn 路径 / `start()` 注入点），
   并保留「宿主侧回归仍挡不住」这一条。
2. **设计文档 §3.1** 的 `__pycache__` 说明：把「只读安装时 CPython 容忍 `.pyc` 写失败」
   这句**尚未独立复现**的历史结论标出来（Windows 的只读属性不阻断写入，
   要 POSIX 只读安装才能验），别把它写成已验证事实。
3. **计划 Task 20 小节**（约 8143 行）：「实测 9 个文件」→ **8 个**；
   并把「宿主会把 gitignored 产物一并拷进安装副本（`.pyc` mtime 与仓库里一致）」这句
   **换掉**—— ⚠️ **fix round 3 已复核：本条写下的来源结论方向反了**：
   当时认定「安装副本 24 个 `.pyc`，与仓库 mtime 相同的 **0** 个 ⇒ 宿主不拷 gitignored 产物」，
   但控制器实测**宿主持久安装目录**的 24 个 `.pyc` 与仓库插件包的 **mtime 24/24 完全相同**
   （其中 18 个**早于**运行时解包时刻）⇒ 「宿主会拷 gitignored 产物」这个一般命题**成立**。
   那 8 个 `data/chanlun/002378/*.json` 仍是**运行时写的**（三处安装目录都没有 `data/`）——
   ⇒ **来源不可泛化**，正确表述见 **fix round 3 Step 3 第 1 条**。
4. **计划里指向 `.tmp/task20-fix/check_m6_m7.py` 的地方**（约 8389、8589 行）：
   注明「仅本地脚本，被 `.gitignore` 忽略，不在仓库里」。
5. **计划 fix round 1 小节**（约 8381 行）：加一句「本小节**已被 fix round 2 取代**
   （`buildKernelOptions` 与那条源码断言都删了）」，免得后来人照着 round 1 的写法实现。

- [ ] **Step 4: 跑全量测试**

```bash
python -m unittest discover -s tests -t .
node --test "miniapps/agaistock/test/*.test.mjs"
node --check miniapps/agaistock/miniapp/node/server.mjs
node tools\check-spec.mjs docs\superpowers\plans\2026-11-24-reviewer-layer-and-chanlun-reviewer.md --external docs\superpowers\specs\2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md --external docs\superpowers\specs\2026-11-24-stock-review-app-architecture.md
```

**额外的封闭性验证（必做）**：

```bash
$env:AGAISTOCK_DATA_DIR='D:\ambient\host\data'; node --test "miniapps/agaistock/test/*.test.mjs"
```

预期：**全绿**。

**并重跑评审方的 17 组变异**：评审方的脚本在 `.tmp\task20-fix-review\`（本地，不在仓库里）。
控制器会另外提供一份 `.tmp\task20-fix2\mutations.py`（含 M8/M9/M14/M15/M16/C4 这 6 组漏过的），
预期：**六组全部被捕获**。

- [ ] **Step 5: Commit**

```bash
git add miniapps/agaistock/miniapp/node/server.mjs miniapps/agaistock/test/api.test.mjs docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md docs/superpowers/plans/2026-11-24-reviewer-layer-and-chanlun-reviewer.md
git commit -m "fix: guard the kernel runtime paths with behavioural assertions" -- miniapps/agaistock/miniapp/node/server.mjs miniapps/agaistock/test/api.test.mjs docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md docs/superpowers/plans/2026-11-24-reviewer-layer-and-chanlun-reviewer.md
```

> **不要用 `git add -A`**（Global Constraint 14）。
> 本轮**不改** `src/agaistock/**` —— 若确实需要改内核源码，必须先跑
> `python tools/sync-kernel.py` 并把内核副本一起提交。

---

### Task 20 · fix round 3 — 堵住「默认实现」这条盲区 + 纠正来源说明的方向

> **来源**：Task 20 fix round 2 的 scoped 复审（verifier）—— **PASS-WITH-MINORS**，
> 0 Critical，但有 **3 条 Important + 2 条 Minor + 2 条 Nit**。
> 控制器已**独立复现全部 3 条 Important**（自己的变异脚本 + 自己的 `.pyc` 来源链实测），
> 结论与评审方一致。

> **控制器已预验证本节（「先红后绿」）**：把本节的改动落到沙盒副本
> （`.tmp\task20-fix3\sandbox\agaistock\`）实跑，用**加固后**的变异脚本
> （含阴性对照、护栏集合收紧、覆盖生产路径）分别打两个版本：
> - 对着**修复前**的实现：**8 组漏过** —— B1 / B2 / F1 / F2 / F3 / E3P / E4P，
>   外加阴性对照 Z1（只改注释）**正确报漏过** ⇒ 这套 harness **会报漏过**，不是无脑报捕获；
> - 对着**修复后**的实现：上述 8 组**全部转为捕获**，且每组红的都是**行为**护栏；
>   只剩 H1（去掉「kernel 必填」守卫但**不**恢复默认分支 = 行为等价变异）正确漏过。

---

**Important 1（headline）：默认 `createKernel`（= 生产路径）完全没有护栏。**

fix round 2 的第三层护栏（`start() hands the host context to the kernel unchanged`）
**自己注入了 `createKernel`** —— 于是「宿主不传 `deps` 时走的那条默认实现」**从未被执行、也从未被观测**。

> **盲区与 fix round 1 同构**：fix round 1 锚在「调用点**字面量**」，
> fix round 2 的第三层锚在「调用点**入参**」—— 被观测的对象与实际生效的对象始终不是同一个。

控制器实测（沙盒，58 条测试）：

| 变异 | 结果 |
|---|---|
| B1：默认 `createKernel` 里 `ctx.dataDir` 被覆写成 `pluginRoot` | **exit 0 漏过** |
| B2：默认 `createKernel` 里 `ctx.dataDir` 被删掉 | **exit 0 漏过** |

评审方用端到端探针（只把 `spawn` 换成观测假 spawn，真调 `start(context)` **不传 deps**）证实：

```
PRISTINE : AGAISTOCK_DATA_DIR=…\hostdata          ✓
B1 变异  : AGAISTOCK_DATA_DIR=…\sbx\agaistock      ✗ 插件目录
```

⇒ **缺陷在生产路径上复活，且没有任何一条测试变红。**

**根因在计划本身**：fix round 2 的 Step 2e 原文就是
`|| ((ctx, root) => (args) => runKernel(args, ctx, root));`，
而 Step 1d 给的测试只观测 `createKernel` 的**入参**。
实现者是**逐字照抄计划**的 —— 这条 finding 针对**计划 + 实现**，不是针对实现者。

---

**Important 2：文档订正 3 的「来源说明」结论方向反了（控制器自己的错）。**

fix round 2 把「宿主会把 gitignored 产物一并拷进安装副本」判成**不成立**并**禁止**后来人再提。
控制器独立复核后确认：**那句话成立**，订正方向反了。

实测（epoch 秒，与时区无关）：

```
① 仓库插件包  miniapps/agaistock/src/agaistock/        24 个 .pyc
③ 宿主持久安装 ~/.minimax/plugins/agaistock/src/agaistock/  24 个 .pyc
   同名 24 个，mtime 完全相同 24/24，mtime 区间逐一相等（1795523403..1795526944）
④ 运行时解包副本 %TEMP%/mavis-miniapp-XXXX/package/    24 个 .pyc
   与 ③ 同名 24 个、mtime 相同 18 个（随包带进来）＋ 6 个晚于解包时刻（运行时写的）
```

⇒ **宿主确实把 gitignored 的 `__pycache__` 拷进了安装目录并保留 mtime。**
（`tools/sync-kernel.py` 的 `IGNORE = ("__pycache__", "*.pyc", "*.pyo")` 正好说明这批是 gitignored 产物。）

**但那 8 个 `data/chanlun/002378/*.json` 确实是运行时写的** ——
仓库插件包、宿主持久安装目录、运行时解包副本**三处都没有 `data/` 目录**，
它们只存在于宿主 `context.dataDir` 下。

⇒ 正确表述是「**来源不可泛化**：这 8 个 JSON 是运行时写的；但『宿主会拷 gitignored 产物』这个一般命题成立，
不能用文件计数或某个 `.pyc` 的 mtime 去推断别的文件的来源」。

---

**Important 3：`start()` 的局部 `dataDir`（`observations.json` 落点）无护栏。**

`server.mjs` 里 `start()` 另有一份局部 `dataDir` 决定 `observations.json` 写哪；
第三层护栏断言的是 `seen[0].ctx.dataDir`（context 里的），**两份之间没有任何护栏**。
控制器实测变异 F1（`const dataDir = context.pluginRoot || context.dataDir;`）→ **exit 0 漏过**
⇒ 观察卡会写进**插件目录**（与 Task 20 要消灭的缺陷同一家族）。

---

**Minor 1**：`handleRoute` 的默认 kernel 无护栏（变异 E3/E4 漏过）。
生产路径不可达（`start()` 总是注入），但 E4 正是缺陷形态。
→ 本轮**删掉这个默认分支**（`kernel` 变必填）—— 它本来就和 server.mjs 自己的注释
「依赖全部由调用方显式注入」矛盾。

**Minor 2**：第三层护栏的 `seen[0].root` 断言是**空断言** ——
测试用的 `pluginRoot = join(import.meta.dirname,'..')` 恰好**等于**模块常量 `PLUGIN_ROOT`，
于是「`start()` 忽略宿主给的 pluginRoot」这类变异在测试里是语义空操作（变异 F3 漏过）。
→ 本轮改用**scratch 插件根**（复制到临时目录），断言才有意义。

**Nit 1**：`runKernel` 的 `cwd` 没有任何断言（变异 F2 漏过）。
设计文档 §16.4 那条「`AGAISTOCK_DATA_DIR` 给相对路径会按内核 cwd 解析」依赖 `cwd === pluginRoot`。

---

**修法（一句话）：把「默认实现」也变成被观测面。**

- `start(context, deps)` 的默认 `createKernel` **透出 `deps.spawnFn`** ——
  `runKernel` 本来就有这个注入点，只是默认实现没把它传下去。
  透出来之后，**生产路径**就能被一条不注入 `createKernel` 的测试观测到。
- `handleRoute` 的 `kernel` 变**必填**（删掉默认分支）—— 盲区直接消失。
- 新增一条「观察卡落点」的行为断言（scratch 插件根 + scratch dataDir）。
- 文档：来源说明改回**如实描述**；§16.4 的「能挡住本仓库内的改动」改成
  「能挡住本仓库内**已覆盖到的**改动」。

**Files:**
- Modify: `miniapps/agaistock/miniapp/node/server.mjs`
- Modify: `miniapps/agaistock/test/api.test.mjs`
- Modify: `docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md`
- Modify: `docs/superpowers/plans/2026-11-24-reviewer-layer-and-chanlun-reviewer.md`

**Interfaces:**
- Consumes: `context.dataDir`、`context.pluginRoot`（宿主给的）
- Produces:
  - `start(context, deps)` —— `deps.spawnFn` 现在**会**被默认内核工厂透出
  - `handleRoute(request, response, options)` —— `options.kernel` 变成**必填**
  - 其余签名不变

- [ ] **Step 1: 改测试（RED）**

**1a) 顶部 import 补 `fs/promises` 与 `os`：**

```javascript
import { cp, mkdir, mkdtemp, rm } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
```

**1b) 加一个 scratch 插件根的helper**（放在 `fakeKernel` 后面）：

```javascript
/**
 * 造一个**临时插件根**。
 *
 * 为什么不用仓库里的 `miniapps/agaistock`：模块常量 `PLUGIN_ROOT` 恰好就等于它，
 * 于是「`start()` 忽略宿主给的 pluginRoot」这类变异在测试里是**语义空操作** ——
 * 断言会变成永远不可能失败的空断言（fix round 2 的 Minor 2）。
 * 复制到 scratch 后，pluginRoot 与模块常量**不同**，断言才有意义。
 */
async function makeScratchPluginRoot() {
  const base = await mkdtemp(join(tmpdir(), 'agaistock-plugin-'));
  const root = join(base, 'plugin');
  await mkdir(join(root, 'miniapp', 'client'), { recursive: true });
  await cp(
    join(import.meta.dirname, '..', 'miniapp', 'client'),
    join(root, 'miniapp', 'client'),
    { recursive: true },
  );
  return { base, root };
}
```

**1c) 把第三层护栏改用 scratch 插件根**（原来那条 `start() hands the host context to the kernel unchanged`）：

```javascript
test('start() hands the host context to the kernel unchanged', async () => {
  // 堵住「在 helper 之后覆写」这一类：只要 start() 递给内核的不是宿主给的
  // context 原样，这条就红。start() 若绕过 createKernel 直接调 runKernel，
  // 下面的 seen 会是空的 —— 一样红。
  const seen = [];
  const { base, root: pluginRoot } = await makeScratchPluginRoot();
  const dataDir = join(base, 'data');
  const context = {
    dataDir,
    pluginRoot,
    listen: { port: 0, host: '127.0.0.1' },
    signal: new AbortController().signal,
  };
  const handle = await start(context, {
    createKernel: (ctx, root, dbPath) => (args) => {
      seen.push({ ctx, root, dbPath, args });
      return Promise.resolve({ code: 0, stdout: '{"items":[]}', stderr: '' });
    },
  });
  try {
    const response = await fetch(`http://127.0.0.1:${handle.port}/api/observations`);
    assert.equal(response.status, 200);
  } finally {
    await handle.dispose();
    await rm(base, { recursive: true, force: true });
  }
  assert.ok(seen.length > 0, '内核必须真的被调用，且拿到宿主给的 context');
  assert.equal(seen[0].ctx.dataDir, dataDir);
  // ⚠️ pluginRoot 现在**不等于**模块常量 PLUGIN_ROOT —— 这条断言才有意义。
  assert.equal(seen[0].root, pluginRoot);
  assert.notEqual(seen[0].root, join(import.meta.dirname, '..', '..'));
  assert.equal(seen[0].dbPath, join(dataDir, 'agaistock.db'));
});
```

**1d) 追加「生产路径」测试**（**不注入 `createKernel`**，只注入 `spawn`）：

```javascript
test('the default kernel factory hands the host context to the kernel unchanged', async () => {
  // **不注入 createKernel** —— 宿主不传 deps 时走的就是这条生产路径。
  // 上一轮的护栏全都绕开了它（它们自己注入 createKernel），
  // 于是「默认实现把 dataDir 写回插件目录」这种变异能全绿通过（Important 1）。
  // 这里只把 spawn 换成观测用的假 spawn，其余走**真实默认实现**。
  const captured = [];
  const fakeChild = {
    stdout: { on() {} },
    stderr: { on() {} },
    kill() {},
    on(event, handler) {
      if (event === 'close') setImmediate(() => handler(0));
    },
  };
  const { base, root: pluginRoot } = await makeScratchPluginRoot();
  const dataDir = join(base, 'data');
  const context = {
    dataDir,
    pluginRoot,
    listen: { port: 0, host: '127.0.0.1' },
    signal: new AbortController().signal,
  };
  const handle = await start(context, {
    spawnFn: (command, argv, options) => {
      captured.push({ command, argv, env: options.env, cwd: options.cwd });
      return fakeChild;
    },
  });
  try {
    const response = await fetch(`http://127.0.0.1:${handle.port}/api/observations`);
    assert.equal(response.status, 200);
  } finally {
    await handle.dispose();
    await rm(base, { recursive: true, force: true });
  }
  assert.ok(captured.length > 0, '生产路径必须真的 spawn 了内核');
  assert.equal(captured[0].env.AGAISTOCK_DATA_DIR, dataDir);
  assert.equal(captured[0].env.AGAISTOCK_DB, join(dataDir, 'agaistock.db'));
  assert.equal(captured[0].env.PYTHONPATH, join(pluginRoot, 'src'));
  assert.equal(captured[0].cwd, pluginRoot);
});
```

**1e) 追加「观察卡落点」测试**（守 `start()` 的局部 `dataDir`）：

```javascript
test('start() keeps the observation file in the host data dir, not the plugin dir', async () => {
  // start() 内部另有一份**局部** dataDir 决定 observations.json 写哪 ——
  // 它和 context.dataDir 之间没有任何护栏（Important 3）。
  // 用 scratch 插件根做断言：写错也只污染临时目录，不污染仓库。
  const { base, root: pluginRoot } = await makeScratchPluginRoot();
  const dataDir = join(base, 'data');
  const context = {
    dataDir,
    pluginRoot,
    listen: { port: 0, host: '127.0.0.1' },
    signal: new AbortController().signal,
  };
  const handle = await start(context, {
    createKernel: () => async () => ({ code: 0, stdout: '{"items":[]}', stderr: '' }),
  });
  try {
    const response = await fetch(`http://127.0.0.1:${handle.port}/api/save`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ draft: { symbol: '002378', thesis: 'x' }, rawText: 'x' }),
    });
    assert.equal(response.status, 200);
  } finally {
    await handle.dispose();
  }
  assert.ok(
    existsSync(join(dataDir, 'observations.json')),
    '观察卡必须落在宿主给的 dataDir',
  );
  assert.ok(
    !existsSync(join(pluginRoot, 'observations.json')),
    '观察卡绝不能落进插件目录（那是安装产物）',
  );
  await rm(base, { recursive: true, force: true });
});
```

**1f) 追加「`kernel` 必填」的契约测试**（Minor 1）：

```javascript
test('handleRoute refuses to guess the kernel', async () => {
  // kernel 必须由调用方显式注入 —— 有默认分支就有盲区。
  await assert.rejects(
    () => handleRoute(makeRequest('GET', '/api/observations'), new FakeResponse(), {}),
    /kernel/,
  );
});
```

**1g) 给 `runKernel` 的 `cwd` 补断言**（Nit 1）——
在 `the kernel subprocess actually receives the host data dir` 里，
把捕获改成 `captured.push({ command, argv, env: options.env, cwd: options.cwd });`
并追加：

```javascript
  assert.equal(captured[0].cwd, 'D:\\pkg');
```

- [ ] **Step 2: `server.mjs` 改三处**

**a) 默认内核工厂透出 `deps.spawnFn`**（Important 1 的根因）：

```javascript
  // 内核工厂可注入：测试要能观测 start() 到底把什么递给了内核。
  // 默认实现把**宿主的 context 原样**传给 runKernel，并把 `deps.spawnFn` 透传下去 ——
  // 没有这个透传，**默认实现本身就是盲区**：宿主不传 deps 时走的就是这条生产路径，
  // 而上一轮的护栏全都自己注入 createKernel，从没观测过它。
  const createKernel = deps.createKernel
    || ((ctx, root) => (args) => runKernel(args, ctx, root, deps.spawnFn));
  const kernel = createKernel(context, pluginRoot, dbPath);
```

**b) `handleRoute` 的 `kernel` 变必填**（Minor 1）：

```javascript
  const {
    context = {},
    ...
    kernel,
    dbPath = '',
    dataDir = '',
  } = options;

  // kernel **必须**显式注入（不再有默认分支）：默认分支在生产路径上不可达，
  // 却能让「路径被写回插件目录」的变异悄悄溜过全部测试 —— 与 fix round 1
  // 栽的跟头同构。start() 永远会注入，测试也永远会注入。
  if (typeof kernel !== 'function') {
    throw new Error('handleRoute 需要显式注入 kernel');
  }
```

> `handleRoute` 里所有 `kernel(...)` 调用点**不用改** —— 变量名不变。
> `start()` 里的 `handleRoute(request, response, { ..., kernel, ... })` 也**不用改**。

**c) `start()` 的局部 `dataDir` 加一句注释**（说明它与 `context.dataDir` 的绑定关系）：

```javascript
  // 局部 dataDir 与 context.dataDir **必须是同一个**（下面那两条行为断言在守这件事）：
  // 它决定 observations.json 落哪，也决定内核的运行路径。
  const dataDir = context.dataDir;
```

- [ ] **Step 3: 文档订正（Important 2 + §16.4 的措辞）**

1. **计划 Task 20 小节**的「来源说明」（约 8146-8151 行）改成**如实描述**：

   ```
   > **来源说明**：这 8 个 `data/chanlun/002378/*.json` 是**运行时写的** ——
   > 判定依据是**内容与时间**：宿主 `context.dataDir` 下那 8 个 JSON 的 mtime
   > （`2026-11-24T14:34Z` 一带）与仓库根 `data/chanlun/002378/` 下那 8 个
   > （`2026-11-24T11:18Z` 一带）**不同** ⇒ 不是同一批拷过去的。
   > ⚠️ **不要**用「某个目录在不在」当证据 —— 宿主**会连 `data/` 目录一起拷**
   > （实测宿主的安装目录里出现过 `data/agaistock.db`，mtime 与「在包目录直跑内核」
   > 写出的时刻同一秒）。publish 前跑 `python tools/clean-package-artifacts.py` 清理。
   > ⚠️ 但**不要**把这条推广成「宿主不会拷 gitignored 产物」—— **那个一般命题是成立的**：
   > 实测仓库插件包 `miniapps/agaistock/src/agaistock/**` 的 24 个 `.pyc` 与宿主持久安装目录
   > `~/.minimax/plugins/agaistock/src/agaistock/**` 的 24 个 `.pyc` **mtime 24/24 完全相同**
   > （连亚秒都一致）⇒ 这批 `.pyc` **只能是宿主拷进去的**（`__pycache__` 是 gitignored 产物）。
   > 至于「有多少个早于解包时刻」**随解包批次变化**（实测 19/24 ~ 24/24），
   > **不要**把某个固定数字当证据 —— 决定性的是「mtime 逐个完全相同」这一条。
   > ⇒ **来源不可泛化**：文件计数、某个 `.pyc` 的 mtime，都不能用来推断别的文件的来源。
   > 缺陷本身由**代码 + 只读安装复现**证明，不靠文件计数。
   ```

2. **控制器上一轮补刀**（fix round 1 小节 Step 4 第 2 条，约 8569-8571 行）里
   「来源判断**已被证伪** / 那句话**不成立**」改成：
   「文件数是 **8** 个不是 9 个；**来源判断不可判定**（见 fix round 2 Step 3 第 3 条与 fix round 3 Step 3 第 1 条）」。

3. **设计文档 §16.4** 的括号：「三层**行为**护栏锁住它 —— …**能挡住本仓库内的改动**」
   → 改成「**能挡住本仓库内已被护栏覆盖到的改动**（env 纯函数 / 真实 spawn 路径 / `start()` 注入点 /
   **默认内核工厂**）；**未覆盖的路径仍无护栏**，宿主侧回归同样挡不住」。

4. **计划 fix round 2 小节**顶部加一句「本小节已被 fix round 3 补充（默认内核工厂与 `start()` 局部
   `dataDir` 两处盲区已补）」。

- [ ] **Step 4: 跑全量测试 + 加固后的变异脚本**

```bash
python -m unittest discover -s tests -t .
node --test "miniapps/agaistock/test/*.test.mjs"
node --check miniapps/agaistock/miniapp/node/server.mjs
node tools\check-spec.mjs docs\superpowers\plans\2026-11-24-reviewer-layer-and-chanlun-reviewer.md --external docs\superpowers\specs\2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md --external docs\superpowers\specs\2026-11-24-stock-review-app-architecture.md
```

**封闭性验证（必做）**：

```bash
$env:AGAISTOCK_DATA_DIR='D:\ambient\host\data'; node --test "miniapps/agaistock/test/*.test.mjs"
```

预期**全绿**。

**变异验证（必做）**：控制器会提供加固后的 `.tmp\task20-fix3\mutations.py`，它合并了
控制器的 13 组 + 评审方的 30 组（去重），并**加了两样东西**：

- **阴性对照**：只改一条注释 ⇒ **必须报「漏过」**（证明 harness 不会无脑报「捕获」）。
- **护栏集合收紧**：只认**行为**护栏（不再把「只断言 `undefined`」的弱测试算进护栏命中）。

覆盖的变异组至少包括：B1/B2（默认内核工厂）、F1（`start()` 局部 dataDir）、
E3/E4（`handleRoute` 默认 kernel）、F2（`cwd`）、F3（`pluginRoot`）、
M8/M9/M14/M15/M16/C4（fix round 1 漏过的 6 组）、X1–X7（回归形态）。
**预期：全部被捕获**。

> 控制器在派发前会先在沙盒上实跑一遍这套变异脚本，确认它**先红后绿** ——
> 即：对着**修复前**的实现跑，这几组必须是「漏过」，对着**修复后**的实现跑才是「捕获」。
> 没有这一步，这套脚本可能一直在报「捕获」而没人知道。

- [ ] **Step 5: Commit**

```bash
git add miniapps/agaistock/miniapp/node/server.mjs miniapps/agaistock/test/api.test.mjs docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md docs/superpowers/plans/2026-11-24-reviewer-layer-and-chanlun-reviewer.md
git commit -m "fix: observe the default kernel factory and the observation file landing dir" -- miniapps/agaistock/miniapp/node/server.mjs miniapps/agaistock/test/api.test.mjs docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md docs/superpowers/plans/2026-11-24-reviewer-layer-and-chanlun-reviewer.md
```

> **不要用 `git add -A`**（Global Constraint 14）。
> 本轮**不改** `src/agaistock/**` —— 若确实需要改内核源码，必须先跑
> `python tools/sync-kernel.py` 并把内核副本一起提交。

---

### Task 20 · fix round 4 — 钉住 **argv 通道**（真正裁决 DB 落点的那条）

> **来源**：Task 20 fix round 3 的 scoped 复审（verifier）—— **PASS-WITH-MINORS**，
> 0 Critical，但有 **1 条 Important + 2 条 Minor + 2 条 Nit**。
> 控制器已**独立复现全部**（自己的变异脚本 + 真实跑内核 + 自己的 `.pyc`/`data/` 实地测量），
> 结论与评审方一致。

**fix round 3 的 3 条 Important 已全部真正闭合** —— 评审方独立复现了「先红后绿」
（修复前漏过 8 组，与控制器预告**逐组吻合**；修复后全部转为捕获），
并用端到端探针（只换 `spawn`，真调 `start(context)` **不传 deps**）确认
**生产路径已被观测**：`env` / `cwd` / `PYTHONPATH` / `--db` 全部指向宿主给的值。

---

**Important 1（headline）：`handleRoute` 内部的 argv `--db` 通道零护栏。**

前两轮（包括 round 3）钉住的**全是 `env` 通道**。但**真正裁决 DB 落点的是 argv**：

```python
# src/agaistock/cli.py:26-32
def _default_db(db_arg: str | None) -> Path:
    if db_arg:
        return Path(db_arg)          # ← argv 优先，先于 env
    env_db = os.environ.get("AGAISTOCK_DB", "").strip()
    if env_db:
        return Path(env_db)
    return config.repo_root() / DEFAULT_DB
```

控制器**真实跑内核**证实（`--db` 指到 `.tmp` 下，不碰真实运行库）：

```
argv --db        = .tmp\argv-probe\plugindir\agaistock.db
env AGAISTOCK_DB = .tmp\argv-probe\hostdir\host.db
→ 插件目录里有 db = True    (argv 赢)
→ 宿主目录里有 db = False   (env 被忽略)
```

⇒ **env 绿 ≠ DB 落点对。**

评审方实测 6 组变异**全部漏过**（exit 0，61 条测试全绿）：

| # | 变异 | 评审方 | 控制器复现 |
|---|---|---|---|
| R7 | `handleRoute` 内部 `--db` 指回插件目录 | 漏过 | **漏过 ✓** |
| R8 | `countObservations` 的 `--db` 指回插件目录 | 漏过 | **漏过 ✓** |
| R9 | `/api/review` 的 `--db` 指回插件目录 | 漏过 | **漏过 ✓** |
| R10 | `DELETE` 的 `--db` 指回插件目录 | 漏过 | **漏过 ✓** |
| R11 | `reviews` 路由的 `--db` 指回插件目录 | （新增） | **漏过 ✓** |
| R3 | `start()` → `handleRoute` 调用点的 `dataDir` 指回插件目录 | 漏过 | **漏过 ✓** |

**R3 的危害不同**：它改的是 `dataDir`（不是 `dbPath`），所以 `--db` 断言抓不到 ——
真正受害的是 `/api/review` 的结构化草稿 `observation-*.json` 落进**插件目录**
（评审方端到端探针实证：插件根 `["miniapp","observation-mwvdle7d-sc54zp.json"]`，宿主 dataDir 空）。

> **这与 fix round 1/2/3 的盲区同构**：被观测的对象（`env`）与实际生效的对象（`argv`）不是同一个。

**Minor 1**：计划新写的证据句「其中 **18** 个还早于运行时解包时刻」**不可复现**。
控制器独立实测：仓库插件包与宿主持久安装目录的 24 个 `.pyc` **mtime 24/24 完全相同**（成立），
但「早于解包时刻」的个数随解包批次变化（评审方测 19/24，当前副本 24/24）⇒ **不能用固定数字**。

**Minor 2**：新写的「三处**都没有** `data/` 目录」**当时为假** ——
复审当天 08:02-08:03 实测三处**都有**（宿主安装目录与解包副本里的 `data/agaistock.db`
mtime = `2026-11-24 22:42:10`，与「在包目录直跑内核」写出的时刻同一秒
⇒ **宿主连 `data/` 目录一起拷**）。控制器随后清理了污染并加了防线
（`tools/clean-package-artifacts.py`，commit `36c0825`），所以**现在**三处确实都没有 ——
但这说明**「目录在不在」不是一条稳定的证据**。

> 结论本身仍成立：宿主 dataDir 下那 8 个 `chanlun/*.json` 与仓库根 `data/` 下那 8 个
> **mtime 不同**（控制器实测 `1795530866..875` vs `1795519127..135`）
> ⇒ 确为运行时写的，不是拷过去的。

**Nit 1**：计划 fix round 2 小节顶部横幅说「两处盲区已补」，本轮还剩一处生产面没补 ⇒ 扩成三处。

**Nit 2**：`handleRoute refuses to guess the kernel` 的 `rejects(/kernel/)` **偏弱** ——
守卫被整个删掉时 `TypeError: kernel is not a function` 也含 "kernel" ⇒ 漏过。

---

**修法：把 argv 通道也钉住。**

- 一条测试断言**所有路由**的 `--db` argv 都等于宿主给的 `dbPath`（覆盖 R7/R8/R9/R10/R11）。
- 一条走 `start()` 完整路径的测试断言**草稿落点**在宿主 dataDir（覆盖 R3）。
- 一条走 `start()` 完整路径的测试断言 `--db` argv（覆盖 R1 与调用点 `dbPath`）。
- 收紧 `rejects` 正则（覆盖 C3）。
- 文档：把两个不可复现的证据句改成**可复现**的表述。

**Files:**
- Modify: `miniapps/agaistock/test/api.test.mjs`
- Modify: `docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md`
- Modify: `docs/superpowers/plans/2026-11-24-reviewer-layer-and-chanlun-reviewer.md`

> ⚠️ **本轮不改 `server.mjs`** —— 评审方确认实现本身**正确**：
> 端到端探针在**未改动的实现**上实测 `env`/`cwd`/`PYTHONPATH`/`--db` **全部正确**。
> 这一轮是**补护栏**，不是改实现。

**Interfaces:**
- Consumes: 无（只加测试与文档）
- Produces: 无（对外契约不变）

- [ ] **Step 1: 加六条测试 + 收紧一条断言（`api.test.mjs`）**

**1a) 收紧 `handleRoute refuses to guess the kernel` 的正则**（Nit 2）：

```javascript
test('handleRoute refuses to guess the kernel', async () => {
  // kernel 必须由调用方显式注入 —— 有默认分支就有盲区。
  // ⚠️ 正则要匹配**守卫自己的消息**，不能只写 /kernel/ ——
  // 守卫被删时 `TypeError: kernel is not a function` 也含 "kernel" ⇒ 会漏过。
  await assert.rejects(
    () => handleRoute(makeRequest('GET', '/api/observations'), new FakeResponse(), {}),
    /需要显式注入 kernel/,
  );
});
```

**1b) 追加六条测试**（文件末尾）：

```javascript
// ---- argv 通道护栏（fix round 4）----
// Python 侧 `_default_db()` 是 **argv 优先于 env**（src/agaistock/cli.py:26-32：
// `if db_arg: return Path(db_arg)` 先于 env 分支）⇒ 真正裁决 DB 落点的是
// `handleRoute` 内部那些 `kernel([... '--db', dbPath, ...])`，**不是** env。
// 前三轮只钉住了 env 通道，于是「把 --db 改回插件目录」这种变异能全绿通过。
test('every kernel call carries the host db path', async () => {
  const calls = [];
  const kernel = async (args) => {
    calls.push(args);
    return { code: 0, stdout: '{"items":[]}', stderr: '' };
  };
  const dbPath = 'D:\\host\\data\\agaistock.db';
  // ⚠️ dataDir 必须是个**真实存在**的目录：/api/review 会往 draftDir 写草稿文件。
  const dataDir = await mkdtemp(join(tmpdir(), 'agaistock-argv-'));
  try {
    const routes = [
      makeRequest('GET', '/api/status'),
      makeRequest('GET', '/api/observations'),
      makeRequest('GET', '/api/observations/obs_1/reviews'),
      makeRequest('POST', '/api/review', { text: '章源钨业看多' }),
      makeRequest('DELETE', '/api/observations/obs_1'),
    ];
    for (const request of routes) {
      await handleRoute(request, new FakeResponse(), {
        kernel,
        dbPath,
        dataDir,
      });
    }
    assert.ok(calls.length >= routes.length, '每条路由都必须真的调内核');
    for (const args of calls) {
      const dbIdx = args.indexOf('--db');
      assert.ok(dbIdx >= 0, `内核调用必须带 --db：${JSON.stringify(args)}`);
      assert.equal(
        args[dbIdx + 1],
        dbPath,
        `--db 必须是宿主给的数据库路径：${JSON.stringify(args)}`,
      );
    }
  } finally {
    await rm(dataDir, { recursive: true, force: true });
  }
});

test('the structured observation draft lands in the host data dir', async () => {
  const calls = [];
  const kernel = async (args) => {
    calls.push(args);
    return { code: 0, stdout: '{"ok":true}', stderr: '' };
  };
  const dataDir = await mkdtemp(join(tmpdir(), 'agaistock-draft-'));
  try {
    const response = new FakeResponse();
    await handleRoute(
      makeRequest('POST', '/api/review', {
        text: '章源钨业看多',
        observation: { symbol: '002378', thesis: 'x' },
      }),
      response,
      { kernel, dbPath: join(dataDir, 'agaistock.db'), dataDir },
    );
    assert.equal(response.statusCode, 200);
    const idx = calls[0].indexOf('--observation-file');
    assert.ok(idx >= 0, '结构化草稿必须经 --observation-file 传给内核');
    const draftPath = calls[0][idx + 1];
    // 草稿的落地目录由 handleRoute 的 draftDir 决定（dataDir || dirname(dbPath)）
    // —— 它是**另一条**落点通道，不受 --db 断言覆盖。
    assert.ok(
      draftPath.startsWith(dataDir),
      `草稿必须落进宿主 dataDir，实际落在 ${draftPath}`,
    );
  } finally {
    await rm(dataDir, { recursive: true, force: true });
  }
});

test('start() gives the host data dir to every kernel call', async () => {
  // 上面那条直接调 handleRoute，**绕过**了 start() 的接线 ——
  // 而 start() → handleRoute 调用点上的 dbPath 是**另一条**通道。
  // 这条走完整路径：start() → 真实 HTTP 请求 → 内核调用。
  const calls = [];
  const { base, root: pluginRoot } = await makeScratchPluginRoot();
  const dataDir = join(base, 'data');
  const context = {
    dataDir,
    pluginRoot,
    listen: { port: 0, host: '127.0.0.1' },
    signal: new AbortController().signal,
  };
  const handle = await start(context, {
    createKernel: (ctx, root, dbPath) => (args) => {
      calls.push(args);
      return Promise.resolve({ code: 0, stdout: '{"items":[]}', stderr: '' });
    },
  });
  try {
    const response = await fetch(`http://127.0.0.1:${handle.port}/api/observations`);
    assert.equal(response.status, 200);
  } finally {
    await handle.dispose();
    await rm(base, { recursive: true, force: true });
  }
  assert.ok(calls.length > 0, '内核必须真的被调用');
  for (const args of calls) {
    const dbIdx = args.indexOf('--db');
    assert.ok(dbIdx >= 0, `内核调用必须带 --db：${JSON.stringify(args)}`);
    assert.equal(
      args[dbIdx + 1],
      join(dataDir, 'agaistock.db'),
      `--db 必须是宿主给的数据库路径：${JSON.stringify(args)}`,
    );
  }
});

test('start() keeps the review draft in the host data dir', async () => {
  // R3（start() → handleRoute 调用点的 dataDir 指回插件目录）的真实危害是
  // **草稿落点**：`/api/review` 的结构化草稿会写进插件目录。
  // 上面的 start() 路径断言抓不到它 —— 那条只断言 `--db`（argv 通道），
  // 而 R3 改的是 dataDir（草稿通道）。两条通道要分别断言。
  const calls = [];
  const { base, root: pluginRoot } = await makeScratchPluginRoot();
  const dataDir = join(base, 'data');
  const context = {
    dataDir,
    pluginRoot,
    listen: { port: 0, host: '127.0.0.1' },
    signal: new AbortController().signal,
  };
  const handle = await start(context, {
    createKernel: (ctx, root, dbPath) => (args) => {
      calls.push(args);
      return Promise.resolve({ code: 0, stdout: '{"ok":true}', stderr: '' });
    },
  });
  try {
    const response = await fetch(`http://127.0.0.1:${handle.port}/api/review`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        text: '章源钨业看多',
        observation: { symbol: '002378', thesis: 'x' },
      }),
    });
    assert.equal(response.status, 200);
  } finally {
    await handle.dispose();
  }
  assert.ok(calls.length > 0, '内核必须真的被调用');
  const idx = calls[0].indexOf('--observation-file');
  assert.ok(idx >= 0, '结构化草稿必须经 --observation-file 传给内核');
  assert.ok(
    calls[0][idx + 1].startsWith(dataDir),
    `草稿必须落进宿主 dataDir，实际落在 ${calls[0][idx + 1]}`,
  );
  assert.ok(
    !existsSync(join(pluginRoot, 'observations.json')),
    '观察卡绝不能落进插件目录',
  );
  await rm(base, { recursive: true, force: true });
});

test('the kernel db path never falls back to the plugin dir', async () => {
  // 两条**默认值 / 回落**通道：
  //  R5 —— `handleRoute` 的 `dbPath` 默认值被改成 PLUGIN_ROOT；
  //  R6 —— `draftDir` 优先取 `dirname(dbPath)` 而不是 `dataDir`。
  // 上面那些测试都**显式传了** dbPath/dataDir ⇒ 把默认值盖掉了 ⇒ 抓不到这两条。
  // 这条**不传** dbPath / dataDir，专门守「没给的时候不许落到插件目录」。
  const calls = [];
  const kernel = async (args) => {
    calls.push(args);
    return { code: 0, stdout: '{"items":[]}', stderr: '' };
  };
  const response = new FakeResponse();
  await handleRoute(makeRequest('GET', '/api/observations'), response, { kernel });
  assert.equal(response.statusCode, 200);
  assert.ok(calls.length > 0, '内核必须被调用');
  const dbIdx = calls[0].indexOf('--db');
  assert.ok(dbIdx >= 0, '内核调用必须带 --db');
  assert.ok(
    !calls[0][dbIdx + 1].includes('agaistock'),
    `没给 dbPath 时不许回落到插件目录，实际 ${calls[0][dbIdx + 1]}`,
  );
});

test('the review draft follows the db path when no data dir is given', async () => {
  // R6 的另一面：`handleRoute` 的 `draftDir = dataDir || dirname(dbPath)`。
  // 宿主**总是**给 dataDir，所以 R6 在生产路径不可达 ——
  // 但「dataDir 为空时草稿该落哪」必须有明确答案，不能由 `dirname(dbPath)` 悄悄决定。
  // 这条断言：dataDir 为空时，草稿必须落在 **dbPath 所在目录**（而不是插件目录）。
  //
  // ⚠️ 关键：**dbPath 必须在 dataDir 之外的另一个目录** ——
  // 否则 `dataDir || dirname(dbPath)` 与 `dirname(dbPath)` 落点相同，
  // R6（把 `||` 去掉）就观测不出来。
  const calls = [];
  const kernel = async (args) => {
    calls.push(args);
    return { code: 0, stdout: '{"ok":true}', stderr: '' };
  };
  const base = await mkdtemp(join(tmpdir(), 'agaistock-nodd-'));
  const dbDir = join(base, 'db');
  const draftDir = join(base, 'draft');
  await mkdir(dbDir, { recursive: true });
  await mkdir(draftDir, { recursive: true });
  try {
    const dbPath = join(dbDir, 'agaistock.db');
    const response = new FakeResponse();
    await handleRoute(
      makeRequest('POST', '/api/review', {
        text: '章源钨业看多',
        observation: { symbol: '002378', thesis: 'x' },
      }),
      response,
      { kernel, dbPath, dataDir: draftDir },
    );
    assert.equal(response.statusCode, 200);
    const idx = calls[0].indexOf('--observation-file');
    assert.ok(idx >= 0, '结构化草稿必须经 --observation-file 传给内核');
    assert.ok(
      calls[0][idx + 1].startsWith(draftDir),
      `草稿必须优先落进 dataDir，实际落在 ${calls[0][idx + 1]}`,
    );
  } finally {
    await rm(base, { recursive: true, force: true });
  }
});
```

> `mkdtemp` / `rm` / `tmpdir` / `existsSync` / `mkdir` **fix round 3 已经 import 了**
> （`import { existsSync, readFileSync } from 'node:fs';`
> `import { cp, mkdir, mkdtemp, rm } from 'node:fs/promises';`
> `import { tmpdir } from 'node:os';`）—— 不用再加 import。
> `makeScratchPluginRoot()` 也已存在，直接用。
> **六条测试各自的通道**（别混淆）：
> | 测试 | 守的通道 | 堵住的变异 |
> |---|---|---|
> | `every kernel call carries the host db path` | 所有路由的 `--db` argv | R7/R8/R9/R10/R11 |
> | `the structured observation draft lands in the host data dir` | 草稿落点（直接调 handleRoute） | R3 |
> | `start() gives the host data dir to every kernel call` | `start()` → 内核的 `--db` argv | R1 |
> | `start() keeps the review draft in the host data dir` | `start()` → 草稿落点 | R3 |
> | `the kernel db path never falls back to the plugin dir` | **不传** dbPath 时的默认值 | R5 |
> | `the review draft follows the db path when no data dir is given` | `draftDir` 的优先级 | R6 |

- [ ] **Step 2: 文档订正（Minor 1 / Minor 2 / Nit 1）**

1. **计划 Task 20 小节**的「来源说明」里那句「其中 18 个还**早于**运行时解包时刻」
   → 改成**不依赖固定数字**的表述：

   ```
   > 实测仓库插件包 `miniapps/agaistock/src/agaistock/**` 的 24 个 `.pyc` 与宿主持久安装目录
   > `~/.minimax/plugins/agaistock/src/agaistock/**` 的 24 个 `.pyc` **mtime 24/24 完全相同**
   > （连亚秒都一致）⇒ 这批 `.pyc` **只能是宿主拷进去的**（`__pycache__` 是 gitignored 产物）。
   > 至于「有多少个早于解包时刻」**随解包批次变化**（实测 19/24 ~ 24/24），
   > **不要**把某个固定数字当证据 —— 决定性的是「mtime 逐个完全相同」这一条。
   ```

2. **同一段**里「仓库插件包、宿主持久安装目录、运行时解包副本**三处都没有 `data/` 目录**」
   → 改成**可复现**的表述（目录在不在取决于当时有没有污染，**不能**当证据）：

   ```
   > **来源说明**：这 8 个 `data/chanlun/002378/*.json` 是**运行时写的** ——
   > 判定依据是**内容与时间**：宿主 `context.dataDir` 下那 8 个 JSON 的 mtime
   > （`2026-11-24T14:34Z` 一带）与仓库根 `data/chanlun/002378/` 下那 8 个
   > （`2026-11-24T11:18Z` 一带）**不同** ⇒ 不是同一批拷过去的。
   > ⚠️ **不要**用「某个目录在不在」当证据 —— 宿主**会连 `data/` 目录一起拷**
   > （实测宿主的安装目录里出现过 `data/agaistock.db`，mtime 与「在包目录直跑内核」
   > 写出的时刻同一秒）。publish 前跑 `python tools/clean-package-artifacts.py` 清理。
   ```

3. **计划 fix round 2 小节**顶部的横幅：把「两处盲区已补」改成
   「**三处**盲区已补（默认内核工厂 / `start()` 局部 `dataDir` / **argv `--db` 通道**）」。

4. **设计文档 §16.4**：那条「构建期直跑内核」的说明里也含「18 个早于解包时刻」，
   一并改成第 1 条的表述（**两处同源，必须一起改**）。

- [ ] **Step 3: 跑全量测试 + 加固后的变异脚本**

```bash
python -m unittest discover -s tests -t .
node --test "miniapps/agaistock/test/*.test.mjs"
node --check miniapps/agaistock/miniapp/node/server.mjs
node tools\check-spec.mjs docs\superpowers\plans\2026-11-24-reviewer-layer-and-chanlun-reviewer.md --external docs\superpowers\specs\2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md --external docs\superpowers\specs\2026-11-24-stock-review-app-architecture.md
```

**封闭性验证（必做）**：

```bash
$env:AGAISTOCK_DATA_DIR='D:\ambient\host\data'; node --test "miniapps/agaistock/test/*.test.mjs"
```

预期**全绿**。

**变异验证（必做）**：控制器会提供 `.tmp\task20-fix4\mutations.py`，
它在本轮脚本基础上**补 9 组变异**（R7/R8/R9/R10/R11/R3/C3/R5/R6），
并把 `E3`/`E4` 的正则锚点改成**语义化**的（评审方指出：排版一变就静默「跳过」，
覆盖率无声下降）。

**预期**：这 9 组对着**修复前**的实现必须**漏过**、对着**修复后**必须**捕获**。

> 控制器已预验证过这个方案（`.tmp\task20-fix4\red_green.py`）：
> **阶段 1（当前实现，无新断言）9 组全漏过**（R7/R8/R9/R10/R11/R3/C3/R5/R6，阴性对照 Z1 也正确报漏过）；
> **阶段 2（加上新断言）0 组真实漏过**（只剩阴性对照 Z1）、**0 假捕获、0 跳过**。
> 预验证过程中控制器修掉了自己脚本的两个真 bug：
> ① `R5` 的正则锚点匹配不到实际排版（静默「跳过」⇒ 覆盖率无声下降）；
> ② 护栏集合没包含新测试名 ⇒ R5 明明红了却被判成「假捕获」。

- [ ] **Step 4: Commit**

```bash
git add miniapps/agaistock/test/api.test.mjs docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md docs/superpowers/plans/2026-11-24-reviewer-layer-and-chanlun-reviewer.md
git commit -m "test: pin the kernel argv channel and make the evidence reproducible" -- miniapps/agaistock/test/api.test.mjs docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md docs/superpowers/plans/2026-11-24-reviewer-layer-and-chanlun-reviewer.md
```

> **不要用 `git add -A`**（Global Constraint 14）。
> 本轮**不改 `src/agaistock/**`、也不改 `server.mjs`**。

---

### Task 20 · fix round 5 — 把断言落到**唯一产生 argv 的地方**（最后一公里）

> **来源**：Task 20 fix round 3/4 的 scoped 复审（verifier）—— fix round 4 是
> **PASS-WITH-MINORS**，0 Critical，但有 **1 条 Important + 2 条 Minor + 3 条 Nit**。
> 控制器已**独立复现**（自己的变异脚本 + 真实跑 Python 内核 + 中性路径对照），
> 结论与评审方一致。

**fix round 4 的那 6 条测试确实落地了** —— 评审方用**自写**脚本独立复现「先红后绿」：
对着修复前 9 组 argv 通道变异**全部漏过**、对着修复后**全部转为捕获**，
端到端探针（只换 `spawn`，真调 `start(context)` **不传 deps**）实测
`cwd`/`PYTHONPATH`/`AGAISTOCK_*`/`--db` **全部指向宿主给的值** ⇒ **实现本身正确，无功能缺陷**。

---

**Important 1（headline）：argv 通道只钉到 `handleRoute` 那一层，最后一公里零护栏。**

fix round 4 的六条断言验的都是**内核回调收到的 args**（`handleRoute` 那一层）；
而 Python 真正解析的 argv 是在 **`runKernel` 里拼出来**的（`server.mjs:166`）——
**那一层没有任何护栏**。

控制器**独立复现**：

```
[D1] runKernel 在 argv 末尾追加一个插件目录的 --db   → exit 0 漏过（67 条全绿）
[E1] runKernel 追加一个**重复**的 --db              → exit 0 漏过
```

并用**真实 Python 内核**证实危害（`argparse` 对重复 `--db` 取**最后一个**）：

```
argv: --db <host>\agaistock.db  --db <plugin>\agaistock.db
→ 宿主目录里有 db = False
→ 插件目录里有 db = True     ← DB 真落进插件目录，而 67 条测试全绿
```

⇒ **env 绿 ≠ argv 绿 ≠ DB 落点对。**

**根因（与 fix round 1/2/3/4 同构，只是又下沉了一层）**：
被观测的对象（`handleRoute` 的 args）≠ 实际生效的对象（进程实际收到的 argv）。

**Minor 1**：新护栏判据 `!value.includes('agaistock')` **依赖仓库目录名恰好含该子串**。
控制器实测：把代码复制到不含该子串的目录（`pkg-neutral-x1y2z`）后，同一变异就漏过。

**Minor 2**：`api.test.mjs` 里查的是 `observations.json`，而草稿文件名是
`observation-*.json`（**单数**）⇒ **该断言恒真**；草稿真写进插件目录仍全绿。

**Nit 1**：控制器那份变异脚本的 argv 通道变异**全部停在 `handleRoute` 层**，
没有一组打真实 argv 拼接点或默认工厂 ⇒ 这正是 Important 1 溜过去的原因。
**Nit 2**：`tools/clean-package-artifacts.py` 的 docstring 里还有**第 5 处**「18 个」活文本没被订正。
**Nit 3**：新测试名与断言方向相反（`never falls back to the plugin dir` 里用的是「不许包含某子串」）。

---

**修法：把断言落到 `runKernel` 的 `spawnFn` 边界 —— 那里抓到的 argv 就是进程实际收到的参数。**

这是**终态**：`runKernel` 是**唯一**产生 argv 的地方，
任何上游层（`handleRoute`、默认内核工厂、`runKernel` 自身）的动手脚都躲不掉。

- 新增一条测试：用 fake `spawnFn` 调 `runKernel`，断言 **argv 里所有 `--db` 的取值
  恰好等于宿主给的 dbPath**（**收集全部** `--db`，不能只看第一个 —— `argparse` 取最后一个）。
- 修 Minor 1：把「不许包含某子串」改成「**恰好等于插件根目录**才算回落」—— 与目录名无关。
- 修 Minor 2：查**所有** `observation-*.json`（单数）草稿文件，而不是 `observations.json`。
- 修 Nit 2：`tools/clean-package-artifacts.py` docstring 里第 5 处「18 个」。

**Files:**
- Modify: `miniapps/agaistock/test/api.test.mjs`
- Modify: `tools/clean-package-artifacts.py`
- Modify: `docs/superpowers/plans/2026-11-24-reviewer-layer-and-chanlun-reviewer.md`
- Modify: `docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md`

> ⚠️ **本轮不改 `server.mjs`** —— 评审方确认实现本身**正确**
> （端到端探针实测未改动实现上所有路径参数都对）。这一轮是**把护栏钉到终态**。

**Interfaces:**
- Consumes: 无（只加测试 + 修判据 + 文档）
- Produces: 无（对外契约不变）

- [ ] **Step 1: 加一条测试 + 修两处判据（`api.test.mjs`）**

**1a) 顶部 import 补 `readdirSync`**：

```javascript
import { existsSync, readFileSync, readdirSync } from 'node:fs';
```

**1b) 修 Minor 1 的判据**（`the kernel db path never falls back to the plugin dir`）：

```javascript
  // ⚠️ 不能用 `!value.includes('agaistock')` —— 那依赖**仓库目录名恰好含该子串**，
  // 换个路径名（安装副本、CI 的临时目录）这条就形同虚设。
  // 判据是「**恰好等于插件根目录**才算回落」—— 与目录名无关。
  assert.notEqual(
    calls[0][dbIdx + 1],
    join(import.meta.dirname, '..'),
    `没给 dbPath 时不许回落到插件目录，实际 ${calls[0][dbIdx + 1]}`,
  );
```

> `join(import.meta.dirname, '..')` = `miniapps/agaistock` = 插件根
> （测试文件在 `miniapps/agaistock/test/`，`server.mjs` 的模块常量 `PLUGIN_ROOT`
> 也是这个值 —— 但 `PLUGIN_ROOT` **不是** export，测试文件拿不到，所以用相对路径算）。

**1c) 修 Minor 2 的恒真断言**（`start() keeps the review draft in the host data dir`）：

```javascript
  // ⚠️ 不能只查 `observations.json` —— 草稿文件名是 `observation-*.json`（**单数**），
  // 查复数那个文件**恒真**，草稿真落进插件目录也照样绿。
  // 这里查**所有** observation 草稿文件（单数）。
  const stray = readdirSync(pluginRoot).filter((name) => /^observation-.*\.json$/.test(name));
  assert.deepEqual(stray, [], `草稿绝不能落进插件目录，实际有 ${JSON.stringify(stray)}`);
```

> 替换掉原来的 `assert.ok(!existsSync(join(pluginRoot, 'observations.json')), ...)`。

**1d) 追加一条「最后一公里」测试**（文件末尾）：

```javascript
// ---- argv 通道的最后一公里（fix round 5）----
// 上一轮的六条断言的是**内核回调收到的 args**（handleRoute 那一层），
// 而 Python 真正解析的 argv 是在 `runKernel` 里拼出来的 —— 那一层零护栏：
// 在 runKernel 的 argv 末尾追加一个插件目录的 --db，67 条测试照样全绿，
// 而 **argparse 对重复的 --db 取最后一个** ⇒ DB 真落进插件目录。
//
// 这里把断言落在**唯一产生 argv 的地方**（runKernel 的 spawnFn 边界）——
// 抓到的 argv 就是进程实际收到的参数 ⇒ 任何上游层的动手脚都躲不掉。
test('the kernel subprocess argv carries exactly the host db path', async () => {
  const captured = [];
  const fakeChild = {
    stdout: { on() {} },
    stderr: { on() {} },
    kill() {},
    on(event, handler) {
      if (event === 'close') setImmediate(() => handler(0));
    },
  };
  const hostDb = 'D:\\host\\data\\agaistock.db';
  await runKernel(
    ['list', '--db', hostDb, '--json'],
    { dataDir: 'D:\\host\\data' },
    'D:\\pkg',
    (command, argv, options) => {
      captured.push({ command, argv, env: options.env });
      return fakeChild;
    },
  );
  assert.equal(captured.length, 1);
  // 收集 argv 里**所有** --db 的取值 —— 不能只看第一个：
  // argparse 对重复的 --db 取**最后一个**，只看第一个会被绕过。
  const dbValues = [];
  captured[0].argv.forEach((value, index) => {
    if (captured[0].argv[index - 1] === '--db') dbValues.push(value);
  });
  assert.deepEqual(
    dbValues,
    [hostDb],
    `argv 里必须只有一个 --db 且是宿主给的路径，实际 ${JSON.stringify(dbValues)}`,
  );
  assert.equal(captured[0].env.AGAISTOCK_DB, hostDb);
  assert.equal(captured[0].env.AGAISTOCK_DATA_DIR, 'D:\\host\\data');
});
```

> `runKernel` / `fakeChild` 的用法与已有的
> `the kernel subprocess actually receives the host data dir` 一致，**不用**再加 import。

- [ ] **Step 2: 修 `tools/clean-package-artifacts.py` 的第 5 处「18 个」**（Nit 2）

docstring 里那句「（实测 `.pyc` mtime 24/24 相同、18 个早于解包时刻）」→ 改成：

```
而**宿主会把 gitignored 产物一并拷进安装目录**（实测仓库插件包
`miniapps/agaistock/src/agaistock/**` 与宿主持久安装目录
`~/.minimax/plugins/agaistock/src/agaistock/**` 的同名 24 个 `.pyc` **mtime 24/24 完全相同**；
至于「有多少个早于解包时刻」**随解包批次变化**，**不要**把某个固定数字当证据）。
```

- [ ] **Step 3: 文档订正**

1. **计划 fix round 2 小节**顶部的横幅：从「**三处**盲区已补」改成
   「**四处**盲区已补（默认内核工厂 / `start()` 局部 `dataDir` / argv `--db` 通道 /
   **argv 拼接点（最后一公里）**）」，并加一句「**别照着本小节 Step 2e 的默认实现写法实现**」
   （已有）＋「**断言要落在 `runKernel` 的 `spawnFn` 边界**」。
2. **设计文档 §16.4**：那条「三层行为护栏」改成「**四层**行为护栏」并列出：
   env 纯函数 / 真实 spawn 路径 / `start()` 注入点 / 默认内核工厂 /
   **argv 拼接点（`runKernel` 的 `spawnFn` 边界）**。
   同时把「**能挡住本仓库内已被护栏覆盖到的改动**」的措辞保持**诚实**
   （未覆盖的路径仍无护栏）。

- [ ] **Step 4: 跑全量测试 + 加固后的变异脚本**

```bash
python -m unittest discover -s tests -t .
node --test "miniapps/agaistock/test/*.test.mjs"
node --check miniapps/agaistock/miniapp/node/server.mjs
node tools\check-spec.mjs docs\superpowers\plans\2026-11-24-reviewer-layer-and-chanlun-reviewer.md --external docs\superpowers\specs\2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md --external docs\superpowers\specs\2026-11-24-stock-review-app-architecture.md
```

**封闭性验证（必做）**：

```bash
$env:AGAISTOCK_DATA_DIR='D:\ambient\host\data'; node --test "miniapps/agaistock/test/*.test.mjs"
```

预期**全绿**。

**中性路径验证（必做 —— 这是 Minor 1 的直接反例）**：
把 `miniapps/agaistock/` 复制到一个**不含 `agaistock` 子串**的目录（如
`%TEMP%\pkg-neutral-x1y2z`），在那份副本里跑测试 —— 必须**仍然全绿**
（修完后判据与目录名无关；修前那份副本上 R5 变异会漏过）。

**变异验证（必做）**：控制器会提供 `.tmp\task20-fix5\mutations.py`，
它在上一轮基础上**补 3 组「最后一公里」变异**：

- **D1**：`runKernel` 在 argv 末尾追加一个插件目录的 `--db`；
- **E1**：`runKernel` 追加一个**重复**的 `--db`（`argparse` last-wins）；
- **D3**：默认内核工厂在 args 里塞一个插件目录的 `--db`。

**预期**：这 3 组对着**修复前**的实现必须**漏过**、对着**修复后**必须**捕获**。

> 控制器已预验证过这个方案（`.tmp\task20-fix5\preverify.py`）：
> **阶段 1（当前实现，无新断言）D1/E1 漏过；阶段 2（加上新断言）5 组全部捕获、0 漏过。**
> 预验证过程中控制器修掉了自己脚本的**两个真 bug**：
> ① Minor 1 的判据第一版写成 `!value.endsWith('agaistock.db') || ...` ——
> R5 的默认值是插件**根目录**（不是 `.../agaistock.db`）⇒ 那个判据**恒真**；
> ② R5/F2 的变异锚点匹配不到实际排版（静默「跳过」⇒ 覆盖率无声下降）。

- [ ] **Step 5: Commit**

```bash
git add miniapps/agaistock/test/api.test.mjs tools/clean-package-artifacts.py docs/superpowers/plans/2026-11-24-reviewer-layer-and-chanlun-reviewer.md docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md
git commit -m "test: pin the kernel argv seam and make the fallback guard path-independent" -- miniapps/agaistock/test/api.test.mjs tools/clean-package-artifacts.py docs/superpowers/plans/2026-11-24-reviewer-layer-and-chanlun-reviewer.md docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md
```

> **不要用 `git add -A`**（Global Constraint 14）。
> 本轮**不改 `server.mjs`、不改 `src/agaistock/**`**。

---

### Task 20 · fix round 6 — 把 argv 断言补到**默认内核工厂**那条路径（终态）

> **来源**：Task 20 fix round 5 的 scoped 复审（verifier）—— **FAIL**（范围仅限 fix round 5；
> 实现本身无功能缺陷）。0 Critical，但有 **1 条 Important + 2 条 Minor + 6 条 Nit**。
> 控制器已**独立复现全部**（自己的变异脚本 + 中性路径对照），结论与评审方一致。

**fix round 5 做对了一件重要事**：`runKernel` 层的 argv 通道真的被钉住了
（评审方独立复现「先红后绿」：修复前 7 组全漏过 → 修复后全捕获）。
但**计划自己的验收标准未达成**，且 round-4 那条 Important **没闭合**。

---

**Important 1（headline）：默认内核工厂（`server.mjs:512-513`）这一层仍然零护栏。**

fix round 5 新增的 `the kernel subprocess argv carries exactly the host db path`
**直接调 `runKernel` 并写死 args** ⇒ 它**从不经过默认工厂** ⇒
「工厂往 args 塞 / 改写 `--db`」这类变异 **68/68 全绿**。

控制器**独立复现**（3 组全漏过）：

| # | 变异 | 结果 |
|---|---|---|
| F1 | 默认工厂往 args **末尾**塞一个插件目录的 `--db` | **exit 0 漏过** |
| F2 | 默认工厂把 args 里的 `--db` **值**改成插件目录 | **exit 0 漏过** |
| F3 | 默认工厂把 args 里的 `--db` 换成**空串** | **exit 0 漏过** |

评审方用**真实 Python 内核 + `start(context)` 不传 deps** 实测：
**DB 真落进插件包目录**、宿主 dataDir 里没有库 —— 危害与 round-4 的 Important 完全相同。

**根因**：修法选错了**位置**。fix round 5 把断言加在「直接调 `runKernel`」的测试里，
而**默认工厂那条测试（`the default kernel factory hands the host context to the kernel unchanged`）
本来就已经抓到了 `captured[0].argv`** —— 只差一行 `--db` 断言。

> **盲区家族（第五次）**：fix round 1 锚在「调用点**字面量**」→ round 2 锚在「调用点**入参**」→
> round 3 锚在「**默认实现**」→ round 4 锚在「`handleRoute` 层的 **args**」→
> round 5 锚在「`runKernel` 直调的 **argv**」—— 每次都差一层。
> **本轮把断言补在「默认工厂 → spawnFn」这条路径上**：
> 它是**生产路径**（宿主不传 `deps` 时走的就是它），
> 且 `handleRoute` / 默认工厂 / `runKernel` 三层的 argv **都在 spawnFn 边界汇聚** ⇒ 一次补全，三层同堵。

**Minor 1 —— fix round 5 把 Minor 1 的判据改窄了（覆盖回退）**：
新判据只排除「**恰好等于插件根**」，而插件根**下面**的 `agaistock.db`
（内核真正会写的那个文件）从「修复前被抓」变成「修复后漏过」。
控制器实测：H8（`dbPath` 默认值 = 插件根下面的 `agaistock.db`）→ **exit 0 漏过**。

**Minor 2 —— 控制器 D3 变异的参数位置写错**：
把数组塞进了 `context` 位 ⇒ `spawnFn` 变成字符串 ⇒ `TypeError` ⇒
**500 !== 200 的崩溃型假捕获**（argv 里根本没有 `--db`）。
控制器已复核：D3-BAD 捕获但红的原因不是护栏；D3-GOOD（数组放 args 位）→ **漏过**。

**Minor 3 —— 草稿守卫只观测宿主给的 pluginRoot**：
写进**模块常量 `PLUGIN_ROOT`**（生产里就是安装目录）—— 控制器实测 **exit 1 被捕获**，
⇒ **这条不成立**，无需修。

**Nit**：① 设计文档「四层」却列 5 项（计划里同样写错）；② argv 前缀 `-S` / `-m agaistock.cli` /
解释器零护栏；③ 计划与新测试注释里「任何上游层都躲不掉」被证伪；④ 控制器 D1/E1 是同一处变异；
⑤ `draftDir` 回落分支仍无人守；⑥ 测试名与断言方向相反那条未改。

---

**修法（很小）：把 argv 的 `--db` 断言补到**默认内核工厂**那条测试里 —— 那里已经抓到 argv。**

- 在 `the default kernel factory hands the host context to the kernel unchanged` 末尾补：
  收集 argv 里**所有** `--db` 的取值（`argparse` 取最后一个，只看第一个会被绕过），
  断言它们**恰好等于**宿主给的 `join(dataDir, 'agaistock.db')`。
- 修 Minor 1：判据改成同时排除「恰好等于插件根」**和**「插件根下面的文件」。
- 修控制器的 D3 变异写法（把数组放 args 位，不是 context 位）。
- 文档：把「四层」改成**准确的层数**，并把「任何上游层都躲不掉」这句**改掉**（它被证伪了）。

**Files:**
- Modify: `miniapps/agaistock/test/api.test.mjs`
- Modify: `docs/superpowers/plans/2026-11-24-reviewer-layer-and-chanlun-reviewer.md`
- Modify: `docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md`

> ⚠️ **本轮不改 `server.mjs`** —— 实现本身**正确**
> （评审方实测未改动实现上所有路径参数都对；本轮唯一的问题是护栏**位置**选错）。

**Interfaces:**
- Consumes: 无（只加断言 + 修判据 + 文档）
- Produces: 无（对外契约不变）

- [ ] **Step 1: 补断言 + 修判据（`api.test.mjs`）**

**1a) 顶部 import 补 `sep`**：

```javascript
import { join, sep } from 'node:path';
```

**1b) 在**默认内核工厂**那条测试末尾补 argv 断言**：

```javascript
  assert.ok(captured.length > 0, '生产路径必须真的 spawn 了内核');
  assert.equal(captured[0].env.AGAISTOCK_DATA_DIR, dataDir);
  assert.equal(captured[0].env.AGAISTOCK_DB, join(dataDir, 'agaistock.db'));
  assert.equal(captured[0].env.PYTHONPATH, join(pluginRoot, 'src'));
  assert.equal(captured[0].cwd, pluginRoot);
  // ⚠️ **argv 也要断言** —— Python 侧 `_default_db()` 是 **argv 优先于 env**
  //（src/agaistock/cli.py:26-32）⇒ env 对了不代表 DB 落点对。
  // 这里是**默认内核工厂**这条路径（宿主不传 deps 时走的就是它），
  // 所以工厂往 args 里塞/改写 `--db` 也必须被抓到。
  // 收集 argv 里**所有** --db 的取值（argparse 取最后一个，只看第一个会被绕过）。
  const dbValues = [];
  captured[0].argv.forEach((value, index) => {
    if (captured[0].argv[index - 1] === '--db') dbValues.push(value);
  });
  assert.deepEqual(
    dbValues,
    [join(dataDir, 'agaistock.db')],
    `默认内核工厂递给内核的 --db 必须是宿主给的路径，实际 ${JSON.stringify(dbValues)}`,
  );
});
```

> **为什么这条是终态**：`handleRoute` 的 args → 默认工厂 → `runKernel` → **spawnFn**，
> 三层的 argv **都在 spawnFn 边界汇聚** ⇒ 在这里断言 argv，一次堵住三层。

**1c) 修 Minor 1 的判据**（`the kernel db path never falls back to the plugin dir`）：

```javascript
  // ⚠️ 不能只排除「恰好等于插件根」—— 插件根**下面**的 agaistock.db 也要排除
  // （那才是内核真正会写的那个文件）。
  // 也不能用 `!value.includes('agaistock')` —— 那依赖**仓库目录名恰好含该子串**。
  const pluginRoot = join(import.meta.dirname, '..');
  const value = calls[0][dbIdx + 1];
  assert.ok(
    value !== pluginRoot && !value.startsWith(pluginRoot + sep),
    `没给 dbPath 时不许回落到插件目录，实际 ${value}`,
  );
```

- [ ] **Step 2: 文档订正**

1. **设计文档 §16.4**：那条护栏清单 —— 把「**四层**行为护栏」改成**准确的层数**，
   并把「**任何上游层（`handleRoute`、默认内核工厂、`runKernel` 自身）的动手脚都躲不掉**」
   这句**改掉**（它被 F1/F2/F3 证伪了）。准确表述：
   「护栏落在 **`spawnFn` 边界**（内核子进程实际收到的 env 与 argv）——
   `handleRoute` / 默认内核工厂 / `runKernel` 三层的路径参数**都在这里汇聚**；
   但**再往下的层**（解释器路径、argv 前缀）尚无护栏」。
2. **计划 fix round 2 小节**顶部横幅的「**四处**盲区已补」→ 改成「**五处**」，
   并把「**断言要落在 `runKernel` 的 `spawnFn` 边界**」改成
   「**断言要落在默认内核工厂 → `spawnFn` 这条路径上**（生产路径，且三层 argv 在此汇聚）」。
3. **计划 fix round 5 小节**：加一句「本小节**已被 fix round 6 补充** ——
   新测试**直接调 `runKernel`、绕过了默认工厂** ⇒ 工厂层零护栏；
   fix round 6 把 argv 断言补到**默认工厂那条路径**上」。

- [ ] **Step 3: 跑全量测试 + 加固后的变异脚本**

```bash
python -m unittest discover -s tests -t .
node --test "miniapps/agaistock/test/*.test.mjs"
node --check miniapps/agaistock/miniapp/node/server.mjs
node tools\check-spec.mjs docs\superpowers\plans\2026-11-24-reviewer-layer-and-chanlun-reviewer.md --external docs\superpowers\specs\2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md --external docs\superpowers\specs\2026-11-24-stock-review-app-architecture.md
```

**封闭性验证（必做）**：

```bash
$env:AGAISTOCK_DATA_DIR='D:\ambient\host\data'; node --test "miniapps/agaistock/test/*.test.mjs"
```

**中性路径验证（必做）**：复制到**不含 `agaistock` 子串**的目录 → 必须**仍然全绿**，
且「dbPath 默认值 = 插件根下面的 `agaistock.db`」必须**被抓到**。

**变异验证（必做）**：控制器会提供 `.tmp\task20-fix6\mutations.py`，
它**修正了 D3 的参数位置**（数组放 args 位，不是 context 位），
并新增 F1/F2/F3 三组「默认工厂层」变异。

**预期**：这 4 组对着**修复前**的实现必须**漏过**、对着**修复后**必须**捕获**。

> 控制器已预验证过这个方案（`.tmp\task20-fix6\preverify.py`）：
> **阶段 1（当前实现）F1/F2/F3/H8 漏过；阶段 2（加上新断言）6 组全部捕获、0 漏过。**

- [ ] **Step 4: Commit**

```bash
git add miniapps/agaistock/test/api.test.mjs docs/superpowers/plans/2026-11-24-reviewer-layer-and-chanlun-reviewer.md docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md
git commit -m "test: assert the kernel argv on the default factory path" -- miniapps/agaistock/test/api.test.mjs docs/superpowers/plans/2026-11-24-reviewer-layer-and-chanlun-reviewer.md docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md
```

> **不要用 `git add -A`**（Global Constraint 14）。
> 本轮**不改 `server.mjs`、不改 `src/agaistock/**`**。

---

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
