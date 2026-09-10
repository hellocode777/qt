"""CLI: qp industry heat — 行业资金流热度榜."""

from __future__ import annotations

from datetime import date, datetime

from qp.research.industry_heat import IndustryHeatService


def cmd_industry_heat(
    as_of: str | None = None,
    window: int = 1,
    granularity: str = "subsector",
    top: int = 15,
    save: bool = True,
) -> int:
    """计算 / 打印 / 落盘 行业热度榜。

    Returns:
        0 成功；1 无数据。
    """
    svc = IndustryHeatService(granularity=granularity)
    as_of_date: date | None = None
    if as_of:
        try:
            as_of_date = date.fromisoformat(as_of)
        except ValueError:
            print(f"日期格式错误: {as_of!r}（应为 YYYY-MM-DD）")
            return 2

    result = svc.compute(as_of=as_of_date, window=window)

    if not result.industries:
        print("无数据: 资金流数据集为空，或该窗口内无有效行情行。")
        print(f"  数据集日期范围: {result.data_date_min} → {result.data_date_max}")
        print("  更新数据: qp capital-flow")
        return 1

    # ── 表头 + 数据新鲜度(如实展示) ──
    stale_days = ""
    try:
        gap = (datetime.now().date() - date.fromisoformat(result.as_of)).days
        if gap >= 1:
            stale_days = f"  ⚠️ 数据滞后 {gap} 天"
    except ValueError:
        pass

    print(
        f"行业热度 · {granularity} · 基准日 {result.as_of}{stale_days}\n"
        f"数据范围 {result.data_date_min} → {result.data_date_max} · 累计窗口 {window} 个交易日"
    )
    print()
    print(f"{'行业':<18}{'成员':>6}{'主力净流入(亿)':>16}{'净占比%':>10}{'涨幅%':>9}")
    print("-" * 60)
    for r in result.industries[:top]:
        print(
            f"{r.industry:<18}{r.members:>6}{r.main_net_flow_yi:>16.2f}"
            f"{r.main_net_flow_pct:>10.3f}{r.change_pct:>9.2f}"
        )

    # ── 尾部:资金流出最多的行业(避坑用) ──
    if len(result.industries) > top:
        print("\n—— 资金净流出最多(尾部 5) ——")
        for r in result.industries[-5:]:
            print(
                f"{r.industry:<18}{r.members:>6}{r.main_net_flow_yi:>16.2f}"
                f"{r.main_net_flow_pct:>10.3f}{r.change_pct:>9.2f}"
            )

    if result.other_members:
        print(
            f"\n注: 另有 {result.other_members} 只股票未归入任何行业(counts as Other)，"
            "行业映射按股票名称关键词生成，覆盖有限。"
        )

    if save:
        path = svc.save(result)
        print(f"\n已落盘: {path}")

    return 0
