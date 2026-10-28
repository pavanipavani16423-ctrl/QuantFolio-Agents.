import json
from pathlib import Path

import pytest

from app.a2a.compliance_agent import _sane, check_portfolio_rules, rules_from_text
from app.agents import research
from app.agents.intake import heuristic_intake, mentioned_tickers
from app.agents.research import extractive_answer
from app.agents.supervisor import decide
from app.data import store
from app.rag.chunking import chunk_document
from app.schemas import MandateRules, Source

TRUTH = json.loads((Path(__file__).resolve().parents[2] / "data" / "eval" / "mandate_truth.json").read_text())


@pytest.mark.parametrize("client", ["C-101", "C-102", "C-103", "C-201"])
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
    assert decide(state)[0] == ["guard"]
    state["input_guard"] = {"blocked": False}
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
    state["trades"] = {"limits": [{"check": "max_order_size", "passed": False}]}
    assert decide(state)[0] == []  # a broker limit fails: nothing to approve
    state["trades"] = {"limits": [{"check": "max_order_size", "passed": True}]}
    assert decide(state)[0] == ["approval"]
    state["approval"] = {"approved": True}
    assert decide(state)[0] == ["execute"]
    state["execution"] = {}
    assert decide(state)[0] == []


def test_blocked_request_stops_the_run() -> None:
    assert decide({"input_guard": {"blocked": True}}) == ([], "stop: the request was stopped by the input guardrails")


def test_non_volatility_failure_is_not_retried() -> None:
    state = {"input_guard": {"blocked": False}, "intake": {}, "research": {}, "risk_profile": {}, "rules": {}, "optimization": {},
             "attempts": 1, "backtest": {},
             "compliance": {"passed": False, "checks": [{"rule": "excluded_sectors", "passed": False}]}}
    assert decide(state)[0] == ["report"]


def test_intake_finds_companies_by_name_and_ticker() -> None:
    assert mentioned_tickers("Climate risks for NVIDIA and NextEra?") == ["NVDA", "NEE"]
    assert mentioned_tickers("I have a vision") == []
    result = heuristic_intake("Rebalance please. What are Apple's risks?", "C-103")
    assert result.research_question == "What are Apple's risks?"
    assert result.focus_tickers == ["AAPL"]


