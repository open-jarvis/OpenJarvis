"""Tests for finance agent tools (prices mocked, in-memory store)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

import openjarvis.tools.finance_tools as ft
from openjarvis.finance.store import FinanceStore
from openjarvis.tools.finance_tools import (
    CryptoPriceTool,
    PaperAccountTool,
    PaperTradeTool,
    PortfolioAddTool,
    PortfolioRemoveTool,
    PortfolioViewTool,
    StockQuoteTool,
    TechnicalAnalysisTool,
)


@pytest.fixture()
def mem_store():
    """Point the finance tools' shared store at an in-memory DB."""
    store = FinanceStore(":memory:")
    prev = ft._STORE
    ft._STORE = store
    yield store
    ft._STORE = prev
    store.close()


# ---------------------------------------------------------------------------
# Quotes
# ---------------------------------------------------------------------------


def test_crypto_price():
    with patch.object(
        ft.prices,
        "get_crypto_price",
        return_value={
            "symbol": "BTC",
            "id": "bitcoin",
            "price": 65000.0,
            "currency": "USD",
            "change_24h": 2.5,
            "source": "coingecko",
        },
    ):
        result = CryptoPriceTool().execute(symbol="btc")
    assert result.success is True
    assert "BTC" in result.content
    assert "65,000" in result.content
    assert "+2.50% 24h" in result.content


def test_crypto_price_no_symbol():
    result = CryptoPriceTool().execute(symbol="")
    assert result.success is False


def test_stock_quote():
    with patch.object(
        ft.prices,
        "get_stock_quote",
        return_value={
            "symbol": "AAPL",
            "price": 201.5,
            "open": 200.0,
            "high": 202.0,
            "low": 199.0,
            "volume": 1000000.0,
            "date": "2026-06-05",
            "source": "stooq",
        },
    ):
        result = StockQuoteTool().execute(symbol="aapl")
    assert result.success is True
    assert "AAPL" in result.content
    assert "201.50" in result.content


# ---------------------------------------------------------------------------
# Technical analysis
# ---------------------------------------------------------------------------


def test_technical_analysis_uptrend():
    series = [float(i) for i in range(1, 80)]
    with patch.object(ft.prices, "get_series", return_value=series):
        result = TechnicalAnalysisTool().execute(symbol="AAPL", asset_type="stock")
    assert result.success is True
    assert "BULLISH" in result.content
    assert result.metadata["bias"] == "bullish"


def test_technical_analysis_price_error():
    with patch.object(ft.prices, "get_series", side_effect=RuntimeError("boom")):
        result = TechnicalAnalysisTool().execute(symbol="AAPL")
    assert result.success is False


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------


def test_portfolio_add_view_remove(mem_store):
    add = PortfolioAddTool().execute(
        symbol="AAPL", quantity=10, asset_type="stock", cost_basis=150.0
    )
    assert add.success is True

    with patch.object(ft.prices, "get_price", return_value=180.0):
        view = PortfolioViewTool().execute()
    assert view.success is True
    assert "AAPL" in view.content
    assert "P/L" in view.content
    assert view.metadata["total_value"] == pytest.approx(1800.0)

    rem = PortfolioRemoveTool().execute(symbol="AAPL")
    assert rem.success is True
    assert rem.metadata["removed"] == 1


def test_portfolio_view_empty(mem_store):
    result = PortfolioViewTool().execute()
    assert result.success is True
    assert result.metadata["count"] == 0


def test_portfolio_add_bad_quantity(mem_store):
    result = PortfolioAddTool().execute(symbol="AAPL", quantity="notanumber")
    assert result.success is False


# ---------------------------------------------------------------------------
# Paper trading
# ---------------------------------------------------------------------------


def test_paper_trade_buy_and_account(mem_store):
    mem_store.ensure_account(10_000.0)
    with patch.object(ft.prices, "get_price", return_value=100.0):
        buy = PaperTradeTool().execute(
            action="buy", symbol="AAPL", quantity=10, asset_type="stock"
        )
    assert buy.success is True
    assert mem_store.get_cash() == pytest.approx(9_000.0)

    with patch.object(ft.prices, "get_price", return_value=120.0):
        acct = PaperAccountTool().execute()
    assert acct.success is True
    assert "AAPL" in acct.content
    # equity = 9000 cash + 10 * 120 = 10200
    assert acct.metadata["equity"] == pytest.approx(10_200.0)


def test_paper_trade_insufficient_cash(mem_store):
    mem_store.ensure_account(100.0)
    with patch.object(ft.prices, "get_price", return_value=100.0):
        result = PaperTradeTool().execute(
            action="buy", symbol="AAPL", quantity=10
        )
    assert result.success is False
    assert "Insufficient cash" in result.content


def test_paper_trade_bad_action(mem_store):
    result = PaperTradeTool().execute(action="hodl", symbol="AAPL", quantity=1)
    assert result.success is False
