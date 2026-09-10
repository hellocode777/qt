"""IndustryHeatService — 行业资金流热度聚合.

把个股资金流(主力净流入 / 涨跌幅)按行业聚合，产出行业热度榜。

注: 底层 parquet 里的 ``turnover`` 列语义未核实(2026-08-14 截面中位数 157、
最高 4546，明显不是百分数换手率)，因此**不参与聚合与展示**(宁缺勿误导)。

数据源: ``data/dataset/capital_flow_latest.parquet``(polars，全市场逐日)。
行业映射: ``qp.portfolio.industry.IndustryMapper``(sector / subsector)。

用法:
    svc = IndustryHeatService()
    result = svc.compute(as_of=date(2026, 9, 10), window=1)
    print(result["industries"][:5])

设计约束:
    - 只用真实数据:数据日期会如实写进结果(result["as_of"] / “data_date”)，缺数据时行业不进榜。
    - 名称覆盖不足的行业归入 "Other"，单独列出且默认不计入排行榜。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any

import polars as pl
from loguru import logger

from qp.data.industry.csrc import CsrcIndustryMapper
from qp.portfolio.industry import IndustryMapper
from qp.shared.json_io import json_save
from qp.shared.paths import DAILY_PRICE_LATEST, DATASET_DIR, INDUSTRY_HEAT_DIR

# 资金流 parquet 的文件名（DATASET_DIR 下的固定产物）
CAPITAL_FLOW_PARQUET = "capital_flow_latest.parquet"

# 主力净流入的单位换算: 元 → 亿元
_YI = 1e8


@dataclass
class IndustryRow:
    """单个行业的热度读数（全部为真实聚合值）。"""

    industry: str
    members: int
    main_net_flow_yi: float  # 主力净流入合计(亿元)
    main_net_flow_pct: float  # 主力净流入净占比均值(%)
    change_pct: float  # 涨跌幅均值(%)
    super_large_net_yi: float = 0.0  # 超大单净额合计(亿元)
    large_net_yi: float = 0.0  # 大单净额合计(亿元)
    amount_yi: float = 0.0  # 成交额合计(亿元) — 行情口径
    up_ratio: float = 0.0  # 上涨家数占比(%) — 行情口径


@dataclass
class HeatResult:
    """一次热度快照。"""

    as_of: str  # 计算基准日(数据实际最新日)
    requested_as_of: str  # 请求的日期
    window: int  # 累计窗口(交易日数)
    granularity: str  # sector / subsector
    data_date_min: str
    data_date_max: str
    industries: list[IndustryRow] = field(default_factory=list)
    other_members: int = 0  # 归入 Other 的股票数
    source: str = "capital_flow"  # capital_flow | price

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["industries"] = [asdict(r) for r in self.industries]
        return d


class IndustryHeatService:
    """按行业聚合资金流热度。

    Args:
        granularity: ``"subsector"``(默认，更细) 或 ``"sector"``。
        mapper: 可注入的行业映射器(便于测试)。
    """

    def __init__(
        self,
        granularity: str = "csrc",
        mapper: IndustryMapper | None = None,
        csrc_mapper: CsrcIndustryMapper | None = None,
    ) -> None:
        """Args:
        granularity: ``csrc``(默认，证监会行业，84 类，覆盖 ~94%) /
            ``sector`` / ``subsector``(名称关键词分类，覆盖较差)。
        mapper: 名称关键词映射器(测试可注入)。
        csrc_mapper: 证监会行业映射器(测试可注入)。
        """
        if granularity not in ("csrc", "sector", "subsector"):
            raise ValueError(f"Unknown granularity: {granularity!r}")
        self._granularity = granularity
        self._mapper = mapper or IndustryMapper()
        self._csrc = csrc_mapper or (CsrcIndustryMapper() if granularity == "csrc" else None)

    # ------------------------------------------------------------------
    # 数据加载
    # ------------------------------------------------------------------

    def load_capital_flow(self, start: date, end: date) -> pl.DataFrame:
        """读取资金流 parquet 并按 [start, end] 过滤。

        Returns:
            DataFrame(date, symbol, close, change_pct,
            main_net_flow, main_net_flow_pct, super_large_net, large_net, ...)
        """
        path = DATASET_DIR / CAPITAL_FLOW_PARQUET
        if not path.exists():
            logger.warning("资金流数据集不存在: {}", path)
            return pl.DataFrame()

        df = pl.read_parquet(str(path))
        # date 列是字符串(YYYY-MM-DD) — 字符串比较即日期比较
        df = df.filter((pl.col("date") >= start.isoformat()) & (pl.col("date") <= end.isoformat()))
        return df

    def _industry_of(self, symbol: str) -> str:
        if self._granularity == "csrc":
            assert self._csrc is not None
            return self._csrc.get(symbol)
        if self._granularity == "sector":
            return self._mapper.get_sector(symbol)
        return self._mapper.get_sector_group(symbol)

    def _attach_industry(self, df: pl.DataFrame) -> pl.DataFrame:
        """给每行打上行业标签(未分类 → Other)。"""
        symbols = df["symbol"].unique().to_list()
        mapping = {str(s): self._industry_of(str(s)) for s in symbols}
        return df.with_columns(
            pl.col("symbol")
            .cast(pl.Utf8)
            .replace_strict(mapping, default="Other")
            .alias("industry")
        )

    # ------------------------------------------------------------------
    # 聚合
    # ------------------------------------------------------------------

    def compute(
        self,
        as_of: date | None = None,
        window: int = 1,
        min_members: int = 3,
        include_other: bool = False,
    ) -> HeatResult:
        """计算行业热度。

        Args:
            as_of: 基准日(默认: 数据里最新的日期)。
            window: 累计窗口(交易日数),1 = 当日。
            min_members: 行业最少成员数(样本太小的行业不进榜)。
            include_other: 是否把 "Other" 放进排行榜(默认否)。

        Returns:
            HeatResult(含真实 as_of —— 实际用到的数据最新日)。
        """
        df_all = self.load_capital_flow(date(2000, 1, 1), as_of or date(2100, 1, 1))
        if df_all.is_empty():
            return HeatResult(
                as_of="N/A",
                requested_as_of=(as_of or date.today()).isoformat(),
                window=window,
                granularity=self._granularity,
                data_date_min="N/A",
                data_date_max="N/A",
            )

        data_min = str(df_all["date"].min())
        data_max = str(df_all["date"].max())

        # 基准日: 请求日期超出数据范围时，退到数据最新日(并如实记录)
        effective_as_of = as_of.isoformat() if as_of else data_max
        if effective_as_of > data_max:
            effective_as_of = data_max

        # 窗口切片(用交易日: 直接取 date <= effective 的最后 window 个日期)
        days = (
            df_all.filter(pl.col("date") <= effective_as_of)
            .select("date")
            .unique()
            .sort("date", descending=True)
            .head(window)["date"]
            .to_list()
        )
        if not days:
            days = [effective_as_of]

        df = df_all.filter(pl.col("date").is_in(days))

        # 数据清洗: 剔除无效行情行(停牌/无成交 → close<=0)
        df = df.filter(pl.col("close") > 0)
        if df.is_empty():
            logger.warning("窗口 {} 清洗后无有效行", days)
            return HeatResult(
                as_of=effective_as_of,
                requested_as_of=(as_of or date.today()).isoformat(),
                window=window,
                granularity=self._granularity,
                data_date_min=data_min,
                data_date_max=data_max,
            )

        df = self._attach_industry(df)

        # 每只股票在窗口内累计(主力净流入/超大单/大单求和，比率/涨幅取均值)
        per_stock = df.group_by(["symbol", "industry"]).agg(
            [
                pl.col("main_net_flow").sum().alias("main_net_flow"),
                pl.col("main_net_flow_pct").mean().alias("main_net_flow_pct"),
                pl.col("super_large_net").sum().alias("super_large_net"),
                pl.col("large_net").sum().alias("large_net"),
                pl.col("change_pct").mean().alias("change_pct"),
            ]
        )

        agg = (
            per_stock.group_by("industry")
            .agg(
                [
                    pl.len().alias("members"),
                    pl.col("main_net_flow").sum().alias("main_net_flow"),
                    pl.col("main_net_flow_pct").mean().alias("main_net_flow_pct"),
                    pl.col("super_large_net").sum().alias("super_large_net"),
                    pl.col("large_net").sum().alias("large_net"),
                    pl.col("change_pct").mean().alias("change_pct"),
                ]
            )
            .filter(pl.col("members") >= min_members)
            .sort("main_net_flow", descending=True)
        )

        rows: list[IndustryRow] = []
        other_members = 0
        for r in agg.iter_rows(named=True):
            if r["industry"] == "Other":
                other_members = int(r["members"])
                if not include_other:
                    continue
            rows.append(
                IndustryRow(
                    industry=str(r["industry"]),
                    members=int(r["members"]),
                    main_net_flow_yi=round(float(r["main_net_flow"]) / _YI, 2),
                    main_net_flow_pct=round(float(r["main_net_flow_pct"]), 3),
                    change_pct=round(float(r["change_pct"]) * 100, 2),
                    super_large_net_yi=round(float(r["super_large_net"]) / _YI, 2),
                    large_net_yi=round(float(r["large_net"]) / _YI, 2),
                )
            )

        return HeatResult(
            as_of=effective_as_of,
            requested_as_of=(as_of or date.today()).isoformat(),
            window=window,
            granularity=self._granularity,
            data_date_min=data_min,
            data_date_max=data_max,
            industries=rows,
            other_members=other_members,
        )

    # ------------------------------------------------------------------
    # 行情口径(不依赖外部请求)
    # ------------------------------------------------------------------

    def compute_from_price(
        self,
        as_of: date | None = None,
        window: int = 1,
        min_members: int = 3,
        include_other: bool = False,
    ) -> HeatResult:
        """行情口径热度: 行业累计涨跌幅 / 成交额 / 上涨家数占比。

        数据源 ``data/dataset/daily_price_latest.parquet``(本地，无外部请求)。
        window=1 表示当日涨跌幅(用前一交易日收盘算)。

        Args:
            as_of: 基准日(默认: 行情数据最新交易日)。
            window: 累计窗口(交易日数)。
            min_members: 行业最少成员数。
            include_other: 是否把 "Other" 放进排行榜。
        """
        path = DAILY_PRICE_LATEST
        if not path.exists():
            logger.warning("行情数据集不存在: {}", path)
            return HeatResult(
                as_of="N/A",
                requested_as_of=(as_of or date.today()).isoformat(),
                source="price",
                window=window,
                granularity=self._granularity,
                data_date_min="N/A",
                data_date_max="N/A",
            )

        df = pl.read_parquet(
            str(path),
            columns=["symbol", "trade_date", "close", "volume", "is_suspended"],
        )
        data_min = str(df["trade_date"].min())
        data_max = str(df["trade_date"].max())

        effective = as_of.isoformat() if as_of else data_max
        if effective > data_max:
            effective = data_max
        eff_d = date.fromisoformat(effective)

        # 交易日序列: 窗口 + 前一日(算收益基准)
        days = (
            df.filter(pl.col("trade_date") <= eff_d)
            .select("trade_date")
            .unique()
            .sort("trade_date", descending=True)
            .head(window + 1)["trade_date"]
            .to_list()
        )
        if not days:
            days = [eff_d]
        win_days = days[:window]
        base_day = days[window] if len(days) > window else None

        keep = list(win_days) + ([base_day] if base_day is not None else [])
        df = df.filter(pl.col("trade_date").is_in(keep))
        # 清洗: 停牌 / 无成交
        df = df.filter((pl.col("close") > 0) & (~pl.col("is_suspended").fill_null(False)))
        if df.is_empty():
            logger.warning("行情窗口 {} 无有效行", keep)
            return HeatResult(
                as_of=effective,
                requested_as_of=(as_of or date.today()).isoformat(),
                source="price",
                window=window,
                granularity=self._granularity,
                data_date_min=data_min,
                data_date_max=data_max,
            )

        df = df.sort(["symbol", "trade_date"]).with_columns(
            pl.col("close").shift(1).over("symbol").alias("prev_close")
        )
        df = df.filter(pl.col("trade_date").is_in(win_days))
        # volume 单位是「手」(已核实: 600519 于 2026-09-09 volume=32226 手，
        # 32226*100*1290.88 ≈ 41.6 亿元，与实际成交额一致) → 乘 100 换成股
        df = df.with_columns(
            (pl.col("close") / pl.col("prev_close") - 1).alias("ret"),
            (pl.col("volume") * 100 * pl.col("close")).alias("amount"),
        )
        df = self._attach_industry(df)

        # 每股: 窗口累计收益 = 窗口末日收盘 / 窗口首日前收 - 1
        per_stock = df.group_by(["symbol", "industry"]).agg(
            [
                (pl.col("close").last() / pl.col("prev_close").first() - 1).alias("ret_w"),
                pl.col("amount").sum().alias("amount"),
                pl.col("ret").last().alias("ret_last"),
            ]
        )

        agg = (
            per_stock.group_by("industry")
            .agg(
                [
                    pl.len().alias("members"),
                    pl.col("ret_w").mean().alias("change_pct"),
                    pl.col("amount").sum().alias("amount"),
                    (pl.col("ret_last") > 0).mean().alias("up_ratio"),
                ]
            )
            .filter(pl.col("members") >= min_members)
            .sort("change_pct", descending=True)
        )

        rows: list[IndustryRow] = []
        other_members = 0
        for r in agg.iter_rows(named=True):
            if r["industry"] == "Other":
                other_members = int(r["members"])
                if not include_other:
                    continue
            rows.append(
                IndustryRow(
                    industry=str(r["industry"]),
                    members=int(r["members"]),
                    main_net_flow_yi=0.0,
                    main_net_flow_pct=0.0,
                    change_pct=round(float(r["change_pct"]) * 100, 2),
                    amount_yi=round(float(r["amount"]) / _YI, 2),
                    up_ratio=round(float(r["up_ratio"]) * 100, 1),
                )
            )

        return HeatResult(
            as_of=effective,
            requested_as_of=(as_of or date.today()).isoformat(),
            source="price",
            window=window,
            granularity=self._granularity,
            data_date_min=data_min,
            data_date_max=data_max,
            industries=rows,
            other_members=other_members,
        )

    # ------------------------------------------------------------------
    # 落盘
    # ------------------------------------------------------------------

    def save(self, result: HeatResult) -> str:
        """把热度快照写入 data/industry_heat/YYYY-MM-DD[_wN].json。"""
        INDUSTRY_HEAT_DIR.mkdir(parents=True, exist_ok=True)
        suffix = f"_w{result.window}" if result.window != 1 else ""
        if result.source != "capital_flow":
            suffix += f"_{result.source}"
        out = INDUSTRY_HEAT_DIR / f"{result.as_of}{suffix}.json"
        json_save(out, result.to_dict())
        logger.info("行业热度已落盘: {}", out)
        return str(out)


def latest_data_date() -> str:
    """资金流数据集的最新日期(用于提示数据是否新鲜)。"""
    path = DATASET_DIR / CAPITAL_FLOW_PARQUET
    if not path.exists():
        return "N/A"
    try:
        df = pl.read_parquet(str(path), columns=["date"])
        return str(df["date"].max())
    except Exception as e:  # pragma: no cover - 防御性
        logger.warning("读取资金流最新日期失败: {}", e)
        return "N/A"


def default_window_start(window: int, as_of: date) -> date:
    """粗略的窗口起始日(自然日近似，实际切片按交易日)。"""
    return as_of - timedelta(days=window * 2)
