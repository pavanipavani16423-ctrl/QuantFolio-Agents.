"""MCP server: a paper-trading broker (no real money, no external API).

Accounts start from data/accounts.json and live in their own SQLite ledger
(data/paper_broker.db). Orders fill at the latest close in the price snapshot.

Permission boundary: `execute_orders` refuses to trade without an approval id, and each
approval id can be used once, so a retried or replayed request never trades twice.
"""

import json
import math
import os
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from app.data import store

_LOCK = threading.Lock()


def _db_path() -> Path:
    return Path(os.environ.get("PAPER_BROKER_DB", store.data_dir() / "paper_broker.db"))


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.execute("CREATE TABLE IF NOT EXISTS accounts (client_id TEXT PRIMARY KEY, cash REAL, "
                 "positions TEXT, updated_at TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS executions (approval_id TEXT PRIMARY KEY, "
                 "client_id TEXT, fills TEXT, executed_at TEXT, approved_by TEXT)")
    return conn


def _load(conn: sqlite3.Connection, client_id: str) -> tuple[float, dict[str, int]]:
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


def _save(conn: sqlite3.Connection, client_id: str, cash: float, positions: dict[str, int]) -> None:
    conn.execute("INSERT OR REPLACE INTO accounts VALUES (?, ?, ?, ?)",
                 (client_id, cash, json.dumps({k: v for k, v in positions.items() if v}),
                  datetime.now(UTC).isoformat()))
    conn.commit()


def _snapshot(client_id: str, cash: float, positions: dict[str, int]) -> dict[str, Any]:
    frame = store.prices()
    prices = {t: float(frame[t].iloc[-1]) for t in positions}
    values = {t: positions[t] * prices[t] for t in positions}
    total = cash + sum(values.values())
    return {
        "client_id": client_id,
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


async def preview_rebalance(client_id: str, target_weights: dict[str, float],
                            min_weight_change: float = 0.0) -> dict[str, Any]:
    if any(w < 0 for w in target_weights.values()):
        raise ToolError("weights must be non-negative")
    if abs(sum(target_weights.values()) - 1) > 1e-3:
        raise ToolError("target weights must sum to 1")
    with _LOCK, _connect() as conn:
        cash, positions = _load(conn, client_id)
    snap = _snapshot(client_id, cash, positions)
    frame = store.prices()
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
    return {"client_id": client_id, "price_date": snap["price_date"], "trades": trades,
            "turnover": round(sum(t["value"] for t in trades) / total, 6) if total else 0.0,
            "cash_after": round(cash + net, 2), "account_value": total}


async def execute_orders(client_id: str, trades: list[dict[str, Any]], approval_id: str,
                         approved_by: str) -> dict[str, Any]:
    if not approval_id.strip() or not approved_by.strip():
        raise ToolError("orders need a human approval (approval_id and approved_by)")
    with _LOCK, _connect() as conn:
        done = conn.execute("SELECT fills FROM executions WHERE approval_id=?", (approval_id,)).fetchone()
        if done:
            return {"client_id": client_id, "approval_id": approval_id, "fills": json.loads(done[0]),
                    "replayed": True, "account": _snapshot(client_id, *_load(conn, client_id))}
        cash, positions = _load(conn, client_id)
        frame = store.prices()
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
                     (approval_id, client_id, json.dumps(fills), datetime.now(UTC).isoformat(),
                      approved_by))
        conn.commit()
    return {"client_id": client_id, "approval_id": approval_id, "fills": fills, "replayed": False,
            "account": _snapshot(client_id, cash, positions)}


def reset_account(client_id: str) -> None:
    """Restore the seed account (used by the API's demo reset, not exposed as a tool)."""
    seed = store.account(client_id)
    with _LOCK, _connect() as conn:
        _save(conn, client_id, float(seed["cash"]), dict(seed["positions"]))


def build_server() -> MCPServer:
    server = MCPServer("quantfolio-paper-broker",
                       instructions="Paper trading only. Trades require a human approval id.")
    server.tool(description="Cash, positions, weights and value of a client's paper account.")(get_account)
    server.tool(description="Whole-share trades that move the account to target weights.")(preview_rebalance)
    server.tool(description="Execute approved paper trades (needs approval_id; idempotent).")(execute_orders)
    return server


if __name__ == "__main__":
    build_server().run()
