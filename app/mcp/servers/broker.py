"""MCP server: a paper-trading broker (no real money, no external API).

Accounts start from data/accounts.json and live in their own ledger: a SQLite file on a laptop
(data/paper_broker.db), or Postgres (Neon) when DATABASE_URL is Postgres, so trades survive a
redeploy. Orders fill at the latest close in the price snapshot.

The broker is the last line of defence and trusts no agent:
* order limits are checked here (known tickers of the client's market, whole positive share
  counts, no short selling, no order above the configured share of the account, turnover cap);
* `execute_orders` needs a signed approval token (app.security.approvals) that matches the
  exact orders a person approved; each token works once, so a retry never trades twice.
"""

import json
import math
import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from app.config import get_settings
from app.data import store
from app.data.universe import BY_TICKER, MARKETS
from app.db.urls import is_postgres
from app.security.approvals import ApprovalError, verify

MAX_ORDERS = 40

_LOCK = threading.Lock()


def _db_path() -> Path:
    return Path(os.environ.get("PAPER_BROKER_DB", store.data_dir() / "paper_broker.db"))


SCHEMA = (
    "CREATE TABLE IF NOT EXISTS accounts (client_id TEXT PRIMARY KEY, cash DOUBLE PRECISION, "
    "positions TEXT, updated_at TEXT)",
    "CREATE TABLE IF NOT EXISTS executions (approval_id TEXT PRIMARY KEY, client_id TEXT, fills TEXT, "
    "executed_at TEXT, approved_by TEXT)",
)


class Ledger:
    """One connection, SQLite or Postgres; the SQL is written once with ? placeholders."""

    def __init__(self, raw: Any, postgres: bool) -> None:  # noqa: ANN401
        self.raw, self.postgres = raw, postgres

    def execute(self, sql: str, params: tuple = ()) -> Any:  # noqa: ANN401
        return self.raw.execute(sql.replace("?", "%s") if self.postgres else sql, params)

    def begin(self, client_id: str) -> None:
        """Serialise executions for one client (and one approval token) across processes."""
        if self.postgres:
            self.execute("BEGIN")
            self.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (client_id,))
        else:
            self.execute("BEGIN IMMEDIATE")


_SCHEMA_READY: set[str] = set()


@contextmanager
def _connect() -> Iterator[Ledger]:
    url = get_settings().database_url
    if is_postgres(url):
        from app.db.pg import pool

        with pool().connection() as raw:
            ledger = Ledger(raw, postgres=True)
            if url not in _SCHEMA_READY:
                for sql in SCHEMA:
                    ledger.execute(sql)
                _SCHEMA_READY.add(url)
            yield ledger
        return
    # autocommit mode: transactions are explicit (Ledger.begin), and the busy timeout lets a
    # second broker process (stdio transport) wait for the lock
    raw = sqlite3.connect(_db_path(), isolation_level=None, timeout=30)
    try:
        ledger = Ledger(raw, postgres=False)
        for sql in SCHEMA:
            ledger.execute(sql)
        yield ledger
    finally:
        raw.close()


def _load(conn: Ledger, client_id: str) -> tuple[float, dict[str, int]]:
    row = conn.execute("SELECT cash, positions FROM accounts WHERE client_id=?", (client_id,)).fetchone()
    if row:
        return float(row[0]), {k: int(v) for k, v in json.loads(row[1]).items()}
    try:
        seed = store.account(client_id)
    except KeyError as exc:
        raise ToolError(str(exc)) from exc
    cash, positions = float(seed["cash"]), dict(seed["positions"])
    _save(conn, client_id, cash, positions)
    return cash, positions


def _save(conn: Ledger, client_id: str, cash: float, positions: dict[str, int]) -> None:
    conn.execute("INSERT INTO accounts VALUES (?, ?, ?, ?) ON CONFLICT (client_id) DO UPDATE SET "
                 "cash = excluded.cash, positions = excluded.positions, updated_at = excluded.updated_at",
                 (client_id, cash, json.dumps({k: v for k, v in positions.items() if v}),
                  datetime.now(UTC).isoformat()))


