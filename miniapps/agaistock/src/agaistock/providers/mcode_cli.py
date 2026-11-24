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

    if isinstance(payload, list) and payload and isinstance(payload[0], dict) and "text" in payload[0]:
        return payload[0]["text"]
    if isinstance(payload, str):
        return payload
    return stdout
