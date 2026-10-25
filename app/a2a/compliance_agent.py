"""Compliance agent - a separate A2A service ("owned by the compliance team").

Skills
* extract-mandate-rules: retrieve the client's investment policy statement with hybrid RAG
  and turn it into machine-checkable rules, each with the chunk it came from. Uses the LLM
  (structured output) when configured, otherwise deterministic patterns. Either way the
  numbers are sanity-checked, so a misread rule cannot silently loosen a limit.
* check-portfolio: check a proposed portfolio against those rules, rule by rule.
"""

import re
from typing import Any

from a2a.types import AgentSkill

from app.a2a.common import SkillContext, SkillExecutor, agent_card
from app.config import get_settings
from app.data.universe import BY_TICKER, SECTORS
from app.llm.gateway import LLMGateway
from app.mcp.hub import MCPHub
from app.schemas import ComplianceReport, MandateRules, RuleCheck, RuleCitation

NAME = "compliance-agent"

RULE_QUERIES = {
    "holdings": "number of holdings the portfolio shall hold exactly",
    "position_limits": "position limits single holding maximum minimum weight",
    "sector_limits": "sector limits no sector may exceed",
    "volatility": "volatility limit expected annualised volatility must not exceed",
    "exclusions": "excluded sectors excluded companies exclusions",
    "risk_aversion": "risk aversion coefficient risk tolerance",
    "approval": "rebalance must be approved before any order is placed",
}

SYSTEM = (
    "You are a compliance officer. Extract the investment rules from the policy excerpts. "
    "Use fractions for percentages (15% -> 0.15). Use the exact GICS sector names from this "
    f"list for excluded_sectors: {', '.join(SECTORS)}. Use tickers for excluded_tickers. "
    "For every rule add a citation with the chunk id it came from and a short exact quote. "
    "If the document says 'none', return an empty list."
)


def _pct(pattern: str, text: str) -> float | None:
    m = re.search(pattern, text, flags=re.I | re.S)
    return float(m.group(1)) / 100 if m else None


def _cite(rule: str, pattern: str, chunks: list[dict]) -> RuleCitation | None:
    for c in chunks:
        m = re.search(pattern, c["text"], flags=re.I | re.S)
        if m:
            start = c["text"].rfind("\n", 0, m.start()) + 1
            end = c["text"].find("\n", m.end())
            quote = c["text"][start: end if end != -1 else None].strip()
            return RuleCitation(rule=rule, chunk_id=c["chunk_id"], quote=quote[:300])
    return None


PATTERNS = {
    "holdings": r"hold exactly (\d+) stocks",
    "max_weight": r"no single holding may exceed (\d+(?:\.\d+)?)%",
    "min_weight": r"at least (\d+(?:\.\d+)?)% of the portfolio",
    "max_sector_weight": r"no sector may exceed (\d+(?:\.\d+)?)%",
    "max_volatility": r"volatility of the portfolio must not exceed (\d+(?:\.\d+)?)%",
    "risk_aversion": r"risk aversion coefficient (\d+(?:\.\d+)?)",
    "excluded_sectors": r"Excluded sectors: ([^.\n]+)",
    "excluded_tickers": r"Excluded companies: ([^.\n]+)",
    "approval_required": r"must be approved",
}


def rules_from_text(client_id: str, chunks: list[dict]) -> MandateRules:
    """Deterministic extraction (used without an LLM, and to sanity-check the LLM)."""
    text = "\n".join(c["text"] for c in chunks)
    holdings = re.search(PATTERNS["holdings"], text, flags=re.I)
    ra = re.search(PATTERNS["risk_aversion"], text, flags=re.I)
    sec = re.search(PATTERNS["excluded_sectors"], text, flags=re.I)
    tick = re.search(PATTERNS["excluded_tickers"], text, flags=re.I)
    excluded_sectors = [s for s in SECTORS if sec and s.lower() in sec.group(1).lower()]
    excluded_tickers = [t for t in re.findall(r"\b[A-Z]{1,5}\b", tick.group(1) if tick else "")
                        if t in BY_TICKER]
    citations = [c for c in (_cite(rule, pat, chunks) for rule, pat in PATTERNS.items()) if c]
    return MandateRules(
        client_id=client_id,
        holdings=int(holdings.group(1)) if holdings else 10,
        max_weight=_pct(PATTERNS["max_weight"], text) or 0.15,
        min_weight=_pct(PATTERNS["min_weight"], text) or 0.02,
        max_sector_weight=_pct(PATTERNS["max_sector_weight"], text) or 0.35,
        max_volatility=_pct(PATTERNS["max_volatility"], text) or 0.20,
        risk_aversion=float(ra.group(1)) if ra else 4.0,
        excluded_sectors=excluded_sectors,
        excluded_tickers=excluded_tickers,
        approval_required=bool(re.search(PATTERNS["approval_required"], text, flags=re.I)),
        citations=citations,
    )