def _snapshot(client_id: str, cash: float, positions: dict[str, int]) -> dict[str, Any]:
    market = store.market_of_client(client_id)
    frame = store.prices(market)
    prices = {t: float(frame[t].iloc[-1]) for t in positions}
    values = {t: positions[t] * prices[t] for t in positions}
    total = cash + sum(values.values())
    return {
        "client_id": client_id,
        "market": market,
        "currency": MARKETS[market].currency,
        "price_date": str(frame.index[-1].date()),
        "cash": round(cash, 2),
        "positions": positions,
        "prices": prices,
        "market_value": round(total, 2),
        "weights": {t: values[t] / total for t in positions},
        "cash_weight": cash / total if total else 0.0,
    }


async def get_account(client_id: str) -> dict[str, Any]:
    with _LOCK, _connect() as conn:
        cash, positions = _load(conn, client_id)
    return _snapshot(client_id, cash, positions)


def order_limits(client_id: str, trades: list[dict[str, Any]], positions: dict[str, int],
                 total: float) -> list[dict[str, Any]]:
    """Hard limits, independent of any model; every check is reported, pass or fail."""
    settings = get_settings()
    max_order, max_turnover = settings.max_order_fraction, settings.max_turnover
    market = store.market_of_client(client_id)
    unknown = sorted({t["ticker"] for t in trades
                      if t["ticker"] not in BY_TICKER or BY_TICKER[t["ticker"]].market != market})
    # order values from the broker's own prices, never from the caller
    frame = store.prices(market)
    trades = [{**t, "value": abs(int(t.get("shares") or 0)) * float(frame[t["ticker"]].iloc[-1])}
              for t in trades if t["ticker"] not in unknown]
    bad_size = [t["ticker"] for t in trades if not isinstance(t.get("shares"), int) or t["shares"] <= 0]
    short = [t["ticker"] for t in trades
             if t["side"] == "sell" and t["shares"] > positions.get(t["ticker"], 0)]
    biggest = max(trades, key=lambda t: t["value"], default=None)
    turnover = sum(t["value"] for t in trades) / total if total else 0.0
    size_detail = "no orders"
    if biggest is not None and total:
        size_detail = (f"largest order {biggest['ticker']} is {biggest['value'] / total:.0%} of the account; "
                       f"limit {max_order:.0%}")
    return [
        {"check": "known_tickers", "passed": not unknown,
         "detail": (f"not tradable for this client: {', '.join(unknown)}" if unknown
                    else f"every ticker is a {market} stock in the universe")},
        {"check": "whole_shares", "passed": not bad_size,
         "detail": f"invalid share counts: {', '.join(bad_size)}" if bad_size else "whole, positive share counts"},
        {"check": "no_short_selling", "passed": not short,
         "detail": f"sells more than held: {', '.join(short)}" if short else "no sell exceeds the position held"},
        {"check": "max_order_size",
         "passed": biggest is None or biggest["value"] <= max_order * total, "detail": size_detail},
        {"check": "max_turnover", "passed": turnover <= max_turnover,
         "detail": f"turnover {turnover:.0%}; limit {max_turnover:.0%}"},
        {"check": "max_orders", "passed": len(trades) <= MAX_ORDERS,
         "detail": f"{len(trades)} orders; limit {MAX_ORDERS}"},
    ]


async def preview_rebalance(client_id: str, target_weights: dict[str, float],
                            min_weight_change: float = 0.0) -> dict[str, Any]:
    if any(w < 0 for w in target_weights.values()):
        raise ToolError("weights must be non-negative")
    if abs(sum(target_weights.values()) - 1) > 1e-3:
        raise ToolError("target weights must sum to 1")
    market = store.market_of_client(client_id)
    unknown = sorted(t for t in target_weights if t not in BY_TICKER or BY_TICKER[t].market != market)
    if unknown:
        raise ToolError(f"not tradable for this client: {', '.join(unknown)}")
    with _LOCK, _connect() as conn:
        cash, positions = _load(conn, client_id)
    snap = _snapshot(client_id, cash, positions)
    frame = store.prices(snap["market"])
    total = snap["market_value"]
    trades = []
    for ticker in sorted(set(positions) | set(target_weights)):
        price = float(frame[ticker].iloc[-1])
        before = snap["weights"].get(ticker, 0.0)
        after = target_weights.get(ticker, 0.0)
        if abs(after - before) < min_weight_change and after > 0 and before > 0:
            continue  # mandate: skip trades that change a weight only a little
        target_shares = math.floor(after * total / price)
        delta = target_shares - positions.get(ticker, 0)
        if delta == 0:
            continue
        trades.append({
            "ticker": ticker, "side": "buy" if delta > 0 else "sell", "shares": abs(delta),
            "price": price, "value": round(abs(delta) * price, 2),
            "weight_before": round(before, 6), "weight_after": round(after, 6),
        })
    net = sum(t["value"] if t["side"] == "sell" else -t["value"] for t in trades)
    limits = order_limits(client_id, trades, positions, total)
    return {"client_id": client_id, "price_date": snap["price_date"], "trades": trades,
            "turnover": round(sum(t["value"] for t in trades) / total, 6) if total else 0.0,
            "cash_after": round(cash + net, 2), "account_value": total, "limits": limits,
            "allowed": all(c["passed"] for c in limits)}


