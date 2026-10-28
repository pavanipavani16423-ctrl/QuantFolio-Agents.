"""Clients the advisor adds in the UI.

The form's answers are written up as an investment policy statement in the same layout as the
built-in ones (data/corpus/mandates/), so nothing downstream is special-cased: the compliance
agent retrieves the new policy with hybrid RAG and extracts its rules with citations, exactly as
for the demo clients. Stored in settings.clients_dir (git-ignored: accounts.json plus one
<client_id>.md policy per client), or in Postgres (Neon) when DATABASE_URL is Postgres, so the
clients survive a redeploy.

What the advisor types is untrusted input that agents will later read: it is PII-redacted and
screened for hidden instructions before it is written into the document. The form's limits come
first in the document, so a number in the free-text notes can never loosen them (the compliance
agent also keeps the stricter value when two readings disagree).
"""

import json
import os
import threading
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.config import get_settings
from app.data.universe import BY_TICKER, MARKETS, SECTORS, universe
from app.db.urls import is_postgres

GOALS = {
    "income": ("Conservative Income", "stable income and preservation of capital, with modest growth"),
    "balanced": ("Balanced Growth", "a balance of long-term growth and stability"),
    "growth": ("Growth", "long-term capital growth ahead of inflation"),
    "esg": ("ESG Growth", "long-term growth from companies with responsible environmental and social practices"),
}
RISK = {
    "low": (6, "weight risk heavily"),
    "medium": (4, "use a balanced weight on risk"),
    "high": (2, "use a light weight on risk"),
}
CURRENCY_WORDS = {"US": "US dollars", "IN": "Indian rupees"}
FIRST_ID = 301

CACHE_SECONDS = 10  # Postgres reads are cached briefly; this process's own writes clear it

_LOCK = threading.Lock()
_CACHE: dict = {"key": None, "data": {"accounts": {}, "policies": {}}}


class ClientError(ValueError):
    """The form cannot become a client; the message is shown to the advisor as is."""