def _sane(rules: MandateRules, reference: MandateRules) -> tuple[MandateRules, list[str]]:
    """Reject impossible LLM values; where the LLM and the patterns disagree, keep the stricter."""
    notes = []
    fixed = rules.model_copy()
    checks = {
        "holdings": 2 <= rules.holdings <= 20,
        "max_weight": 0 < rules.max_weight <= 1,
        "min_weight": 0 <= rules.min_weight < rules.max_weight,
        "max_sector_weight": 0 < rules.max_sector_weight <= 1,
        "max_volatility": 0 < rules.max_volatility < 1,
        "risk_aversion": 0 < rules.risk_aversion <= 50,
    }
    for name, ok in checks.items():
        if not ok:
            setattr(fixed, name, getattr(reference, name))
            notes.append(f"{name}: LLM value {getattr(rules, name)} is out of range; used {getattr(reference, name)}")
    stricter = {"max_weight": min, "max_sector_weight": min, "max_volatility": min, "min_weight": max}
    for name, pick in stricter.items():
        a, b = getattr(fixed, name), getattr(reference, name)
        if abs(a - b) > 1e-9:
            setattr(fixed, name, pick(a, b))
            notes.append(f"{name}: LLM read {a}, document patterns read {b}; kept the stricter {pick(a, b)}")
    if fixed.holdings != reference.holdings:
        notes.append(f"holdings: LLM read {fixed.holdings}, patterns read {reference.holdings}; kept the document value")
        fixed.holdings = reference.holdings
    fixed.excluded_sectors = sorted(set(fixed.excluded_sectors) | set(reference.excluded_sectors))
    fixed.excluded_tickers = sorted(set(fixed.excluded_tickers) | set(reference.excluded_tickers))
    fixed.excluded_sectors = [s for s in fixed.excluded_sectors if s in SECTORS]
    fixed.excluded_tickers = [t for t in fixed.excluded_tickers if t in BY_TICKER]
    fixed.approval_required = fixed.approval_required or reference.approval_required
    if not fixed.citations:
        fixed.citations = reference.citations
    return fixed, notes


async def extract_mandate_rules(data: dict[str, Any], ctx: SkillContext) -> dict[str, Any]:
    settings = get_settings()
    client_id = data["client_id"]
    chunks: dict[str, dict] = {}
    searches = []
    async with MCPHub(settings.mcp_transport, settings.mcp_timeout_seconds,
                      recorder=ctx.record_tool) as hub:
        tools = hub.toolbox("compliance_agent")
        for rule, query in RULE_QUERIES.items():
            found = await tools.call("research", "search_documents", query=query, k=2,
                                     mode="hybrid", doc_types=["mandate"], client_id=client_id)
            searches.append({"rule": rule, "query": query,
                             "chunks": [h["chunk_id"] for h in found["hits"]]})
            for hit in found["hits"]:
                chunks.setdefault(hit["chunk_id"], hit)
    ordered = sorted(chunks.values(), key=lambda c: c["chunk_id"])
    reference = rules_from_text(client_id, ordered)

    gateway = LLMGateway(settings, recorder=ctx.record_llm)
    excerpts = "\n\n".join(f"[chunk {c['chunk_id']}]\n{c['text']}" for c in ordered)
    rules, method = await gateway.structured(
        "compliance_extract_rules", MandateRules, SYSTEM,
        f"Client id: {client_id}\n\nPolicy excerpts:\n{excerpts}",
        fallback=lambda: reference,
    )
    rules.client_id = client_id
    notes: list[str] = []
    if method == "llm":
        rules, notes = _sane(rules, reference)
    return {"rules": rules.model_dump(), "method": method, "notes": notes,
            "retrieved_chunks": [c["chunk_id"] for c in ordered], "searches": searches}


