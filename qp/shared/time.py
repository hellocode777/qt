"""统一时间工具 — 全项目唯一的取时/时区入口。

约定（Rule: Same Input, Same Output — determinism）：
- **存储/审计**：UTC，ISO 8601（``now_utc().isoformat()``）
- **面向用户显示 / 中国交易日语义**：Asia/Shanghai（``now_cn`` / ``today_cn``）
- **禁止裸 ``datetime.now()`` / ``date.today()``**（naive，依赖机器时区）；
  一律从这里取。

Usage:
    from qp.shared.time import now_utc, now_cn, today_cn, display_cn, utc_iso, cn_iso

    ts = now_utc()       # datetime, UTC aware（存储）
    cn = now_cn()        # datetime, Asia/Shanghai aware（中国语义）
    d = today_cn()       # date, 中国日期（交易日/日期键）
    s = display_cn(iso)  # "2026-08-27 18:30:00" 北京显示
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

# 中国标准时区 — 全项目唯一时区常量（替代各模块重复定义的 CN_TZ / BEIJING_TZ）
CN_TZ = ZoneInfo("Asia/Shanghai")

__all__ = [
    "CN_TZ",
    "cn_iso",
    "display_cn",
    "fmt_compact",
    "fmt_date",
    "fmt_display",
    "fmt_display_utc",
    "fmt_sec",
    "fmt_ts",
    "now_cn",
    "now_utc",
    "today_cn",
    "utc_iso",
]


def now_utc() -> datetime:
    """当前时间（UTC, aware）。存储/审计/跨时区比较用。"""
    return datetime.now(UTC)


def now_cn() -> datetime:
    """当前时间（Asia/Shanghai, aware）。中国日历语义/用户显示用。"""
    return datetime.now(CN_TZ)


def today_cn() -> date:
    """中国日期（Asia/Shanghai）。交易日/日期键用。"""
    return now_cn().date()


def utc_iso() -> str:
    """当前 UTC 时间 ISO 8601 字符串（存储格式）。"""
    return now_utc().isoformat()


def cn_iso() -> str:
    """当前北京时间 ISO 8601 字符串。"""
    return now_cn().isoformat()


def display_cn(iso_str: str) -> str:
    """ISO 8601 时间字符串 → 'YYYY-MM-DD HH:MM:SS' 北京时间显示。"""
    return datetime.fromisoformat(iso_str).astimezone(CN_TZ).strftime("%Y-%m-%d %H:%M:%S")


# ── 格式函数（统一 strftime 格式，见 docs/tracking C-3）──────────────
# 约定：dt 省略时默认北京当前时间；日期/时间对象可直接传入。


def fmt_date(dt: datetime | date | None = None) -> str:
    """'YYYY-MM-DD'（日期显示/文件名）。"""
    return (dt or now_cn()).strftime("%Y-%m-%d")


def fmt_compact(dt: datetime | date | None = None) -> str:
    """'YYYYMMDD' 紧凑日期（目录/版本）。"""
    return (dt or now_cn()).strftime("%Y%m%d")


def fmt_ts(dt: datetime | date | None = None, sep: str = "_") -> str:
    """'YYYYMMDD{sep}HHMMSS' 时间戳（文件名）。"""
    return (dt or now_cn()).strftime(f"%Y%m%d{sep}%H%M%S")


def fmt_display(dt: datetime | date | None = None) -> str:
    """'YYYY-MM-DD HH:MM' 分钟级显示。"""
    return (dt or now_cn()).strftime("%Y-%m-%d %H:%M")


def fmt_sec(dt: datetime | date | None = None) -> str:
    """'YYYY-MM-DD HH:MM:SS' 秒级显示。"""
    return (dt or now_cn()).strftime("%Y-%m-%d %H:%M:%S")


def fmt_display_utc(dt: datetime | None = None) -> str:
    """'YYYY-MM-DD HH:MM UTC' UTC 显示。"""
    return (dt or now_utc()).strftime("%Y-%m-%d %H:%M UTC")
