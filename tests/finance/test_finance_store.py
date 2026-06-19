"""Tests for the finance SQLite store (in-memory)."""

from __future__ import annotations

import pytest

from openjarvis.finance.store import DEFAULT_STARTING_CASH, FinanceStore


@pytest.fixture()
def store():
    s = FinanceStore(":memory:")
    yield s
    s.close()


def test_add_and_list_holdings(store):
    store.add_holding("AAPL", "stock", 10, 150.0)
    store.add_holding("btc", "crypto", 0.5, 40000.0)
    holdings = store.list_holdings()
    assert len(holdings) == 2
    symbols = {h.symbol for h in holdings}
    assert symbols == {"AAPL", "BTC"}


def test_add_holding_upserts(store):
    store.add_holding("AAPL", "stock", 10, 150.0)
    store.add_holding("AAPL", "stock", 20, 160.0)
    holdings = store.list_holdings()
    assert len(holdings) == 1
    assert holdings[0].quantity == 20
    assert holdings[0].cost_basis == 160.0


def test_remove_holding(store):
    store.add_holding("AAPL", "stock", 10, 150.0)
    removed = store.remove_holding("AAPL")
    assert removed == 1
    assert store.list_holdings() == []


def test_ensure_account_default_cash(store):
    assert store.ensure_account() == DEFAULT_STARTING_CASH
    # Idempotent — second call does not reset.
    assert store.get_cash() == DEFAULT_STARTING_CASH


def test_paper_buy_then_sell(store):
    store.ensure_account(10_000.0)
    store.execute_paper_trade("buy", "AAPL", "stock", 10, 100.0)
    assert store.get_cash() == pytest.approx(9_000.0)
    positions = store.list_paper_positions()
    assert len(positions) == 1
    assert positions[0].quantity == 10
    assert positions[0].avg_price == pytest.approx(100.0)

    store.execute_paper_trade("sell", "AAPL", "stock", 5, 120.0)
    assert store.get_cash() == pytest.approx(9_600.0)
    assert store.list_paper_positions()[0].quantity == 5


def test_paper_avg_price_updates_on_additional_buy(store):
    store.ensure_account(10_000.0)
    store.execute_paper_trade("buy", "AAPL", "stock", 10, 100.0)
    store.execute_paper_trade("buy", "AAPL", "stock", 10, 200.0)
    pos = store.list_paper_positions()[0]
    assert pos.quantity == 20
    assert pos.avg_price == pytest.approx(150.0)


def test_paper_insufficient_cash(store):
    store.ensure_account(100.0)
    with pytest.raises(ValueError, match="Insufficient cash"):
        store.execute_paper_trade("buy", "AAPL", "stock", 10, 100.0)


def test_paper_insufficient_position(store):
    store.ensure_account(10_000.0)
    store.execute_paper_trade("buy", "AAPL", "stock", 1, 100.0)
    with pytest.raises(ValueError, match="Insufficient position"):
        store.execute_paper_trade("sell", "AAPL", "stock", 5, 100.0)


def test_paper_trades_recorded(store):
    store.ensure_account(10_000.0)
    store.execute_paper_trade("buy", "AAPL", "stock", 1, 100.0)
    trades = store.list_paper_trades()
    assert len(trades) == 1
    assert trades[0].side == "buy"
    assert trades[0].symbol == "AAPL"
