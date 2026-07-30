"""Shadow Ledger — paper trading / shadow production system.

Simulates daily execution of DecisionPackage recommendations without real
money. Tracks shadow positions and daily P&L for production validation.

Answers: "If I had followed the system's recommendations, what would my
returns look like?"

Storage: data/simulation/shadow_positions.parquet + shadow_daily.parquet

Usage:
    ledger = ShadowLedger()
    result = ledger.run_daily(date_str="2026-07-30")
    print(f"Shadow P&L: ¥{result['daily_pnl']:,.0f}")
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
from loguru import logger

SIM_DIR = Path("data/simulation")
SHADOW_POSITIONS = SIM_DIR / "shadow_positions.parquet"
SHADOW_DAILY = SIM_DIR / "shadow_daily.parquet"
SHADOW_INDEX = SIM_DIR / "shadow_index.json"


@dataclass
class ShadowPosition:
    """A shadow (paper) position tracking simulated entry and current value."""

    symbol: str
    entry_date: str
    entry_price: float
    shares: int
    strategy: str
    decision_id: str
    status: str = "ACTIVE"  # ACTIVE | CLOSED
    exit_date: str = ""
    exit_price: float = 0.0
    exit_reason: str = ""
    pnl: float = 0.0
    pnl_pct: float = 0.0

    @property
    def market_value(self) -> float:
        return self.entry_price * self.shares

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "entry_date": self.entry_date,
            "entry_price": self.entry_price,
            "shares": self.shares,
            "strategy": self.strategy,
            "decision_id": self.decision_id,
            "status": self.status,
            "exit_date": self.exit_date,
            "exit_price": self.exit_price,
            "exit_reason": self.exit_reason,
            "pnl": self.pnl,
            "pnl_pct": self.pnl_pct,
            "market_value": self.market_value,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ShadowPosition:
        return cls(
            symbol=str(d.get("symbol", "")),
            entry_date=str(d.get("entry_date", "")),
            entry_price=float(d.get("entry_price", 0)),
            shares=int(d.get("shares", 0)),
            strategy=str(d.get("strategy", "")),
            decision_id=str(d.get("decision_id", "")),
            status=str(d.get("status", "ACTIVE")),
            exit_date=str(d.get("exit_date", "")),
            exit_price=float(d.get("exit_price", 0)),
            exit_reason=str(d.get("exit_reason", "")),
            pnl=float(d.get("pnl", 0)),
            pnl_pct=float(d.get("pnl_pct", 0)),
        )


class ShadowLedger:
    """Manages the shadow portfolio lifecycle.

    Usage:
        ledger = ShadowLedger()
        result = ledger.run_daily("2026-07-30")
    """

    def __init__(self, initial_capital: float = 1_000_000.0) -> None:
        SIM_DIR.mkdir(parents=True, exist_ok=True)
        self._capital = initial_capital

    # ------------------------------------------------------------------
    # Daily Run
    # ------------------------------------------------------------------

    def run_daily(self, date_str: str = "") -> dict[str, Any]:
        """Execute one day of shadow trading.

        1. Mark existing positions to market (today's close price)
        2. Execute SELL recommendations → close shadow positions
        3. Execute BUY recommendations → open new shadow positions
        4. Record daily P&L snapshot

        Returns:
            Dict with daily_summary, positions, pnl.
        """
        if not date_str:
            date_str = datetime.now(UTC).date().isoformat()

        # Load today's DecisionPackage
        from qp.decision.decision_package import DecisionPackage

        dp = DecisionPackage.load_latest()
        if dp is None:
            return {"date": date_str, "status": "no_decision", "daily_pnl": 0.0}

        # Load price data for mark-to-market
        prices = self._load_prices(date_str)

        # 1. Mark existing positions to market
        active = self._load_active()
        daily_pnl = 0.0
        for pos in active:
            px = prices.get(pos.symbol, pos.entry_price)
            if px > 0:
                unrealized = (px - pos.entry_price) * pos.shares
                daily_pnl += unrealized

        # 2. Execute SELL recommendations
        sell_recs = [r for r in dp.report.recommendations if r.action == "SELL"]
        for rec in sell_recs:
            self._close_position(rec.symbol, rec.estimated_price, rec.reason, date_str)

        # 3. Execute BUY recommendations (skip if already have active position)
        active_symbols = {p.symbol for p in self._load_active()}
        new_positions = 0
        for rec in dp.report.buys:
            if rec.symbol in active_symbols:
                continue
            if rec.quantity_shares <= 0:
                continue
            pos = ShadowPosition(
                symbol=rec.symbol,
                entry_date=date_str,
                entry_price=rec.estimated_price,
                shares=rec.quantity_shares,
                strategy=rec.strategy,
                decision_id=dp.package_id,
            )
            self._save_position(pos)
            new_positions += 1

        # 4. Record daily snapshot
        active_after = self._load_active()
        total_value = sum(
            p.shares * max(prices.get(p.symbol, p.entry_price), 0)
            for p in active_after
        )
        closed = self._load_closed()
        realized_pnl = sum(p.pnl for p in closed)

        snapshot = {
            "date": date_str,
            "n_positions": len(active_after),
            "market_value": total_value,
            "cash": self._capital - total_value,
            "realized_pnl": realized_pnl,
            "unrealized_pnl": daily_pnl,
            "total_equity": self._capital + realized_pnl + daily_pnl,
            "decision_id": dp.package_id,
            "n_buys": dp.report.n_buys,
            "n_sells": dp.report.n_sells,
        }
        self._save_daily(snapshot)

        logger.info(
            "Shadow daily {}: equity=¥{:.0f} pnl=¥{:.0f} positions={}",
            date_str, snapshot["total_equity"], daily_pnl, len(active_after),
        )

        return snapshot

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_history(self, days: int = 60) -> list[dict[str, Any]]:
        """Get daily P&L history."""
        if not SHADOW_DAILY.exists():
            return []
        df = pl.read_parquet(str(SHADOW_DAILY)).sort("date").tail(days)
        return df.to_dicts()

    def get_positions(self) -> list[dict[str, Any]]:
        """Get current shadow positions."""
        return [p.to_dict() for p in self._load_active()]

    def summary(self) -> dict[str, Any]:
        """Portfolio summary for display."""
        history = self.get_history(days=90)
        active = self._load_active()
        closed = self._load_closed()

        total_value = sum(
            p.market_value for p in active
        )
        total_pnl = sum(p.pnl for p in closed)
        winning = len([p for p in closed if p.pnl > 0])

        # Compute cumulative return
        if history:
            first_equity = history[0]["total_equity"]
            last_equity = history[-1]["total_equity"]
            total_return = (last_equity - first_equity) / first_equity if first_equity > 0 else 0
        else:
            total_return = 0.0

        return {
            "active_count": len(active),
            "total_value": total_value,
            "total_value_fmt": f"¥{total_value:,.0f}",
            "realized_pnl": total_pnl,
            "realized_pnl_fmt": f"¥{total_pnl:+,.0f}",
            "closed_count": len(closed),
            "win_rate": f"{winning}/{len(closed)} ({winning/len(closed)*100:.0f}%)" if closed else "N/A",
            "total_return": total_return,
            "total_return_fmt": f"{total_return:+.2%}",
            "history": history,
            "pnl_badge": "badge-green" if total_pnl >= 0 else "badge-red",
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_active(self) -> list[ShadowPosition]:
        return self._load_by_status("ACTIVE")

    def _load_closed(self) -> list[ShadowPosition]:
        return self._load_by_status("CLOSED")

    def _load_by_status(self, status: str) -> list[ShadowPosition]:
        if not SHADOW_POSITIONS.exists():
            return []
        df = pl.read_parquet(str(SHADOW_POSITIONS))
        if df.is_empty():
            return []
        filtered = df.filter(pl.col("status") == status)
        return [ShadowPosition.from_dict(r) for r in filtered.to_dicts()]

    def _save_position(self, pos: ShadowPosition) -> None:
        row = pos.to_dict()
        new_df = pl.DataFrame([row])
        if SHADOW_POSITIONS.exists():
            existing = pl.read_parquet(str(SHADOW_POSITIONS))
            # Remove existing entry for same symbol if active
            existing = existing.filter(
                ~((pl.col("symbol") == pos.symbol) & (pl.col("status") == "ACTIVE"))
            )
            combined = pl.concat([existing, new_df], how="diagonal_relaxed")
        else:
            combined = new_df
        combined.write_parquet(str(SHADOW_POSITIONS))

    def _close_position(self, symbol: str, exit_price: float, reason: str, date_str: str) -> None:
        if not SHADOW_POSITIONS.exists():
            return
        df = pl.read_parquet(str(SHADOW_POSITIONS))
        mask = (pl.col("symbol") == symbol) & (pl.col("status") == "ACTIVE")
        active = df.filter(mask)
        if active.is_empty():
            return

        # Get all active rows and update them
        for row in active.to_dicts():
            p = ShadowPosition.from_dict(row)
            p.status = "CLOSED"
            p.exit_date = date_str
            p.exit_price = exit_price
            p.exit_reason = reason
            p.pnl = (exit_price - p.entry_price) * p.shares
            p.pnl_pct = (exit_price - p.entry_price) / p.entry_price if p.entry_price > 0 else 0

            # Replace in df
            df = df.filter(~((pl.col("symbol") == symbol) & (pl.col("status") == "ACTIVE")))
            new_row = pl.DataFrame([p.to_dict()])
            df = pl.concat([df, new_row], how="diagonal_relaxed")
            logger.info("Shadow close: {} PnL=¥{:.0f}", symbol, p.pnl)

        df.write_parquet(str(SHADOW_POSITIONS))

    @staticmethod
    def _load_prices(date_str: str) -> dict[str, float]:
        """Load latest close prices for mark-to-market."""
        price_path = Path("data/dataset/daily_price_latest.parquet")
        if not price_path.exists():
            return {}
        try:
            df = pl.read_parquet(str(price_path))
            if df.is_empty():
                return {}
            latest = df.sort("trade_date", descending=True).unique(
                subset=["symbol"], keep="first"
            )
            return {
                str(r["symbol"]): float(r["close"])
                for r in latest.iter_rows(named=True)
            }
        except Exception:
            return {}

    def _save_daily(self, snapshot: dict[str, Any]) -> None:
        """Append daily snapshot to parquet."""
        new_df = pl.DataFrame([snapshot])
        if SHADOW_DAILY.exists():
            existing = pl.read_parquet(str(SHADOW_DAILY))
            existing = existing.filter(pl.col("date") != snapshot["date"])
            combined = pl.concat([existing, new_df], how="diagonal_relaxed")
        else:
            combined = new_df
        combined.write_parquet(str(SHADOW_DAILY))
