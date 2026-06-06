"""Finance agent tools: crypto/stock quotes, technical analysis, portfolio
tracking, and a paper-trading account.

Quotes use free, key-free providers (CoinGecko, Stooq). Portfolio and paper
trades persist to a local SQLite DB and have no real-world side effects, so they
are not gated behind confirmation.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.finance import indicators, prices
from openjarvis.finance.store import FinanceStore
from openjarvis.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)

_STORE: Optional[FinanceStore] = None


def _store() -> FinanceStore:
    global _STORE
    if _STORE is None:
        _STORE = FinanceStore()
    return _STORE


def _norm_asset_type(value: Any) -> str:
    s = str(value or "stock").strip().lower()
    if s in ("crypto", "coin", "cryptocurrency"):
        return "crypto"
    return "stock"


def _fmt_money(value: Optional[float], currency: str = "USD") -> str:
    if value is None:
        return "n/a"
    return f"{value:,.2f} {currency}"


# ---------------------------------------------------------------------------
# crypto_price
# ---------------------------------------------------------------------------


@ToolRegistry.register("crypto_price")
class CryptoPriceTool(BaseTool):
    tool_id = "crypto_price"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="crypto_price",
            description=(
                "Get the current price and 24h change for a cryptocurrency"
                " (e.g. BTC, ETH). No API key required."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Ticker, e.g. BTC."},
                    "vs_currency": {
                        "type": "string",
                        "description": "Quote currency (default usd).",
                    },
                },
                "required": ["symbol"],
            },
            category="finance",
        )

    def execute(self, **params: Any) -> ToolResult:
        symbol = str(params.get("symbol", "")).strip()
        if not symbol:
            return ToolResult(
                tool_name="crypto_price", content="No symbol provided.", success=False
            )
        vs = str(params.get("vs_currency", "usd") or "usd")
        try:
            data = prices.get_crypto_price(symbol, vs_currency=vs)
        except Exception as exc:
            return ToolResult(
                tool_name="crypto_price",
                content=f"Crypto price lookup failed: {exc}",
                success=False,
            )
        change = data.get("change_24h")
        change_str = f" ({change:+.2f}% 24h)" if isinstance(change, (int, float)) else ""
        return ToolResult(
            tool_name="crypto_price",
            content=(
                f"{data['symbol']}: {_fmt_money(data['price'], data['currency'])}"
                f"{change_str}"
            ),
            success=True,
            metadata=data,
        )


# ---------------------------------------------------------------------------
# stock_quote
# ---------------------------------------------------------------------------


@ToolRegistry.register("stock_quote")
class StockQuoteTool(BaseTool):
    tool_id = "stock_quote"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="stock_quote",
            description=(
                "Get the latest stock/ETF quote (OHLCV) for a ticker"
                " (e.g. AAPL). No API key required."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Ticker, e.g. AAPL."},
                },
                "required": ["symbol"],
            },
            category="finance",
        )

    def execute(self, **params: Any) -> ToolResult:
        symbol = str(params.get("symbol", "")).strip()
        if not symbol:
            return ToolResult(
                tool_name="stock_quote", content="No symbol provided.", success=False
            )
        try:
            data = prices.get_stock_quote(symbol)
        except Exception as exc:
            return ToolResult(
                tool_name="stock_quote",
                content=f"Stock quote lookup failed: {exc}",
                success=False,
            )
        return ToolResult(
            tool_name="stock_quote",
            content=(
                f"{data['symbol']}: {_fmt_money(data['price'])} "
                f"(O {data['open']} H {data['high']} L {data['low']} "
                f"V {data['volume']}) as of {data['date']}"
            ),
            success=True,
            metadata=data,
        )


# ---------------------------------------------------------------------------
# technical_analysis
# ---------------------------------------------------------------------------


@ToolRegistry.register("technical_analysis")
class TechnicalAnalysisTool(BaseTool):
    tool_id = "technical_analysis"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="technical_analysis",
            description=(
                "Compute technical indicators (SMA20/50, RSI14, MACD) and a"
                " naive bias for a crypto or stock symbol."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Ticker symbol."},
                    "asset_type": {
                        "type": "string",
                        "description": "'stock' or 'crypto'. Default stock.",
                    },
                    "days": {
                        "type": "integer",
                        "description": "History window in days (default 120).",
                    },
                },
                "required": ["symbol"],
            },
            category="finance",
        )

    def execute(self, **params: Any) -> ToolResult:
        symbol = str(params.get("symbol", "")).strip()
        if not symbol:
            return ToolResult(
                tool_name="technical_analysis",
                content="No symbol provided.",
                success=False,
            )
        asset_type = _norm_asset_type(params.get("asset_type"))
        try:
            days = int(params.get("days", 120) or 120)
        except (TypeError, ValueError):
            days = 120

        try:
            series = prices.get_series(symbol, asset_type, days)
        except Exception as exc:
            return ToolResult(
                tool_name="technical_analysis",
                content=f"Could not load price history: {exc}",
                success=False,
            )

        s = indicators.summarize(series)

        def _r(v: Any, nd: int = 2) -> str:
            return f"{v:.{nd}f}" if isinstance(v, (int, float)) else "n/a"

        macd_str = "n/a"
        if s["macd"] is not None:
            m, sig, hist = s["macd"]
            macd_str = f"macd {_r(m)}, signal {_r(sig)}, hist {_r(hist)}"

        lines = [
            f"Technical analysis for {symbol.upper()} ({asset_type}):",
            f"  Last: {_r(s['last'])}  SMA20: {_r(s['sma20'])}  SMA50: {_r(s['sma50'])}",
            f"  RSI14: {_r(s['rsi14'])}  MACD: {macd_str}",
            f"  Signals: {', '.join(s['signals']) or 'none'}",
            f"  Bias: {s['bias'].upper()}",
        ]
        return ToolResult(
            tool_name="technical_analysis",
            content="\n".join(lines),
            success=True,
            metadata={"symbol": symbol.upper(), "asset_type": asset_type, "bias": s["bias"]},
        )


# ---------------------------------------------------------------------------
# portfolio_add / portfolio_view / portfolio_remove
# ---------------------------------------------------------------------------


@ToolRegistry.register("portfolio_add")
class PortfolioAddTool(BaseTool):
    tool_id = "portfolio_add"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="portfolio_add",
            description=(
                "Add or update a tracked holding in the user's portfolio."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Ticker symbol."},
                    "quantity": {"type": "number", "description": "Units held."},
                    "asset_type": {
                        "type": "string",
                        "description": "'stock' or 'crypto'. Default stock.",
                    },
                    "cost_basis": {
                        "type": "number",
                        "description": "Per-unit cost (optional).",
                    },
                },
                "required": ["symbol", "quantity"],
            },
            category="finance",
        )

    def execute(self, **params: Any) -> ToolResult:
        symbol = str(params.get("symbol", "")).strip()
        if not symbol:
            return ToolResult(
                tool_name="portfolio_add", content="No symbol provided.", success=False
            )
        try:
            quantity = float(params.get("quantity"))
        except (TypeError, ValueError):
            return ToolResult(
                tool_name="portfolio_add",
                content="quantity must be a number.",
                success=False,
            )
        asset_type = _norm_asset_type(params.get("asset_type"))
        try:
            cost_basis = float(params.get("cost_basis", 0) or 0)
        except (TypeError, ValueError):
            cost_basis = 0.0

        h = _store().add_holding(symbol, asset_type, quantity, cost_basis)
        return ToolResult(
            tool_name="portfolio_add",
            content=(
                f"Tracking {h.quantity} {h.symbol} ({h.asset_type})"
                f"{f' @ cost {h.cost_basis}' if h.cost_basis else ''}."
            ),
            success=True,
            metadata={"symbol": h.symbol, "asset_type": h.asset_type},
        )


@ToolRegistry.register("portfolio_view")
class PortfolioViewTool(BaseTool):
    tool_id = "portfolio_view"
    is_local = False  # fetches live prices

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="portfolio_view",
            description=(
                "Show the user's tracked portfolio with live valuation and"
                " profit/loss vs. cost basis."
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            category="finance",
        )

    def execute(self, **params: Any) -> ToolResult:
        holdings = _store().list_holdings()
        if not holdings:
            return ToolResult(
                tool_name="portfolio_view",
                content="Portfolio is empty. Add holdings with portfolio_add.",
                success=True,
                metadata={"count": 0},
            )
        lines = ["Portfolio:"]
        total_value = 0.0
        total_cost = 0.0
        for h in holdings:
            try:
                price = prices.get_price(h.symbol, h.asset_type)
            except Exception:
                lines.append(f"  {h.symbol} ({h.asset_type}): {h.quantity} — price n/a")
                continue
            value = price * h.quantity
            total_value += value
            line = f"  {h.symbol} ({h.asset_type}): {h.quantity} @ {price:,.2f} = {value:,.2f}"
            if h.cost_basis:
                cost = h.cost_basis * h.quantity
                total_cost += cost
                pl = value - cost
                pct = (pl / cost * 100) if cost else 0.0
                line += f"  P/L {pl:+,.2f} ({pct:+.1f}%)"
            lines.append(line)
        lines.append(f"Total value: {total_value:,.2f} USD")
        if total_cost:
            lines.append(
                f"Total P/L: {total_value - total_cost:+,.2f} USD"
                f" ({(total_value - total_cost) / total_cost * 100:+.1f}%)"
            )
        return ToolResult(
            tool_name="portfolio_view",
            content="\n".join(lines),
            success=True,
            metadata={"count": len(holdings), "total_value": total_value},
        )


@ToolRegistry.register("portfolio_remove")
class PortfolioRemoveTool(BaseTool):
    tool_id = "portfolio_remove"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="portfolio_remove",
            description="Remove a tracked holding from the user's portfolio.",
            parameters={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Ticker to remove."},
                    "asset_type": {
                        "type": "string",
                        "description": "Optional: 'stock' or 'crypto'.",
                    },
                },
                "required": ["symbol"],
            },
            category="finance",
        )

    def execute(self, **params: Any) -> ToolResult:
        symbol = str(params.get("symbol", "")).strip()
        if not symbol:
            return ToolResult(
                tool_name="portfolio_remove",
                content="No symbol provided.",
                success=False,
            )
        asset_type = (
            _norm_asset_type(params.get("asset_type"))
            if params.get("asset_type")
            else None
        )
        removed = _store().remove_holding(symbol, asset_type)
        return ToolResult(
            tool_name="portfolio_remove",
            content=(
                f"Removed {removed} holding(s) for {symbol.upper()}."
                if removed
                else f"No tracked holding found for {symbol.upper()}."
            ),
            success=True,
            metadata={"removed": removed},
        )


# ---------------------------------------------------------------------------
# paper_trade / paper_account
# ---------------------------------------------------------------------------


@ToolRegistry.register("paper_trade")
class PaperTradeTool(BaseTool):
    tool_id = "paper_trade"
    is_local = False  # fetches live prices

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="paper_trade",
            description=(
                "Execute a simulated (paper) buy or sell at the current market"
                " price. Uses virtual cash — no real money is involved."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "'buy' or 'sell'.",
                    },
                    "symbol": {"type": "string", "description": "Ticker symbol."},
                    "quantity": {"type": "number", "description": "Units to trade."},
                    "asset_type": {
                        "type": "string",
                        "description": "'stock' or 'crypto'. Default stock.",
                    },
                },
                "required": ["action", "symbol", "quantity"],
            },
            category="finance",
        )

    def execute(self, **params: Any) -> ToolResult:
        action = str(params.get("action", "")).strip().lower()
        symbol = str(params.get("symbol", "")).strip()
        if action not in ("buy", "sell"):
            return ToolResult(
                tool_name="paper_trade",
                content="action must be 'buy' or 'sell'.",
                success=False,
            )
        if not symbol:
            return ToolResult(
                tool_name="paper_trade", content="No symbol provided.", success=False
            )
        try:
            quantity = float(params.get("quantity"))
        except (TypeError, ValueError):
            return ToolResult(
                tool_name="paper_trade",
                content="quantity must be a number.",
                success=False,
            )
        asset_type = _norm_asset_type(params.get("asset_type"))

        try:
            price = prices.get_price(symbol, asset_type)
        except Exception as exc:
            return ToolResult(
                tool_name="paper_trade",
                content=f"Could not fetch price for {symbol}: {exc}",
                success=False,
            )

        try:
            trade = _store().execute_paper_trade(
                action, symbol, asset_type, quantity, price
            )
        except ValueError as exc:
            return ToolResult(
                tool_name="paper_trade", content=str(exc), success=False
            )

        cash = _store().get_cash()
        return ToolResult(
            tool_name="paper_trade",
            content=(
                f"Paper {trade.side.upper()} {trade.quantity} {trade.symbol}"
                f" @ {price:,.2f} = {trade.quantity * price:,.2f}."
                f" Cash balance: {cash:,.2f} USD."
            ),
            success=True,
            metadata={
                "side": trade.side,
                "symbol": trade.symbol,
                "price": price,
                "cash": cash,
            },
        )


@ToolRegistry.register("paper_account")
class PaperAccountTool(BaseTool):
    tool_id = "paper_account"
    is_local = False  # values positions at live prices

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="paper_account",
            description=(
                "Show the paper-trading account: cash, open positions valued at"
                " live prices, and total equity."
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            category="finance",
        )

    def execute(self, **params: Any) -> ToolResult:
        store = _store()
        cash = store.get_cash()
        positions = store.list_paper_positions()
        lines = ["Paper trading account:", f"  Cash: {cash:,.2f} USD"]
        equity = cash
        if positions:
            lines.append("  Positions:")
            for p in positions:
                try:
                    price = prices.get_price(p.symbol, p.asset_type)
                    value = price * p.quantity
                    equity += value
                    pl = (price - p.avg_price) * p.quantity
                    lines.append(
                        f"    {p.symbol} ({p.asset_type}): {p.quantity} @"
                        f" {price:,.2f} = {value:,.2f}  P/L {pl:+,.2f}"
                    )
                except Exception:
                    lines.append(
                        f"    {p.symbol} ({p.asset_type}): {p.quantity}"
                        f" @ avg {p.avg_price:,.2f} — live price n/a"
                    )
        else:
            lines.append("  No open positions.")
        lines.append(f"  Total equity: {equity:,.2f} USD")
        return ToolResult(
            tool_name="paper_account",
            content="\n".join(lines),
            success=True,
            metadata={"cash": cash, "equity": equity, "positions": len(positions)},
        )


__all__ = [
    "CryptoPriceTool",
    "StockQuoteTool",
    "TechnicalAnalysisTool",
    "PortfolioAddTool",
    "PortfolioViewTool",
    "PortfolioRemoveTool",
    "PaperTradeTool",
    "PaperAccountTool",
]
