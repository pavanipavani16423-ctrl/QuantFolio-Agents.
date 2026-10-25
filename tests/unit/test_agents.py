import json
from pathlib import Path

import pytest

from app.a2a.compliance_agent import _sane, check_portfolio_rules, rules_from_text
from app.agents.intake import heuristic_intake, mentioned_tickers
from app.agents.research import diversify, extractive_answer
from app.agents.supervisor import decide
from app.data import store
from app.rag.chunking import chunk_document
from app.schemas import MandateRules, Source

TRUTH = json.loads((Path(__file__).resolve().parents[2] / "data" / "eval" / "mandate_truth.json").read_text())


@pytest.mark.parametrize("client", ["C-101", "C-102", "C-103"])
def test_rule_patterns_extract_every_mandate_exactly(client: str) -> None:
    chunks = [c.to_dict() for c in chunk_document(store.document(f"mandate_{client}"))]
    rules = rules_from_text(client, chunks)
    for key, expected in TRUTH[client].items():
        got = getattr(rules, key)
        assert (sorted(got) == sorted(expected)) if isinstance(expected, list) else got == pytest.approx(expected), key
    assert {c.rule for c in rules.citations} >= {"holdings", "max_weight", "max_volatility"}


def test_llm_rules_are_sanity_checked_toward_the_stricter_value() -> None:
    reference = MandateRules(client_id="C-1", **TRUTH["C-102"])
    llm = reference.model_copy(update={"max_weight": 0.35, "holdings": 9, "excluded_sectors": []})
    fixed, notes = _sane(llm, reference)
    assert fixed.max_weight == 0.20  # stricter of 0.35 and 0.20
    assert fixed.holdings == 8
    assert fixed.excluded_sectors == ["Energy"]  # an exclusion can never be dropped
    assert notes


def test_portfolio_check_flags_each_broken_rule() -> None:
    rules = MandateRules(client_id="C-102", **TRUTH["C-102"])
    weights = {"XOM": 0.3, "NVDA": 0.1, "MSFT": 0.1, "AAPL": 0.1, "KO": 0.1, "PG": 0.1, "JNJ": 0.1, "V": 0.1}
    report = check_portfolio_rules(rules, weights, volatility=0.30)
    failed = {c.rule for c in report.checks if not c.passed}
    assert not report.passed
    assert failed == {"max_weight", "excluded_sectors", "max_volatility"}


def test_supervisor_routes_a_full_run() -> None:
    state: dict = {"run_id": "r", "client_id": "C-102"}
    assert decide(state)[0] == ["intake"]
    state["intake"] = {"wants_rebalance": True}
    assert sorted(decide(state)[0]) == ["mandate", "research", "risk"]
    state.update(research={}, risk_profile={}, rules={})
    assert decide(state)[0] == ["optimize"]
    state.update(optimization={}, attempts=1)
    assert decide(state)[0] == ["backtest"]
    state["backtest"] = {}
    assert decide(state)[0] == ["check"]
    state["compliance"] = {"passed": False, "checks": [{"rule": "max_volatility", "passed": False}]}
    assert decide(state)[0] == ["optimize"]  # one retry with more risk aversion
    state["attempts"] = 2
    assert decide(state)[0] == ["report"]
    state.update(memo={}, evaluation={})
    assert decide(state)[0] == []  # still failing: no trades
    state["compliance"] = {"passed": True, "checks": []}
    assert decide(state)[0] == ["trades"]
    state["trades"] = {}
    assert decide(state)[0] == ["approval"]
    state["approval"] = {"approved": True}
    assert decide(state)[0] == ["execute"]
    state["execution"] = {}
    assert decide(state)[0] == []


def test_non_volatility_failure_is_not_retried() -> None:
    state = {"intake": {}, "research": {}, "risk_profile": {}, "rules": {}, "optimization": {},
             "attempts": 1, "backtest": {},
             "compliance": {"passed": False, "checks": [{"rule": "excluded_sectors", "passed": False}]}}
    assert decide(state)[0] == ["report"]


def test_intake_finds_companies_by_name_and_ticker() -> None:
    assert mentioned_tickers("Climate risks for NVIDIA and NextEra?") == ["NVDA", "NEE"]
    assert mentioned_tickers("I have a vision") == []
    result = heuristic_intake("Rebalance please. What are Apple's risks?", "C-103")
    assert result.research_question == "What are Apple's risks?"
    assert result.focus_tickers == ["AAPL"]


def test_diversify_spreads_slots_across_companies() -> None:
    hits = [{"ticker": "A", "rank": i} for i in range(1, 6)] + [{"ticker": "B", "rank": 6}]
    picked = diversify(hits, 3)
    assert {h["ticker"] for h in picked} == {"A", "B"}


def test_extractive_answer_cites_its_sources() -> None:
    src = Source(n=1, chunk_id="X#1", doc_id="X", doc_type="risk_factors", ticker="X", title="t",
                 text="Supply shortages could adversely affect our results. Other text follows here today.")
    answer = extractive_answer("What supply risks exist?", [src])
    assert "[1]" in answer.answer
    assert answer.risk_flags[0].source == 1
