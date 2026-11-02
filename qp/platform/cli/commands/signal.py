"""``qp signal`` —— 只看今天的信号（纯只读）。

与 ``qp decide --force`` 的区别（这是本命令存在的全部理由）：

- **不拉行情数据**：只读本地 ``factor_values_daily.parquet``；
- **不做风控/仓位分配**：不跑 RiskManager、不跑 CapitalAllocator；
- **不生成决策包**：不写 ``data/decisions/``、不更新 index；
- **不产生任何写操作**：全程只读。

计算口径与生产一致：``daily_pipeline`` Step 6 算当日得分走的也是
``multifactor._compute_today_from_parquet``（factor execution plane 快路径）——
按 approved 快照的**冻结权重**做加权求和 + 全截面排名。实测 ~0.1s / 3020 只。

注意：这里输出的是**排名原始信号**，不含后续的行业中性再平衡、追高过滤、
风控剔除与仓位计算。要看最终建议，请走 ``qp decide``（读已有决策包）。
"""

from __future__ import annotations

import polars as pl

from qp.shared.paths import FACTOR_VALUES_DAILY


def _factor_dates() -> list[str]:
    """本地因子库里出现过的交易日（升序）。"""
    path = FACTOR_VALUES_DAILY
    if not path.exists():
        return []
    frame = pl.read_parquet(path, columns=["trade_date"])
    return sorted({str(v)[:10] for v in frame["trade_date"].to_list()})


def cmd_signal(as_of: str = "", top: int = 0) -> int:
    """Print today's ranked signals from local factor parquet. Read-only."""
    from qp.strategy.multifactor import _compute_today_from_parquet
    from qp.strategy.registry import StrategyRegistry

    dates = _factor_dates()
    if not dates:
        print("❌ 本地因子库不存在或为空 / no local factor data")
        print(f"   期望路径 / expected: {FACTOR_VALUES_DAILY}")
        return 1

    latest = dates[-1]
    requested = as_of or latest

    # ── 策略与冻结权重（必须来自 approved 快照，不能用默认值）──
    try:
        snapshots = StrategyRegistry().load_active()
    except Exception as exc:
        print(f"❌ 读取 approved 快照失败 / cannot read approved snapshot: {exc}")
        return 1
    if not snapshots:
        print("❌ 没有 APPROVED 策略，无信号可算 / no APPROVED strategy")
        return 1
    if len(snapshots) > 1:
        names = ", ".join(getattr(s, "strategy_id", "?") for s in snapshots)
        print(f"❌ 存在多个 APPROVED 策略（{names}），请先确定唯一生产策略")
        return 1

    snap = snapshots[0]
    strategy_id = getattr(snap, "strategy_id", "?")
    version = getattr(snap, "version", "?")
    weights = dict(getattr(snap, "weights", {}) or {})
    params = dict(getattr(snap, "parameters", {}) or {})
    top_n = top if top > 0 else int(params.get("top_n", 10) or 10)

    if not weights:
        print(f"❌ 策略 {strategy_id} 的快照没有冻结权重 / snapshot has no frozen weights")
        return 1

    # ── 日期可用性：问的日期没数据就明说，不偷偷换日期 ──
    if requested not in dates:
        print(f"❌ {requested} 不在本地因子库中 / not in local factor data")
        print(f"   最近可用 / latest available: {latest}")
        return 1

    scores = _compute_today_from_parquet(weights, requested)
    if scores.is_empty():
        print(f"❌ {requested} 无评分结果（因子列与权重不匹配？）")
        print(f"   权重 / weights: {weights}")
        return 1

    print("═══ QP 今日信号 / Today's Signals（只读 read-only）═══\n")
    print(f"  策略 / Strategy:  {strategy_id} ({version})")
    print(f"  权重 / Weights:   {', '.join(f'{k}={v}' for k, v in weights.items())}")
    print(f"  请求日期 / As of: {requested}")
    if requested != latest:
        print(f"  ⚠️ 本地最新数据是 {latest}，本次按请求日期 {requested} 计算")
    print(f"  数据来源:         {FACTOR_VALUES_DAILY}")
    print(f"  全截面 / Scored:  {len(scores)} 只")

    ranked = scores.sort("rank").head(top_n)
    print(f"\n  ── Top {top_n} ──")
    for row in ranked.iter_rows(named=True):
        print(f"   {int(row['rank']):>3}  {row['symbol']}   {float(row['raw_score']):+.6f}")

    print("\n  说明 / Note: 仅冻结权重加权评分 + 排名；未拉行情、未做风控/仓位、")
    print("               未生成决策包、未写任何文件。")
    print("               最新建议请用 `qp decide` 读当天决策包。")
    return 0
