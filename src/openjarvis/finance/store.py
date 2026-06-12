"""SQLite store for portfolio holdings and a paper-trading account.

Two concerns share one DB file (``~/.openjarvis/finance.db``):

* ``holdings`` — real positions the user wants tracked (symbol, qty, cost basis).
* ``paper_account`` / ``paper_positions`` / ``paper_trades`` — a simulated cash
  trading account for risk-free strategy testing.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

DEFAULT_STARTING_CASH = 100_000.0


@dataclass
class Holding:
    symbol: str
    asset_type: str
    quantity: float
    cost_basis: float  # per-unit cost


@dataclass
class PaperPosition:
    symbol: str
    asset_type: str
    quantity: float
    avg_price: float


@dataclass
class PaperTrade:
    ts: str
    side: str
    symbol: str
    asset_type: str
    quantity: float
    price: float


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FinanceStore:
    """Persistent store for tracked holdings and a paper-trading account."""

    def __init__(self, db_path: str = "") -> None:
        if not db_path:
            db_path = str(Path.home() / ".openjarvis" / "finance.db")
        self._db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()
        self._conn.commit()

    def _create_tables(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS holdings (
                symbol TEXT NOT NULL,
                asset_type TEXT NOT NULL,
                quantity REAL NOT NULL,
                cost_basis REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                PRIMARY KEY (symbol, asset_type)
            );

            CREATE TABLE IF NOT EXISTS paper_account (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                cash REAL NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS paper_positions (
                symbol TEXT NOT NULL,
                asset_type TEXT NOT NULL,
                quantity REAL NOT NULL,
                avg_price REAL NOT NULL,
                PRIMARY KEY (symbol, asset_type)
            );

            CREATE TABLE IF NOT EXISTS paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                side TEXT NOT NULL,
                symbol TEXT NOT NULL,
                asset_type TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL NOT NULL
            );
            """
        )

    # -- Holdings --------------------------------------------------------------

    def add_holding(
        self, symbol: str, asset_type: str, quantity: float, cost_basis: float = 0.0
    ) -> Holding:
        """Insert or update a tracked holding (replaces existing same-key row)."""
        symbol = symbol.upper()
        self._conn.execute(
            """
            INSERT INTO holdings (symbol, asset_type, quantity, cost_basis, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(symbol, asset_type) DO UPDATE SET
                quantity = excluded.quantity,
                cost_basis = excluded.cost_basis
            """,
            (symbol, asset_type, float(quantity), float(cost_basis), _now()),
        )
        self._conn.commit()
        return Holding(symbol, asset_type, float(quantity), float(cost_basis))

    def list_holdings(self) -> List[Holding]:
        cur = self._conn.execute(
            "SELECT symbol, asset_type, quantity, cost_basis FROM holdings"
            " ORDER BY symbol"
        )
        return [Holding(r[0], r[1], r[2], r[3]) for r in cur.fetchall()]

    def remove_holding(self, symbol: str, asset_type: Optional[str] = None) -> int:
        """Delete holding(s) for a symbol. Returns number of rows removed."""
        symbol = symbol.upper()
        if asset_type:
            cur = self._conn.execute(
                "DELETE FROM holdings WHERE symbol = ? AND asset_type = ?",
                (symbol, asset_type),
            )
        else:
            cur = self._conn.execute(
                "DELETE FROM holdings WHERE symbol = ?", (symbol,)
            )
        self._conn.commit()
        return cur.rowcount

    # -- Paper account ---------------------------------------------------------

    def ensure_account(self, starting_cash: float = DEFAULT_STARTING_CASH) -> float:
        """Create the paper account if missing; return current cash balance."""
        row = self._conn.execute(
            "SELECT cash FROM paper_account WHERE id = 1"
        ).fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO paper_account (id, cash, created_at) VALUES (1, ?, ?)",
                (float(starting_cash), _now()),
            )
            self._conn.commit()
            return float(starting_cash)
        return float(row[0])

    def get_cash(self) -> float:
        return self.ensure_account()

    def reset_paper_account(self, starting_cash: float = DEFAULT_STARTING_CASH) -> None:
        self._conn.execute("DELETE FROM paper_positions")
        self._conn.execute("DELETE FROM paper_trades")
        self._conn.execute("DELETE FROM paper_account")
        self._conn.execute(
            "INSERT INTO paper_account (id, cash, created_at) VALUES (1, ?, ?)",
            (float(starting_cash), _now()),
        )
        self._conn.commit()

    def list_paper_positions(self) -> List[PaperPosition]:
        cur = self._conn.execute(
            "SELECT symbol, asset_type, quantity, avg_price FROM paper_positions"
            " WHERE quantity > 0 ORDER BY symbol"
        )
        return [PaperPosition(r[0], r[1], r[2], r[3]) for r in cur.fetchall()]

    def list_paper_trades(self, limit: int = 50) -> List[PaperTrade]:
        cur = self._conn.execute(
            "SELECT ts, side, symbol, asset_type, quantity, price FROM paper_trades"
            " ORDER BY id DESC LIMIT ?",
            (int(limit),),
        )
        return [PaperTrade(r[0], r[1], r[2], r[3], r[4], r[5]) for r in cur.fetchall()]

    def execute_paper_trade(
        self, side: str, symbol: str, asset_type: str, quantity: float, price: float
    ) -> PaperTrade:
        """Execute a simulated buy/sell at *price*, updating cash and positions.

        Raises ``ValueError`` on insufficient funds (buy) or insufficient
        holdings (sell).
        """
        side = side.lower()
        if side not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")
        symbol = symbol.upper()
        quantity = float(quantity)
        price = float(price)
        if quantity <= 0:
            raise ValueError("quantity must be positive")

        cash = self.ensure_account()
        cost = quantity * price

        row = self._conn.execute(
            "SELECT quantity, avg_price FROM paper_positions"
            " WHERE symbol = ? AND asset_type = ?",
            (symbol, asset_type),
        ).fetchone()
        held_qty = float(row[0]) if row else 0.0
        held_avg = float(row[1]) if row else 0.0

        if side == "buy":
            if cost > cash + 1e-9:
                raise ValueError(
                    f"Insufficient cash: need {cost:.2f}, have {cash:.2f}"
                )
            new_cash = cash - cost
            new_qty = held_qty + quantity
            new_avg = (
                (held_qty * held_avg + cost) / new_qty if new_qty > 0 else 0.0
            )
        else:  # sell
            if quantity > held_qty + 1e-9:
                raise ValueError(
                    f"Insufficient position: trying to sell {quantity}, "
                    f"hold {held_qty}"
                )
            new_cash = cash + cost
            new_qty = held_qty - quantity
            new_avg = held_avg  # avg cost unchanged on a sell

        self._conn.execute(
            "UPDATE paper_account SET cash = ? WHERE id = 1", (new_cash,)
        )
        self._conn.execute(
            """
            INSERT INTO paper_positions (symbol, asset_type, quantity, avg_price)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(symbol, asset_type) DO UPDATE SET
                quantity = excluded.quantity,
                avg_price = excluded.avg_price
            """,
            (symbol, asset_type, new_qty, new_avg),
        )
        ts = _now()
        self._conn.execute(
            "INSERT INTO paper_trades (ts, side, symbol, asset_type, quantity, price)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (ts, side, symbol, asset_type, quantity, price),
        )
        self._conn.commit()
        return PaperTrade(ts, side, symbol, asset_type, quantity, price)

    def close(self) -> None:
        self._conn.close()


__all__ = [
    "FinanceStore",
    "Holding",
    "PaperPosition",
    "PaperTrade",
    "DEFAULT_STARTING_CASH",
]
