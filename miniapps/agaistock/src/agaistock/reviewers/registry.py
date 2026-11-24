"""点评师注册表：按配置发现并实例化点评师。"""
from __future__ import annotations

import importlib

from .. import config


class _UnavailableReviewer:
    """模块导入失败时的占位点评师。

    占位对象让注册流程保持"逐个隔离"的语义：某个点评师的模块坏了，
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
    其它点评师：该项 `instance` 是占位对象，`error` 记录是谁、哪个模块、
    原始异常是什么。占位对象在 review 时抛错，由引擎转成 status='error'
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
