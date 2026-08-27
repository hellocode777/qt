"""Risk Exit Manager — 每日风险退出检查（V2.1 Final 规范）.

V2.1 第三章 第二类：Risk Exit（风险退出）
  - 每天收盘后检查，触发后次日开盘执行
  - 与模型预测完全无关

检查项:
  Stop Loss:      持仓亏损 ≥ -10% → 次日开盘卖出
  ST 风险:        股票名称含 ST/PT → 次日开盘卖出
  退市风险:       已知退市列表 → 次日开盘卖出
  黑名单:         人工/规则标记 → 次日开盘卖出
  长期停牌:      连续停牌 > 30 天 → 标记冻结
  流动性风险:     日均成交量过低 → 次日开盘卖出

优先级 (V2.1 §5):
  CRITICAL:  ST、退市
  HIGH:      Stop Loss
  MEDIUM:    流动性风险、长期停牌
  LOW:       Rank Drop、仓位调整

Usage:
    from qp.portfolio.risk_exit import RiskExitManager, Priority, TradeReason

    rm = RiskExitManager(stop_loss_pct=-0.10)
    exits = rm.evaluate_daily(holdings, daily_prices, date_str)
    # → list[RiskExitSignal]
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path

from loguru import logger

from qp.shared.paths import BLACKLIST

# ------------------------------------------------------------------
# Priority & Reason enums (V2.1 §5)
# ------------------------------------------------------------------


class Priority(IntEnum):
    """退出优先级 — 数字越小越高."""

    CRITICAL = 1  # ST、退市
    HIGH = 2  # Stop Loss
    MEDIUM = 3  # 流动性风险、长期停牌
    LOW = 4  # Rank Drop、仓位调整


class TradeReason(str):
    """交易原因标签（V2.1 多重原因共存）."""

    STOP_LOSS = "STOP_LOSS"
    RISK_ST = "RISK_ST"
    RISK_DELIST = "RISK_DELIST"
    RISK_SUSPENSION = "RISK_SUSPENSION"
    RISK_LIQUIDITY = "RISK_LIQUIDITY"
    RISK_BLACKLIST = "RISK_BLACKLIST"
    RANK_DROP = "RANK_DROP"
    FUNDAMENTAL_DETERIORATION = "FUNDAMENTAL_DETERIORATION"
    NEW_ENTRY = "NEW_ENTRY"
    REBALANCE = "REBALANCE"
    SECTOR_OVERWEIGHT = "SECTOR_OVERWEIGHT"


# ------------------------------------------------------------------
# Data models
# ------------------------------------------------------------------


@dataclass
class RiskExitSignal:
    """一条风险退出建议.

    V2.1 §5: 同一天多条原因合并为一条建议，保留多个 reason tag.
    """

    symbol: str
    action: str = "SELL"
    priority: Priority = Priority.HIGH
    reasons: list[str] = field(default_factory=list)
    detail: str = ""
    execution_time: str = "NEXT_OPEN"

    def __repr__(self) -> str:
        reasons_str = ", ".join(self.reasons)
        return f"RiskExit({self.symbol}, {self.action}, {self.priority.name}, [{reasons_str}])"


# ------------------------------------------------------------------
# Default config (V2.1 §7 PMConfig)
# ------------------------------------------------------------------


@dataclass
class RiskExitConfig:
    """Risk Exit 配置."""

    stop_loss_pct: float = -0.10  # 固定止损线
    stop_loss_check: str = "EOD"  # 检查频率
    stop_loss_execute: str = "NEXT_OPEN"  # 执行时间
    force_sell_st: bool = True  # ST 强制卖出
    force_sell_delist: bool = True  # 退市强制卖出
    force_sell_blacklist: bool = True  # 黑名单强制卖出
    max_suspension_days: int = 30  # 长期停牌阈值
    liquidity_min_avg_volume: int = 100_000  # 日均成交量最低阈值 (股)
    liquidity_lookback_days: int = 20  # 流动性回看天数
    blacklist_path: str | Path = BLACKLIST  # 黑名单文件路径


# ------------------------------------------------------------------
# Risk Exit Manager
# ------------------------------------------------------------------


class RiskExitManager:
    """每日风险退出检查引擎.

    V2.1 §3 第二类：每天收盘后运行，次日开盘执行。

    Usage:
        rm = RiskExitManager()
        exits = rm.evaluate_daily(
            holdings={"000001": 1000, "600519": 500},
            prices={"000001": 12.50, "600519": 1800.0},
            cost_basis={"000001": 14.0, "600519": 1750.0},
            date_str="2024-06-30",
        )
        for e in exits:
            print(f"{e.symbol}: {e.reasons}")
    """

    def __init__(self, config: RiskExitConfig | None = None) -> None:
        self.config = config or RiskExitConfig()
        self._known_delisted: set[str] | None = None
        self._blacklist: set[str] | None = None

    # ------------------------------------------------------------------
    # Main entry point — daily evaluation
    # ------------------------------------------------------------------

    def evaluate_daily(
        self,
        holdings: dict[str, int | float],
        prices: dict[str, float],
        cost_basis: dict[str, float],
        date_str: str = "",
        stock_names: dict[str, str] | None = None,
        suspension_days: dict[str, int] | None = None,
        volume_data: dict[str, list[float]] | None = None,
    ) -> list[RiskExitSignal]:
        """每日收盘后评估所有持仓的风险.

        Args:
            holdings: {symbol: shares} — 当前持仓股数.
            prices: {symbol: close_price} — 当日收盘价.
            cost_basis: {symbol: avg_cost} — 持仓成本.
            date_str: 当前日期 (YYYY-MM-DD).
            stock_names: {symbol: name} — 股票名称（ST 检测用）.
            suspension_days: {symbol: consecutive_suspended_days}.
            volume_data: {symbol: [recent_daily_volumes]} — 近期日成交量（流动性检测用）.

        Returns:
            RiskExitSignal 列表，按优先级排序.
        """
        if not holdings:
            return []

        exits: dict[str, RiskExitSignal] = {}
        stock_names = stock_names or {}
        suspension_days = suspension_days or {}

        for symbol, shares in holdings.items():
            if shares <= 0:
                continue

            px = prices.get(symbol)
            if px is None or px <= 0:
                continue

            name = stock_names.get(symbol, "")
            reasons: list[str] = []

            # ── CRITICAL: ST 风险 ──
            if self.config.force_sell_st and self._is_st(name):
                reasons.append(TradeReason.RISK_ST)

            # ── CRITICAL: 退市风险 ──
            if self.config.force_sell_delist and self._is_delisted(symbol):
                reasons.append(TradeReason.RISK_DELIST)

            # ── CRITICAL: 黑名单 ──
            if self.config.force_sell_blacklist and self._is_blacklisted(symbol):
                reasons.append(TradeReason.RISK_BLACKLIST)

            # ── HIGH: Stop Loss ──
            cb = cost_basis.get(symbol, 0.0)
            if cb > 0:
                pnl_pct = (px - cb) / cb
                if pnl_pct <= self.config.stop_loss_pct:
                    reasons.append(TradeReason.STOP_LOSS)

            # ── MEDIUM: 流动性风险 ──
            if volume_data and symbol in volume_data:
                vols = volume_data[symbol]
                if vols:
                    avg_vol = sum(vols) / len(vols)
                    if avg_vol < self.config.liquidity_min_avg_volume:
                        reasons.append(TradeReason.RISK_LIQUIDITY)

            # ── MEDIUM: 长期停牌 ──
            susp = suspension_days.get(symbol, 0)
            if susp > self.config.max_suspension_days:
                reasons.append(TradeReason.RISK_SUSPENSION)

            if reasons:
                priority = self._highest_priority(reasons)
                exits[symbol] = RiskExitSignal(
                    symbol=symbol,
                    action="SELL",
                    priority=priority,
                    reasons=reasons,
                    detail=self._build_detail(symbol, name, px, cb, reasons),
                    execution_time=self.config.stop_loss_execute,
                )

        # Priority sort
        result = sorted(exits.values(), key=lambda e: e.priority.value)

        if result:
            n_crit = sum(1 for e in result if e.priority == Priority.CRITICAL)
            n_high = sum(1 for e in result if e.priority == Priority.HIGH)
            n_med = sum(1 for e in result if e.priority == Priority.MEDIUM)
            parts = []
            if n_crit:
                parts.append(f"CRITICAL={n_crit}")
            if n_high:
                parts.append(f"HIGH={n_high}")
            if n_med:
                parts.append(f"MEDIUM={n_med}")
            logger.info(
                "🛡️ Risk Exit ({}/{}): {} — {}",
                date_str,
                len(holdings),
                ", ".join(parts),
                [f"{e.symbol}({','.join(e.reasons)})" for e in result[:5]],
            )

        return result

    # ------------------------------------------------------------------
    # Standalone checks (exposed for per-check usage)
    # ------------------------------------------------------------------

    def check_stop_loss(
        self,
        holdings: dict[str, float],
        prices: dict[str, float],
        cost_basis: dict[str, float],
    ) -> list[str]:
        """检查止损触发."""
        triggered: list[str] = []
        for symbol in holdings:
            px = prices.get(symbol, 0.0)
            cb = cost_basis.get(symbol, 0.0)
            if px > 0 and cb > 0:
                pnl_pct = (px - cb) / cb
                if pnl_pct <= self.config.stop_loss_pct:
                    triggered.append(symbol)
        return triggered

    def check_st_risk(
        self,
        stock_names: dict[str, str],
        holdings: set[str] | None = None,
    ) -> list[str]:
        """检查 ST 风险."""
        triggered: list[str] = []
        check_set = set(holdings) if holdings else set(stock_names.keys())
        for symbol in check_set:
            if self._is_st(stock_names.get(symbol, "")):
                triggered.append(symbol)
        return triggered

    def check_delisting_risk(self, holdings: set[str]) -> list[str]:
        """检查退市风险."""
        triggered: list[str] = []
        for symbol in holdings:
            if self._is_delisted(symbol):
                triggered.append(symbol)
        return triggered

    def check_suspension_risk(
        self,
        suspension_days: dict[str, int],
        holdings: set[str] | None = None,
    ) -> list[str]:
        """检查长期停牌."""
        triggered: list[str] = []
        check_set = set(holdings) if holdings else set(suspension_days.keys())
        for symbol in check_set:
            if suspension_days.get(symbol, 0) > self.config.max_suspension_days:
                triggered.append(symbol)
        return triggered

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _is_st(name: str) -> bool:
        """股票名称是否含 ST/PT."""
        if not name:
            return False
        return any(tag in str(name).upper() for tag in ("ST", "PT"))

    def _is_delisted(self, symbol: str) -> bool:
        """检查是否已知退市股票."""
        if self._known_delisted is None:
            self._known_delisted = self._load_delisted()
        return symbol in self._known_delisted

    def _is_blacklisted(self, symbol: str) -> bool:
        """检查是否在黑名单中."""
        if self._blacklist is None:
            self._blacklist = self._load_blacklist()
        return symbol in self._blacklist

    @staticmethod
    def _load_delisted() -> set[str]:
        """加载已知退市列表."""
        try:
            from qp.data.cleaning.delisted_handler import DelistedHandler

            handler = DelistedHandler()
            return set(handler.get_delisted_codes())
        except Exception:
            return set()

    @staticmethod
    def _load_blacklist() -> set[str]:
        """从 JSON 文件加载黑名单.

        Blacklist 格式 (data/blacklist.json):
            ["000001", "600519"]  或  {"symbols": ["000001"], "reason": "..."}
        """
        try:
            path = Path(BLACKLIST)
            if not path.exists():
                # Create empty blacklist template
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('{"symbols": [], "reason": "人工维护的黑名单"}', encoding="utf-8")
                return set()
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return {str(s) for s in data}
            return {str(s) for s in data.get("symbols", [])}
        except (OSError, json.JSONDecodeError):
            return set()

    @staticmethod
    def _highest_priority(reasons: list[str]) -> Priority:
        """从原因列表提取最高优先级."""
        if (
            TradeReason.RISK_ST in reasons
            or TradeReason.RISK_DELIST in reasons
            or TradeReason.RISK_BLACKLIST in reasons
        ):
            return Priority.CRITICAL
        if TradeReason.STOP_LOSS in reasons:
            return Priority.HIGH
        if TradeReason.RISK_SUSPENSION in reasons or TradeReason.RISK_LIQUIDITY in reasons:
            return Priority.MEDIUM
        # RANK_DROP, FUNDAMENTAL_DETERIORATION, REBALANCE, SECTOR_OVERWEIGHT → LOW
        return Priority.LOW

    @staticmethod
    def _build_detail(
        symbol: str,
        name: str,
        px: float,
        cost: float,
        reasons: list[str],
    ) -> str:
        """生成人类可读详情."""
        parts = []
        if TradeReason.STOP_LOSS in reasons and cost > 0:
            pnl = (px - cost) / cost * 100
            parts.append(f"止损 {pnl:+.1f}% (成本¥{cost:.2f} → 现价¥{px:.2f})")
        if TradeReason.RISK_ST in reasons:
            parts.append(f"ST 警告 ({name})")
        if TradeReason.RISK_DELIST in reasons:
            parts.append("退市风险")
        if TradeReason.RISK_BLACKLIST in reasons:
            parts.append("黑名单")
        if TradeReason.RISK_SUSPENSION in reasons:
            parts.append("长期停牌")
        if TradeReason.RISK_LIQUIDITY in reasons:
            parts.append("流动性不足")
        return "; ".join(parts) if parts else str(reasons)
