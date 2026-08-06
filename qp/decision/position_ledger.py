"""Position Ledger — tracks positions from decision approval to exit.

Each position is linked to a DecisionPackage and strategy, creating a full
audit trail from "why did we buy this?" to "why did we sell it?"

Storage: data/positions/positions.parquet + data/positions/index.json

Usage:
    ledger = PositionLedger()
    pos = ledger.open(
        symbol="600519", entry_price=1450.0, shares=100,
        strategy_id="momentum_v1.0", decision_id="dp-2026-07-30-xxx",
    )
    active = ledger.get_active()         # → list[Position]
    ledger.close(pos.position_id, exit_price=1500.0, reason="target reached")
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
from loguru import logger

from qp.shared.types import PositionState

POSITIONS_DIR = Path("data/positions")
POSITIONS_PARQUET = POSITIONS_DIR / "positions.parquet"
POSITIONS_INDEX = POSITIONS_DIR / "index.json"


# ==================================================================
# Position data model
# ==================================================================


@dataclass
class Position:
    """A single position in the portfolio, linked to its decision origin.

    Attributes:
        position_id: Unique identifier (e.g. "P-00001").
        symbol: Stock code (e.g. "600519").
        entry_date: Date the position was opened (YYYY-MM-DD).
        entry_price: Average fill price per share.
        shares: Number of shares held.
        strategy_id: Which strategy generated the buy signal.
        decision_id: Which DecisionPackage approved this position.
        status: PositionState — HOLDING, REDUCING, CLOSED, etc.
        exit_date: Date closed (if CLOSED).
        exit_price: Average exit price (if CLOSED).
        exit_reason: Why the position was closed (e.g. "stop_loss", "rank_drop").
        pnl: Realized P&L in CNY (if CLOSED).
        pnl_pct: Realized P&L as percentage.
        notes: Optional free-text notes.
    """

    position_id: str = ""
    symbol: str = ""
    entry_date: str = ""
    entry_price: float = 0.0
    shares: int = 0
    strategy_id: str = ""
    decision_id: str = ""
    status: PositionState = PositionState.HOLDING
    exit_date: str = ""
    exit_price: float = 0.0
    exit_reason: str = ""
    pnl: float = 0.0
    pnl_pct: float = 0.0
    notes: str = ""

    @property
    def is_active(self) -> bool:
        """True if this position is still held."""
        return self.status in (PositionState.HOLDING, PositionState.REDUCING)

    @property
    def market_value(self) -> float:
        """Current market value (entry price × shares)."""
        return self.entry_price * self.shares

    @property
    def realized_pnl(self) -> float:
        """Realized P&L (exit - entry) × shares, if closed."""
        if self.status == PositionState.CLOSED and self.exit_price > 0:
            return (self.exit_price - self.entry_price) * self.shares
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "position_id": self.position_id,
            "symbol": self.symbol,
            "entry_date": self.entry_date,
            "entry_price": self.entry_price,
            "shares": self.shares,
            "strategy_id": self.strategy_id,
            "decision_id": self.decision_id,
            "status": self.status.value,
            "status_name": self.status.name,
            "exit_date": self.exit_date,
            "exit_price": self.exit_price,
            "exit_reason": self.exit_reason,
            "pnl": self.realized_pnl,
            "pnl_pct": round(self.pnl_pct, 4),
            "notes": self.notes,
            "is_active": self.is_active,
            "market_value": self.market_value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Position:
        status_raw = data.get("status", PositionState.HOLDING.value)
        if isinstance(status_raw, int):
            status = PositionState(status_raw)
        elif isinstance(status_raw, str) and status_raw.isdigit():
            status = PositionState(int(status_raw))
        else:
            try:
                status = (
                    PositionState[status_raw]
                    if status_raw.isupper()
                    else PositionState(int(status_raw))
                )
            except (KeyError, ValueError):
                status = PositionState.HOLDING

        return cls(
            position_id=str(data.get("position_id", "")),
            symbol=str(data.get("symbol", "")),
            entry_date=str(data.get("entry_date", "")),
            entry_price=float(data.get("entry_price", 0.0)),
            shares=int(data.get("shares", 0)),
            strategy_id=str(data.get("strategy_id", "")),
            decision_id=str(data.get("decision_id", "")),
            status=status,
            exit_date=str(data.get("exit_date", "")),
            exit_price=float(data.get("exit_price", 0.0)),
            exit_reason=str(data.get("exit_reason", "")),
            pnl=float(data.get("pnl", 0.0)),
            pnl_pct=float(data.get("pnl_pct", 0.0)),
            notes=str(data.get("notes", "")),
        )


# ==================================================================
# PositionLedger — CRUD + persistence
# ==================================================================


class PositionLedger:
    """Manages the lifecycle of positions with Parquet persistence.

    Usage:
        ledger = PositionLedger()
        pos = ledger.open("600519", 1450.0, 100, "momentum_v1.0", "dp-xxx")
        active = ledger.get_active()
        ledger.close(pos.position_id, 1500.0, "target_reached")
    """

    def __init__(self) -> None:
        POSITIONS_DIR.mkdir(parents=True, exist_ok=True)
        self._next_id = self._load_next_id()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def open(
        self,
        symbol: str,
        entry_price: float,
        shares: int,
        strategy_id: str = "",
        decision_id: str = "",
        entry_date: str = "",
        notes: str = "",
    ) -> Position:
        """Open a new position.

        Args:
            symbol: Stock code.
            entry_price: Fill price per share.
            shares: Number of shares.
            strategy_id: Source strategy.
            decision_id: Approving DecisionPackage.
            entry_date: Date (defaults to today).
            notes: Optional notes.

        Returns:
            The newly created Position.
        """
        if not entry_date:
            entry_date = datetime.now(UTC).date().isoformat()

        pos_id = self._generate_id()
        position = Position(
            position_id=pos_id,
            symbol=symbol,
            entry_date=entry_date,
            entry_price=entry_price,
            shares=shares,
            strategy_id=strategy_id,
            decision_id=decision_id,
            status=PositionState.HOLDING,
            notes=notes,
        )

        self._save(position)
        logger.info(
            "Position opened: {} {} {}shares @¥{}", pos_id, symbol, shares, entry_price
        )
        return position

    def close(
        self,
        position_id: str,
        exit_price: float,
        exit_reason: str = "",
        exit_date: str = "",
        notes: str = "",
    ) -> Position | None:
        """Close an active position.

        Args:
            position_id: Position to close.
            exit_price: Exit fill price.
            exit_reason: Why (e.g. "stop_loss", "rank_drop", "target_reached").
            exit_date: Date (defaults to today).
            notes: Optional notes.

        Returns:
            Updated Position, or None if not found or already closed.
        """
        pos = self.get(position_id)
        if pos is None:
            logger.warning("Position not found: {}", position_id)
            return None
        if not pos.is_active:
            logger.warning("Position already closed: {}", position_id)
            return None

        if not exit_date:
            exit_date = datetime.now(UTC).date().isoformat()

        pos.status = PositionState.CLOSED
        pos.exit_price = exit_price
        pos.exit_date = exit_date
        pos.exit_reason = exit_reason
        pos.pnl = (exit_price - pos.entry_price) * pos.shares
        pos.pnl_pct = (
            (exit_price - pos.entry_price) / pos.entry_price
            if pos.entry_price > 0
            else 0.0
        )
        if notes:
            pos.notes = pos.notes + "; " + notes if pos.notes else notes

        self._save(pos)
        logger.info(
            "Position closed: {} PnL=¥{:.2f} ({:.2%}) reason={}",
            position_id,
            pos.pnl,
            pos.pnl_pct,
            exit_reason,
        )
        return pos

    def get(self, position_id: str) -> Position | None:
        """Load a single position by ID."""
        df = self._load_df()
        if df.is_empty():
            return None
        filtered = df.filter(pl.col("position_id") == position_id)
        if filtered.is_empty():
            return None
        return Position.from_dict(filtered.row(0, named=True))

    def get_active(self) -> list[Position]:
        """Get all currently active (non-closed) positions."""
        df = self._load_df()
        if df.is_empty():
            return []
        # HOLDING and REDUCING are active
        active_statuses = [PositionState.HOLDING.value, PositionState.REDUCING.value]
        filtered = df.filter(pl.col("status").is_in(active_statuses))
        return [Position.from_dict(row) for row in filtered.to_dicts()]

    def get_by_decision(self, decision_id: str) -> list[Position]:
        """Get all positions linked to a specific DecisionPackage."""
        df = self._load_df()
        if df.is_empty():
            return []
        filtered = df.filter(pl.col("decision_id") == decision_id)
        return [Position.from_dict(row) for row in filtered.to_dicts()]

    def get_history(self, limit: int = 100) -> list[Position]:
        """Get recent positions, most recent first."""
        df = self._load_df()
        if df.is_empty():
            return []
        sorted_df = df.sort("entry_date", descending=True).head(limit)
        return [Position.from_dict(row) for row in sorted_df.to_dicts()]

    def get_all(self) -> list[Position]:
        """Get all positions ever recorded."""
        df = self._load_df()
        if df.is_empty():
            return []
        return [Position.from_dict(row) for row in df.to_dicts()]

    def total_active_value(self) -> float:
        """Total market value of all active positions."""
        return sum(p.market_value for p in self.get_active())

    def total_realized_pnl(self) -> float:
        """Total realized P&L across all closed positions."""
        df = self._load_df()
        if df.is_empty():
            return 0.0
        closed = df.filter(pl.col("status") == PositionState.CLOSED.value)
        if closed.is_empty():
            return 0.0
        return float(closed["pnl"].sum())

    # ------------------------------------------------------------------
    # Internal: persistence
    # ------------------------------------------------------------------

    def _save(self, position: Position) -> None:
        """Save (upsert) a position to Parquet and update index."""
        row = position.to_dict()
        new_df = pl.DataFrame([row])

        df = self._load_df()
        if not df.is_empty():
            # Remove existing entry with same ID
            df = df.filter(pl.col("position_id") != position.position_id)
            df = pl.concat([df, new_df], how="diagonal_relaxed")
        else:
            df = new_df

        df.write_parquet(str(POSITIONS_PARQUET))
        self._update_index()

    def _load_df(self) -> pl.DataFrame:
        """Load positions from Parquet."""
        if not POSITIONS_PARQUET.exists():
            return pl.DataFrame()
        try:
            return pl.read_parquet(str(POSITIONS_PARQUET))
        except Exception:
            return pl.DataFrame()

    def _generate_id(self) -> str:
        """Generate the next sequential position ID."""
        pos_id = f"P-{self._next_id:05d}"
        self._next_id += 1
        self._save_next_id()
        return pos_id

    def _load_next_id(self) -> int:
        """Load the next position ID counter."""
        if not POSITIONS_INDEX.exists():
            return 1
        try:
            data = json.loads(POSITIONS_INDEX.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data.get("next_id", 1)
            # Legacy format: list or unexpected structure
            return 1
        except (json.JSONDecodeError, OSError, AttributeError):
            return 1

    def _save_next_id(self) -> None:
        """Persist the next ID counter."""
        POSITIONS_INDEX.write_text(
            json.dumps({"next_id": self._next_id}, indent=2),
            encoding="utf-8",
        )

    def _update_index(self) -> None:
        """Refresh index with summary stats."""
        active = self.get_active()
        all_positions = self.get_all()
        data = {
            "next_id": self._next_id,
            "active_count": len(active),
            "total_count": len(all_positions),
            "active_value": self.total_active_value(),
            "total_realized_pnl": self.total_realized_pnl(),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        POSITIONS_INDEX.write_text(
            json.dumps(data, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Bulk operations (P2.3 — approve → create positions)
    # ------------------------------------------------------------------

    def open_from_decision(
        self,
        decision_package: Any,  # DecisionPackage
    ) -> list[Position]:
        """Create positions from an approved DecisionPackage's recommendations.

        Idempotent: skips symbols that already have active positions from
        this decision_id to prevent duplicates on re-approval.

        Args:
            decision_package: An approved DecisionPackage with BUY recommendations.

        Returns:
            List of newly created Positions (may be empty if all already exist).
        """
        # Check existing positions for this decision
        existing = self.get_by_decision(decision_package.package_id)
        existing_symbols = {p.symbol for p in existing if p.is_active}

        positions: list[Position] = []
        for rec in decision_package.report.recommendations:
            if rec.action != "BUY" or rec.quantity_shares <= 0:
                continue
            if rec.symbol in existing_symbols:
                continue  # Already opened — dedup
            pos = self.open(
                symbol=rec.symbol,
                entry_price=rec.estimated_price,
                shares=rec.quantity_shares,
                strategy_id=rec.strategy,
                decision_id=decision_package.package_id,
                notes=f"Weight: {rec.target_weight_pct:.1f}% | {rec.reason}",
            )
            positions.append(pos)
        logger.info(
            "Bulk opened {} positions from {}",
            len(positions),
            decision_package.package_id,
        )
        return positions
