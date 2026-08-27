"""统一 JSON 读写。

替代散落的 ``with open(...) as f: json.dump/load`` 样板（118 处 / 50 文件，
2026-08-27 扫描，见 docs/tracking/qt_backlog_tracker.md C-2）。统一约定：
- 编码 ``utf-8``
- ``indent=2``、``ensure_ascii=False``（中文可读）
- ``default=str``（datetime/Path 等可序列化）
- **自动创建父目录**（原 with open 需要手动 mkdir）

Usage:
    from qp.shared.json_io import json_save, json_load

    json_save("data/xxx.json", {"a": 1})
    data = json_load("data/xxx.json")
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def json_save(
    path: str | Path,
    data: Any,
    *,
    indent: int = 2,
    ensure_ascii: bool = False,
    default: Any = str,
) -> Path:
    """Write ``data`` as JSON to ``path``（utf-8，自动建父目录）。

    所有 kwargs 与原 json.dump 语义一致，可覆盖。
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii, default=default)
    return p


def json_load(path: str | Path) -> Any:
    """Read JSON from ``path``（utf-8）。"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)