class NewClient(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    who: str = Field("", max_length=60, description="One line, e.g. 'Retired couple, Chennai'")
    market: Literal["US", "IN"] = "US"
    goal: Literal["income", "balanced", "growth", "esg"] = "balanced"
    risk: Literal["low", "medium", "high"] = "medium"
    horizon_years: int = Field(7, ge=1, le=40)
    holdings: int = Field(8, ge=3, le=15)
    max_weight: float = Field(0.20, ge=0.05, le=0.5)
    min_weight: float = Field(0.04, ge=0.01, le=0.2)  # > 0: the policy always states a minimum
    max_sector_weight: float = Field(0.40, ge=0.1, le=1.0)
    max_volatility: float = Field(0.22, ge=0.05, le=0.6)
    excluded_sectors: list[str] = Field(default_factory=list, max_length=11)
    excluded_tickers: list[str] = Field(default_factory=list, max_length=20)
    cash: float = Field(0.0, ge=0, le=1e11)
    positions: dict[str, int] = Field(default_factory=dict, max_length=20)
    notes: str = Field("", max_length=600)


# ---- storage ------------------------------------------------------------------------------
Make = Callable[[str], tuple[dict, str]]  # client id -> (account, policy text)


class FileStore:
    """accounts.json plus one policy file per client; re-read when the file changes."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.path = folder / "accounts.json"

    def _raw(self) -> dict:
        return json.loads(self.path.read_text("utf-8")) if self.path.exists() else {"next_id": FIRST_ID, "accounts": {}}

    def version(self) -> object:
        return self.path.stat().st_mtime_ns if self.path.exists() else None

    def load(self) -> dict:
        accounts = self._raw()["accounts"]
        policies = {cid: (self.folder / f"{cid}.md").read_text("utf-8")
                    for cid in accounts if (self.folder / f"{cid}.md").exists()}
        return {"accounts": accounts, "policies": policies}

    def _write(self, state: dict) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = self.folder / "accounts.json.tmp"
        tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), "utf-8")
        os.replace(tmp, self.path)

    def add(self, make: Make) -> dict:
        state = self._raw()
        client_id = f"C-{state['next_id']}"
        account, policy = make(client_id)
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / f"{client_id}.md").write_text(policy, "utf-8")
        state["accounts"][client_id] = account
        state["next_id"] += 1
        self._write(state)
        return account

    def remove(self, client_id: str) -> None:
        state = self._raw()
        if client_id not in state["accounts"]:
            raise KeyError(f"unknown added client {client_id!r}")
        del state["accounts"][client_id]
        self._write(state)
        (self.folder / f"{client_id}.md").unlink(missing_ok=True)


class PostgresStore:
    """One row per client; removed clients keep their row (flagged), so ids are never reused."""

    SCHEMA = ("CREATE TABLE IF NOT EXISTS added_clients (client_id TEXT PRIMARY KEY, seq INTEGER UNIQUE, "
              "account TEXT NOT NULL, policy TEXT NOT NULL, removed BOOLEAN NOT NULL DEFAULT FALSE, "
              "created_at TEXT NOT NULL)")

    def __init__(self) -> None:
        from app.db.pg import pool

        self.pool = pool()
        with self.pool.connection() as conn:
            conn.execute(self.SCHEMA)

    def version(self) -> object:
        return int(time.monotonic() // CACHE_SECONDS)

    def load(self) -> dict:
        with self.pool.connection() as conn:
            rows = conn.execute("SELECT client_id, account, policy FROM added_clients WHERE NOT removed "
                                "ORDER BY seq").fetchall()
        return {"accounts": {r[0]: json.loads(r[1]) for r in rows}, "policies": {r[0]: r[2] for r in rows}}

    def add(self, make: Make) -> dict:
        with self.pool.connection() as conn, conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtext('added_clients'))")
            seq = conn.execute("SELECT COALESCE(MAX(seq) + 1, %s) FROM added_clients", (FIRST_ID,)).fetchone()[0]
            account, policy = make(f"C-{seq}")
            conn.execute("INSERT INTO added_clients VALUES (%s, %s, %s, %s, FALSE, %s)",
                         (f"C-{seq}", seq, json.dumps(account, ensure_ascii=False), policy,
                          datetime.now(UTC).isoformat()))
        return account

    def remove(self, client_id: str) -> None:
        with self.pool.connection() as conn:
            done = conn.execute("UPDATE added_clients SET removed = TRUE WHERE client_id = %s AND NOT removed",
                                (client_id,)).rowcount
        if not done:
            raise KeyError(f"unknown added client {client_id!r}")


_STORES: dict[str, FileStore | PostgresStore] = {}


def _store() -> FileStore | PostgresStore:
    s = get_settings()
    key = s.database_url if is_postgres(s.database_url) else str(s.clients_dir)
    if key not in _STORES:
        _STORES[key] = PostgresStore() if is_postgres(s.database_url) else FileStore(Path(s.clients_dir))
    return _STORES[key]


def _state() -> dict:
    store = _store()
    key = (id(store), store.version())
    if _CACHE["key"] != key:
        _CACHE.update(key=key, data=store.load())
    return _CACHE["data"]


def accounts() -> dict[str, dict]:
    return _state()["accounts"]


def is_custom(client_id: str) -> bool:
    return client_id in accounts()


def mandate_texts() -> dict[str, str]:
    return dict(_state()["policies"])


# ---- validation ---------------------------------------------------------------------------
def _pct(value: float) -> str:
    return f"{round(value * 100, 1):g}%"


def normalized(c: NewClient) -> NewClient:
    return c.model_copy(update={
        "name": " ".join(c.name.split()),
        "who": " ".join(c.who.split()),
        "excluded_tickers": sorted({t.strip().upper() for t in c.excluded_tickers}),
        "excluded_sectors": sorted(set(c.excluded_sectors)),
        "positions": {t.strip().upper(): int(n) for t, n in c.positions.items() if int(n) > 0},
        "notes": c.notes.strip(),
    })


def problems(c: NewClient) -> list[str]:
    """Plain-language reasons the rules cannot work; empty when the client can be created."""
    from app.data import store

    c = normalized(c)
    out = []
    market_tickers = {a.ticker for a in universe(c.market)}
    wrong = [t for t in [*c.positions, *c.excluded_tickers] if t not in market_tickers]
    if wrong:
        out.append(f"Not in the {MARKETS[c.market].name} list of companies: {', '.join(sorted(set(wrong)))}.")
    bad_sectors = [s for s in c.excluded_sectors if s not in SECTORS]
    if bad_sectors:
        out.append(f"Unknown sector: {', '.join(bad_sectors)}.")
    if any(n > 100_000_000 for n in c.positions.values()):
        out.append("A holding has more than 100 million shares; check the numbers.")
    if not wrong:
        prices = store.prices(c.market).iloc[-1]
        value = c.cash + sum(n * float(prices[t]) for t, n in c.positions.items())
        if value <= 0:
            out.append("Add some cash or at least one current holding, so there is money to invest.")
    eligible = [a for a in universe(c.market)
                if a.ticker not in c.excluded_tickers and a.sector not in c.excluded_sectors]
    if len(eligible) < c.holdings:
        out.append(f"After the exclusions only {len(eligible)} companies are left, but the client must hold "
                   f"{c.holdings}. Exclude less or choose fewer stocks.")
    if c.min_weight >= c.max_weight:
        out.append("The smallest share per stock must be below the largest.")
    if c.holdings * c.max_weight < 1 - 1e-9:
        out.append(f"{c.holdings} stocks of at most {_pct(c.max_weight)} each cannot add up to 100%. "
                   "Raise the maximum per stock or the number of stocks.")
    if c.holdings * c.min_weight > 1 + 1e-9:
        out.append(f"{c.holdings} stocks of at least {_pct(c.min_weight)} each add up to more than 100%.")
    by_sector: dict[str, int] = {}
    for a in eligible:
        by_sector[a.sector] = by_sector.get(a.sector, 0) + 1
    capacity = sum(min(c.max_sector_weight, min(n, c.holdings) * c.max_weight) for n in by_sector.values())
    if eligible and capacity < 1 - 1e-9:
        out.append(f"The sector limit of {_pct(c.max_sector_weight)} is too tight for the companies left. "
                   "Raise it or exclude fewer sectors.")
    return out


def screen(c: NewClient) -> tuple[NewClient, dict[str, int]]:
    """Remove personal data and refuse text that reads like an instruction to the AI."""
    from app.guardrails.injection import scan
    from app.guardrails.input import semantic_check
    from app.guardrails.pii import redact

    s = get_settings()
    removed: dict[str, int] = {}
    clean = {}
    for field in ("name", "who", "notes"):
        text, counts = redact(getattr(c, field))
        for k, v in counts.items():
            removed[k] = removed.get(k, 0) + v
        if text and (scan(text).is_attack(s.injection_block_threshold)
                     or semantic_check(text, s.semantic_injection_threshold)[0]):
            raise ClientError(f"The {field} reads like an instruction to the AI, so it was not saved. "
                              "Describe the client in plain words.")
        clean[field] = text
    return c.model_copy(update=clean), removed


# ---- the policy document ------------------------------------------------------------------
def render_policy(c: NewClient, client_id: str = "new client") -> str:
    """The investment policy statement, in the phrasing the compliance agent's patterns read."""
    c = normalized(c)
    m = MARKETS[c.market]
    profile, goal = GOALS[c.goal]
    coefficient, weighting = RISK[c.risk]
    label = f" (client {client_id})" if client_id.startswith("C-") else ""
    who = f" ({c.who})" if c.who else ""
    sectors = ", ".join(c.excluded_sectors) or "none"
    companies = ", ".join(c.excluded_tickers) or "none"
    full_names = "; ".join(BY_TICKER[t].name.rstrip(".") for t in c.excluded_tickers if t in BY_TICKER)
    lines = [
        f"# Investment Policy Statement - {c.name}{label} - {profile}",
        "",
        f"Written from the advisor's answers in the QuantFolio-Agents client form on {date.today().isoformat()}.",
        "",
        "## Section 1. Purpose",
        "",
        f"1.1 This Investment Policy Statement (IPS) governs the listed equity portfolio of {c.name}{who}.",
        "",
        "## Section 2. Investment objectives",
        "",
        f"2.1 The objective is {goal} over a horizon of at least {c.horizon_years} years.",
        "",
        f"2.2 Risk tolerance: {c.risk}.",
        "",
        f"2.3 Risk aversion: the manager shall {weighting} when choosing between portfolios (risk aversion "
        f"coefficient {coefficient} on the scale used by the firm's optimizer, where higher means more risk averse).",
        "",
        "## Section 3. Portfolio construction",
        "",
        f"3.1 Number of holdings: the portfolio shall hold exactly {c.holdings} stocks.",
        "",
        f"3.2 Position limits: no single holding may exceed {_pct(c.max_weight)} of the portfolio, and every "
        f"holding must be at least {_pct(c.min_weight)} of the portfolio.",
        "",
        f"3.3 Sector limits: no sector may exceed {_pct(c.max_sector_weight)} of the portfolio.",
        "",
        f"3.4 Volatility limit: the expected annualised volatility of the portfolio must not exceed "
        f"{_pct(c.max_volatility)}.",
        "",
        f"3.5 Universe: only equity shares listed on the {m.exchange} in {CURRENCY_WORDS[c.market]}. "
        "No derivatives, no borrowing.",
        "",
        "## Section 4. Exclusions",
        "",
        f"4.1 Excluded sectors: {sectors}.",
        "",
        f"4.2 Excluded companies: {companies}." + (f" In full: {full_names}." if full_names else ""),
        "",
    ]
    if c.notes:
        lines += ["## Section 5. Advisor notes", "", f"5.1 {c.notes}", ""]
    lines += [
        "## Section 6. Rebalancing and review",
        "",
        "6.1 The portfolio is reviewed every quarter.",
        "",
        "6.2 Every proposed rebalance must be approved by the advisor before any order is placed.",
        "",
        "## Section 7. Reporting",
        "",
        "7.1 Reports must show each holding, its weight, and the risks found in the companies' own reports.",
        "",
    ]
    return "\n".join(lines)


def rules_summary(c: NewClient) -> str:
    excluded = [*c.excluded_sectors, *(BY_TICKER[t].name.split()[0].rstrip(",.") for t in c.excluded_tickers)]
    head = f"No {', '.join(excluded)}" if excluded else f"{c.risk.capitalize()} risk"
    return f"{head} · {c.holdings} stocks · max {_pct(c.max_weight)} each"


# ---- create / remove ----------------------------------------------------------------------
def create(form: NewClient) -> tuple[dict, dict[str, int]]:
    """Validate, screen and store a new client; returns the account and the personal data removed."""
    form = normalized(form)
    found = problems(form)
    if found:
        raise ClientError(" ".join(found))
    form, removed = screen(form)

    def make(client_id: str) -> tuple[dict, str]:
        account = {
            "client_id": client_id, "name": form.name, "profile": GOALS[form.goal][0],
            "mandate_doc": f"mandate_{client_id}", "market": form.market, "cash": form.cash,
            "positions": form.positions, "as_of": date.today().isoformat(),
            "note": "Added by the advisor in the client form.", "custom": True,
            "who": form.who or GOALS[form.goal][0], "rules_summary": rules_summary(form),
            "form": form.model_dump(),
        }
        return account, render_policy(form, client_id)

    with _LOCK:
        account = _store().add(make)
        _CACHE["key"] = None
    return account, removed


def remove(client_id: str) -> None:
    # ids are never reused, so old runs and audit entries stay unambiguous
    with _LOCK:
        _store().remove(client_id)
        _CACHE["key"] = None


def example_requests(account: dict) -> list[str]:
    """Two starter requests that name companies the intake agent recognises."""
    from app.agents.intake import ALIASES
    from app.data import store

    positions = account.get("positions") or {}
    prices = store.prices(account["market"]).iloc[-1]
    held = sorted(positions, key=lambda t: -positions[t] * float(prices[t]))
    pool = held + [a.ticker for a in universe(account["market"]) if a.ticker not in held]
    form = account.get("form") or {}
    excluded = set(form.get("excluded_tickers", []))
    sectors = set(form.get("excluded_sectors", []))
    names = [ALIASES.get(t, [BY_TICKER[t].name])[0] for t in pool
             if t not in excluded and BY_TICKER[t].sector not in sectors][:3]
    return [
        f"Rebalance the portfolio. What are the main risks for {names[0]} and {names[1]}?",
        f"Rebalance the portfolio. Is {names[2]}'s business stable?",
    ]

