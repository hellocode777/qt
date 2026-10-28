"""调仓节奏（cadence）：把「多久调仓」从硬编码日历判定变成可参数化。

背景（2026-10-28 实测）：`lvr_vol_only` 在 2024-01-01→2026-08-14 上，40 个交易日
调仓的 Sharpe 1.59–1.92（三个相位），显著优于 20 日的 1.26，且换手/成本减半
（1860%→1054%，8.34%→4.63%）。但生产调仓日原先写死在
`daily_pipeline.py`：`is_first_trading_day_of_month`，`approved.rebalance`
是惰性字段 —— 想让生产跑 40 日节奏，必须先把 cadence 变成参数驱动。

两种模式：
  - ``monthly``（默认，保持历史行为）：当月第一个真实交易日（原逻辑，走 akshare 日历）
  - ``trading_days``：每 N 个交易日一次，锚点 = ``rebalance_anchor``（缺省=数据集首个交易日）

``trading_days`` 用的交易日序列取自本地行情 ``daily_price_latest.parquet`` 的
``trade_date``（离线可用、与策略实际用的数据一致），不依赖 akshare 网络。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

MODE_MONTHLY = "monthly"
MODE_TRADING_DAYS = "trading_days"
VALID_MODES: frozenset[str] = frozenset({MODE_MONTHLY, MODE_TRADING_DAYS})


@dataclass(frozen=True)
class CadenceSpec:
    """解析后的调仓节奏。"""

    mode: str
    days: int = 0
    anchor: str | None = None
    source: str = "default"

    def describe(self) -> str:
        if self.mode == MODE_TRADING_DAYS:
            anchor = self.anchor or "dataset_start"
            return f"trading_days={self.days}, anchor={anchor}, source={self.source}"
        return f"monthly(first_trading_day_of_month), source={self.source}"


def resolve_cadence(
    approved_parameters: Mapping[str, Any] | None,
    context_parameters: Mapping[str, Any] | None,
) -> CadenceSpec:
    """解析调仓节奏。

    优先级：approved 快照 → 运行时 context 参数 → 默认 ``monthly``。
    approved 快照优先，是为了让「冻结的生产参数」说话，避免调度器配置漂移
    悄悄改掉策略行为。

    Raises:
        ValueError: 模式未知，或 ``trading_days`` 未给正整数 ``rebalance_days``。
    """
    for source, params in (
        ("approved", approved_parameters or {}),
        ("context", context_parameters or {}),
    ):
        raw_mode = params.get("rebalance_cadence")
        if raw_mode is None or str(raw_mode).strip() == "":
            continue
        mode = str(raw_mode).strip().lower()
        if mode not in VALID_MODES:
            raise ValueError(
                f"未知 rebalance_cadence={mode!r}（来源 {source}），允许值 {sorted(VALID_MODES)}"
            )
        if mode == MODE_MONTHLY:
            return CadenceSpec(mode=mode, source=source)

        try:
            days = int(params.get("rebalance_days", 0) or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"rebalance_days 必须是正整数（来源 {source}）") from exc
        if days <= 0:
            raise ValueError(
                f"rebalance_cadence=trading_days 需要 rebalance_days>0（来源 {source}）"
            )
        anchor_raw = params.get("rebalance_anchor")
        anchor = str(anchor_raw) if anchor_raw else None
        return CadenceSpec(mode=mode, days=days, anchor=anchor, source=source)

    return CadenceSpec(mode=MODE_MONTHLY, source="default")


@lru_cache(maxsize=4)
def _load_trade_dates_cached(path_str: str, mtime_ns: int) -> tuple[str, ...]:
    """读取交易日序列（按 mtime 缓存，数据更新后自动失效）。"""
    import polars as pl

    frame = pl.read_parquet(path_str, columns=["trade_date"])
    dates = sorted({str(v)[:10] for v in frame["trade_date"].to_list()})
    return tuple(dates)


def load_trade_dates(path: str | Path) -> list[str]:
    """从行情 parquet 读排序去重的交易日列表（YYYY-MM-DD 字符串）。"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"交易日序列来源不存在：{p}")
    return list(_load_trade_dates_cached(str(p), p.stat().st_mtime_ns))


def is_trading_days_rebalance(
    today: str,
    spec: CadenceSpec,
    trade_dates: Sequence[str],
) -> tuple[bool, str]:
    """判断 ``today`` 是否落在 N 交易日节奏的调仓日上。

    Returns:
        (是否调仓日, 供日志/元数据留痕的说明字符串)

    判定：以锚点（缺省数据集首个交易日）为 0，交易日序号 ``idx`` 满足
    ``(idx - anchor_idx) % days == 0`` 即为调仓日。纯函数、无状态、可复现。
    """
    if spec.mode != MODE_TRADING_DAYS:
        raise ValueError(f"is_trading_days_rebalance 只处理 trading_days，收到 {spec.mode!r}")
    if not trade_dates:
        return False, "trading_days: 交易日序列为空，不调仓"

    date_list = list(trade_dates)
    if today not in date_list:
        latest = date_list[-1]
        flag = "（today 晚于最新数据，可能数据未更新）" if today > latest else ""
        return False, f"trading_days={spec.days}: {today} 不在交易日序列（最新 {latest}）{flag}"

    index = date_list.index(today)
    if spec.anchor:
        # 锚点不要求本身出现在序列里（可能是未来日期、也可能是节假日）：
        # 用「锚点之后到今天有几个交易日」来算偏移，today 恰好是锚点后的第 1 个
        # 交易日 → offset=0（即调仓日）。anchor == today → offset=0。
        offset = sum(1 for d in date_list if spec.anchor <= d <= today) - 1
        if offset < 0:
            return False, f"trading_days={spec.days}: today 早于锚点 {spec.anchor}"
    else:
        offset = index

    is_rebalance = offset % spec.days == 0
    return is_rebalance, (
        f"trading_days={spec.days} offset={offset} "
        f"anchor={spec.anchor or date_list[0]} "
        f"next_gap={0 if is_rebalance else spec.days - offset % spec.days}"
    )