@pytest.mark.anyio
async def test_every_company_asked_about_gets_passages(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    async def search(_ctx, query, k, tickers=None, **_):  # noqa: ANN001, ANN003, ANN202
        calls.append((tickers, k))
        return [{"ticker": tickers[0], "rank": i} for i in range(1, k + 1)]

    monkeypatch.setattr(research, "search", search)
    hits = await research.per_company(None, "risks?", ["TCS", "HDFCBANK", "HINDUNILVR"], 6)
    assert calls == [(["TCS"], 2), (["HDFCBANK"], 2), (["HINDUNILVR"], 2)]
    assert [h["ticker"] for h in hits] == ["TCS", "TCS", "HDFCBANK", "HDFCBANK", "HINDUNILVR", "HINDUNILVR"]
    calls.clear()
    await research.per_company(None, "risks?", [f"T{i}" for i in range(8)], 6)
    assert {k for _, k in calls} == {1}


def test_extractive_answer_quotes_whole_sentences_only() -> None:
    text = ("Source: NSE annual report filing, https://example.com/ar.pdf\n\nMarket risks arise from failing to "
            "meet sustainability goals, leading to competitive disadvantages. 3 Climate in building the brand "
            "as a top end offering.")
    src = Source(n=1, chunk_id="X#1", doc_id="X", doc_type="brsr", ticker="X", title="t", text=text)
    points = extractive_answer("What sustainability risks?", [src]).companies[0].key_points
    assert points == ["Market risks arise from failing to meet sustainability goals, leading to "
                      "competitive disadvantages [1]."]


def test_extractive_answer_cites_its_sources() -> None:
    src = Source(n=1, chunk_id="X#1", doc_id="X", doc_type="risk_factors", ticker="X", title="t",
                 text="Supply shortages could adversely affect our results. Other text follows here today.")
    answer = extractive_answer("What supply risks exist?", [src])
    assert "[1]" in answer.answer
    assert answer.risk_flags[0].source == 1


def test_advisor_feedback_only_tightens_the_rules() -> None:
    from app.agents.preferences import effective_rules, feedback_to_preferences

    rules = MandateRules(client_id="C-102", **TRUTH["C-102"])
    prefs = [{"kind": "exclude_ticker", "value": "NVDA"}, {"kind": "max_weight", "value": "0.15"},
             {"kind": "note", "value": "keep turnover low"}]
    feedback = [{"changes": {"remove_tickers": ["GOOGL"], "max_weight": 0.30, "lower_risk": True},
                 "note": "less tech"}]
    out, applied = effective_rules(rules, prefs, feedback)
    assert set(out.excluded_tickers) >= {"NVDA", "GOOGL"}
    assert out.max_weight == 0.15  # a looser cap (0.30) is ignored
    assert out.risk_aversion == pytest.approx(TRUTH["C-102"]["risk_aversion"] * 1.5)
    assert applied["notes"] == ["keep turnover low", "less tech"]
    assert rules.max_weight == 0.20  # the mandate itself is unchanged

    # an impossible cap (5% with 8 holdings) is raised to the smallest feasible one
    tight, _ = effective_rules(rules, [{"kind": "max_weight", "value": "0.05"}], [])
    assert tight.max_weight >= 1 / 8

    rows = feedback_to_preferences("C-102", {"changes": {"remove_tickers": ["NVDA"], "lower_risk": True},
                                             "note": "why", "reviewer": "r"}, "run_1")
    assert {r["kind"] for r in rows} == {"exclude_ticker", "lower_risk", "note"}


def test_india_research_uses_sebi_documents_and_inr() -> None:
    from app.data.universe import MARKETS, market_of_tickers, tickers

    assert MARKETS["IN"].research_doc_types == ("ar_risk", "ar_mdna", "brsr")
    assert market_of_tickers(["TCS", "INFY", "NIFTY50"]) == "IN"
    with pytest.raises(ValueError):
        market_of_tickers(["TCS", "AAPL"])
    assert "ITC" in tickers("IN") and "AAPL" not in tickers("IN")
    assert mentioned_tickers("Our reliance on titanium suppliers", "IN") == []
    assert mentioned_tickers("Compare Reliance and Tata Steel", "IN") == ["RELIANCE", "TATASTEEL"]


def test_citations_are_normalized_to_one_style() -> None:
    from app.agents.research import normalize_citations

    assert normalize_citations("A【1】 B【2†L3-L5】 C [3, 4] D [5][6]") == "A[1] B[2] C [3][4] D [5][6]"
    assert normalize_citations("Not in the reports [none]. Cited [2].") == "Not in the reports. Cited [2]."


@pytest.mark.anyio
async def test_intake_keeps_every_company_the_request_names() -> None:
    """The model's ticker list is backed up by the name matcher (a live run once dropped HDFC Bank)."""
    from types import SimpleNamespace

    from app.agents.intake import run_intake
    from app.schemas import IntakeResult

    async def structured(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        return IntakeResult(client_id="C-201", wants_rebalance=True, research_question="How stable are they?",
                            focus_tickers=["TCS", "HINDUNILVR", "AAPL"]), "llm"

    ctx = SimpleNamespace(llm=SimpleNamespace(structured=structured))
    request = "Rebalance. How stable are TCS, HDFC Bank and Hindustan Unilever?"
    result, _ = await run_intake(ctx, request, "C-201")
    assert result.focus_tickers == ["TCS", "HINDUNILVR", "HDFCBANK"]  # AAPL is not an NSE stock