async def execute_orders(client_id: str, trades: list[dict[str, Any]], approval_token: str) -> dict[str, Any]:
    try:
        claims = verify(approval_token, client_id, trades)
    except ApprovalError as exc:
        raise ToolError(f"refused: {exc}") from exc
    token_id, approved_by = claims["jti"], claims["reviewer"]
    with _LOCK, _connect() as conn:
        # one transaction for the replay check, the account update and the execution record,
        # so a crash cannot apply the trades and leave the token reusable (and two broker
        # processes cannot both execute the same approval)
        conn.begin(client_id)
        try:
            result = _execute_locked(conn, client_id, trades, token_id, approved_by)
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
        return result


def _execute_locked(conn: Ledger, client_id: str, trades: list[dict[str, Any]], token_id: str,
                    approved_by: str) -> dict[str, Any]:
    """Inside the caller's transaction: replay check, limits, fills, account, record."""
    done = conn.execute("SELECT fills FROM executions WHERE approval_id=?", (token_id,)).fetchone()
    if done:
        return {"client_id": client_id, "approval_id": token_id, "approved_by": approved_by,
                "fills": json.loads(done[0]), "replayed": True,
                "account": _snapshot(client_id, *_load(conn, client_id))}
    cash, positions = _load(conn, client_id)
    total = _snapshot(client_id, cash, positions)["market_value"]
    failed = [c["detail"] for c in order_limits(client_id, trades, positions, total) if not c["passed"]]
    if failed:
        raise ToolError("refused: " + "; ".join(failed))
    frame = store.prices(store.market_of_client(client_id))
    fills = []
    # sells first, so their cash funds the buys
    for trade in sorted(trades, key=lambda t: t["side"] != "sell"):
        ticker, shares = trade["ticker"], int(trade["shares"])
        price = float(frame[ticker].iloc[-1])
        if trade["side"] == "sell":
            shares = min(shares, positions.get(ticker, 0))
            positions[ticker] = positions.get(ticker, 0) - shares
            cash += shares * price
        else:
            shares = min(shares, int(cash // price))
            positions[ticker] = positions.get(ticker, 0) + shares
            cash -= shares * price
        if shares:
            fills.append({"ticker": ticker, "side": trade["side"], "shares": shares,
                          "price": price, "value": round(shares * price, 2)})
    positions = {t: s for t, s in positions.items() if s > 0}
    _save(conn, client_id, cash, positions)
    conn.execute("INSERT INTO executions VALUES (?, ?, ?, ?, ?)",
                 (token_id, client_id, json.dumps(fills), datetime.now(UTC).isoformat(), approved_by))
    return {"client_id": client_id, "approval_id": token_id, "approved_by": approved_by, "fills": fills,
            "replayed": False, "account": _snapshot(client_id, cash, positions)}


def reset_account(client_id: str) -> None:
    """Restore the seed account (used by the API's demo reset, not exposed as a tool)."""
    seed = store.account(client_id)
    with _LOCK, _connect() as conn:
        _save(conn, client_id, float(seed["cash"]), dict(seed["positions"]))


def forget_account(client_id: str) -> None:
    """Drop a removed client's paper ledger (the execution history is kept for the audit)."""
    with _LOCK, _connect() as conn:
        conn.execute("DELETE FROM accounts WHERE client_id=?", (client_id,))


def build_server() -> MCPServer:
    server = MCPServer("quantfolio-paper-broker",
                       instructions="Paper trading only. Trades require a signed human approval token.")
    server.tool(description="Cash, positions, weights and value of a client's paper account.")(get_account)
    server.tool(description="Whole-share trades that move the account to target weights, with the "
                "broker's order-limit checks.")(preview_rebalance)
    server.tool(description="Execute approved paper trades (needs the signed approval token for exactly "
                "these orders; single use).")(execute_orders)
    return server


if __name__ == "__main__":
    build_server().run()