def check_portfolio_rules(rules: MandateRules, weights: dict[str, float],
                          volatility: float | None) -> ComplianceReport:
    cite = {c.rule: c.chunk_id for c in rules.citations}
    held = {t: w for t, w in weights.items() if w > 1e-9}
    sectors: dict[str, float] = {}
    for t, w in held.items():
        sectors[BY_TICKER[t].sector] = sectors.get(BY_TICKER[t].sector, 0) + w
    tol = 1e-4
    checks = [
        RuleCheck(rule="holdings", passed=len(held) == rules.holdings,
                  detail=f"{len(held)} stocks held; mandate requires exactly {rules.holdings}",
                  citation=cite.get("holdings")),
        RuleCheck(rule="max_weight", passed=max(held.values(), default=0) <= rules.max_weight + tol,
                  detail=f"largest position {max(held.values(), default=0):.1%}; limit {rules.max_weight:.0%}",
                  citation=cite.get("max_weight")),
        RuleCheck(rule="min_weight", passed=min(held.values(), default=0) >= rules.min_weight - tol,
                  detail=f"smallest position {min(held.values(), default=0):.1%}; minimum {rules.min_weight:.0%}",
                  citation=cite.get("min_weight")),
        RuleCheck(rule="max_sector_weight",
                  passed=max(sectors.values(), default=0) <= rules.max_sector_weight + tol,
                  detail="largest sector " + (f"{max(sectors, key=sectors.get)} {max(sectors.values()):.1%}"
                                              if sectors else "n/a") + f"; limit {rules.max_sector_weight:.0%}",
                  citation=cite.get("max_sector_weight")),
        RuleCheck(rule="excluded_sectors",
                  passed=not any(BY_TICKER[t].sector in rules.excluded_sectors for t in held),
                  detail=("no holdings in " + ", ".join(rules.excluded_sectors)) if rules.excluded_sectors
                  else "no sector exclusions",
                  citation=cite.get("excluded_sectors")),
        RuleCheck(rule="excluded_tickers", passed=not (set(held) & set(rules.excluded_tickers)),
                  detail=("excluded: " + ", ".join(rules.excluded_tickers)) if rules.excluded_tickers
                  else "no company exclusions",
                  citation=cite.get("excluded_tickers")),
    ]
    if volatility is not None:
        checks.append(RuleCheck(rule="max_volatility", passed=volatility <= rules.max_volatility + tol,
                                detail=f"expected volatility {volatility:.1%}; limit {rules.max_volatility:.0%}",
                                citation=cite.get("max_volatility")))
    for check in checks:
        if not check.passed and check.rule == "excluded_sectors":
            bad = [t for t in held if BY_TICKER[t].sector in rules.excluded_sectors]
            check.detail = f"holds {', '.join(bad)} in an excluded sector"
        if not check.passed and check.rule == "excluded_tickers":
            check.detail = f"holds excluded {', '.join(sorted(set(held) & set(rules.excluded_tickers)))}"
    return ComplianceReport(passed=all(c.passed for c in checks), checks=checks)


async def check_portfolio(data: dict[str, Any], ctx: SkillContext) -> dict[str, Any]:
    rules = MandateRules.model_validate(data["rules"])
    report = check_portfolio_rules(rules, data["weights"], data.get("volatility"))
    return report.model_dump()


SKILLS = {"extract-mandate-rules": extract_mandate_rules, "check-portfolio": check_portfolio}


def card(base_url: str):  # noqa: ANN201
    return agent_card(
        "Compliance Agent",
        "Reads client investment policy statements (hybrid RAG) and checks portfolios against them.",
        base_url,
        [
            AgentSkill(id="extract-mandate-rules", name="Extract mandate rules",
                       description="Machine-checkable rules with citations from a client's IPS.",
                       tags=["compliance", "rag", "mandate"], examples=['{"client_id": "C-102"}']),
            AgentSkill(id="check-portfolio", name="Check portfolio",
                       description="Rule-by-rule check of a proposed portfolio.",
                       tags=["compliance", "guardrail"]),
        ],
    )


def executor() -> SkillExecutor:
    return SkillExecutor(NAME, SKILLS)
