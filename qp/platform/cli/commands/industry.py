"""CLI: qp industry heat — 行业热度榜(行情口径 / 资金流口径)."""

from __future__ import annotations

from datetime import date, datetime

from qp.research.industry_heat import IndustryHeatService


def cmd_industry_heat(
    as_of: str | None = None,
    window: int = 1,
    granularity: str = "csrc",
    top: int = 15,
    save: bool = True,
    source: str = "price",
) -> int:
    """计算 / 打印 / 落盘 行业热度榜。

    Args:
        source: ``price``(行情口径: 涨幅/成交额/上涨占比，本地数据，最新)
            或 ``capital_flow``(资金流口径: 主力净流入)。

    Returns:
        0 成功；1 无数据；2 参数错误。
    """
    if source not in ("price", "capital_flow"):
        print(f"未知口径: {source!r}（可选 price / capital_flow）")
        return 2

    svc = IndustryHeatService(granularity=granularity)
    as_of_date: date | None = None
    if as_of:
        try:
            as_of_date = date.fromisoformat(as_of)
        except ValueError:
            print(f"日期格式错误: {as_of!r}（应为 YYYY-MM-DD）")
            return 2

    if source == "price":
        result = svc.compute_from_price(as_of=as_of_date, window=window)
        label = "行情口径"
    else:
        result = svc.compute(as_of=as_of_date, window=window)
        label = "资金流口径"

    if not result.industries:
        print("无数据: 数据集为空，或该窗口内无有效行情行。")
        print(f"  数据集日期范围: {result.data_date_min} → {result.data_date_max}")
        if source == "capital_flow":
            print("  更新数据: qp capital-flow --incremental")
        return 1

    # ── 数据新鲜度(如实展示) ──
    stale_days = ""
    try:
        gap = (datetime.now().date() - date.fromisoformat(result.as_of)).days
        if gap >= 1:
            stale_days = f"  ⚠️ 数据滞后 {gap} 天"
    except ValueError:
        pass

    print(
        f"行业热度 · {label} · {granularity} · 基准日 {result.as_of}{stale_days}\n"
        f"数据范围 {result.data_date_min} → {result.data_date_max} · 累计窗口 {window} 个交易日"
    )
    print()

    if source == "price":
        print(f"{'行业':<18}{'成员':>6}{'涨幅%':>9}{'成交额(亿)':>14}{'上涨占比%':>11}")
        print("-" * 58)
        for r in result.industries[:top]:
            print(
                f"{r.industry:<18}{r.members:>6}{r.change_pct:>9.2f}"
                f"{r.amount_yi:>14.2f}{r.up_ratio:>11.1f}"
            )
    else:
        print(f"{'行业':<18}{'成员':>6}{'主力净流入(亿)':>16}{'净占比%':>10}{'涨幅%':>9}")
        print("-" * 60)
        for r in result.industries[:top]:
            print(
                f"{r.industry:<18}{r.members:>6}{r.main_net_flow_yi:>16.2f}"
                f"{r.main_net_flow_pct:>10.3f}{r.change_pct:>9.2f}"
            )

    # ── 尾部(榜尾 5) ──
    if len(result.industries) > top:
        print("\n—— 榜尾 5 ——")
        for r in result.industries[-5:]:
            if source == "price":
                print(
                    f"{r.industry:<18}{r.members:>6}{r.change_pct:>9.2f}"
                    f"{r.amount_yi:>14.2f}{r.up_ratio:>11.1f}"
                )
            else:
                print(
                    f"{r.industry:<18}{r.members:>6}{r.main_net_flow_yi:>16.2f}"
                    f"{r.main_net_flow_pct:>10.3f}{r.change_pct:>9.2f}"
                )

    if result.other_members:
        print(
            f"\n注: 另有 {result.other_members} 只股票未归入任何行业(counts as Other)，"
            "行业映射按股票名称关键词生成，覆盖有限。"
        )
    if source == "price":
        print("\n提示: 资金流口径(主力净流入)用 --source capital_flow; 其数据源有严格限流。")

    if save:
        path = svc.save(result)
        print(f"\n已落盘: {path}")

    return 0
