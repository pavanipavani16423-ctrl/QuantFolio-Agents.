"""The whole system through the HTTP API: start -> agents -> pause for approval -> approve.

A2A calls go to an address where nothing listens, so they exercise the fallback to the
in-process agents (the same protocol over an ASGI transport).
"""

import time

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def _wait(client: TestClient, run_id: str, until: set[str], timeout: float = 240) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        doc = client.get(f"/api/v1/runs/{run_id}").json()
        if doc["status"] in until:
            return doc
        time.sleep(0.5)
    raise AssertionError(f"run stuck in {doc['status']}")


@pytest.fixture(scope="module")
def client():  # noqa: ANN201
    with TestClient(create_app()) as c:
        yield c


def test_agent_cards_are_published(client: TestClient) -> None:
    for name in ("risk", "compliance"):
        card = client.get(f"/a2a/{name}/.well-known/agent-card.json").json()
        assert card["skills"] and card["supportedInterfaces"][0]["url"].endswith(f"/a2a/{name}/rpc")


@pytest.mark.timeout(300)
def test_full_run_with_human_approval(client: TestClient) -> None:
    client.post("/api/v1/clients/C-102/reset")
    started = client.post("/api/v1/runs", json={
        "client_id": "C-102",
        "request": "Rebalance GreenLeaf. What climate risks do NVIDIA and NextEra disclose?",
        "methods": ["classical", "quantum", "hybrid"],
    })
    assert started.status_code == 202
    run_id = started.json()["id"]
    doc = _wait(client, run_id, {"awaiting_approval", "failed", "blocked"})
    assert doc["status"] == "awaiting_approval", doc.get("error")

    r = doc["result"]
    assert r["rules"]["excluded_sectors"] == ["Energy"]
    assert all(t not in ("XOM", "CVX") for t in r["optimization"]["proposals"]["classical"]["selected"])
    assert r["optimization"]["qubits"] == 18
    assert r["compliance"]["passed"]
    assert {s["ticker"] for s in r["research"]["sources"]} >= {"NVDA", "NEE"}
    scores = r["evaluation"]["scores"]
    assert scores["output_rule_extraction_accuracy"]["value"] == 1.0
    assert {a["agent"] for a in doc["a2a_calls"]} == {"risk", "compliance"}
    assert any(t["server"] == "optimizer" and t["tool"] == "select_quantum" for t in doc["tool_calls"])

    # approving twice: the second one is a conflict
    assert client.post(f"/api/v1/runs/{run_id}/approval", json={"approved": True, "reviewer": "test"}).status_code == 200
    doc = _wait(client, run_id, {"executed", "failed"})
    assert doc["status"] == "executed"
    assert client.post(f"/api/v1/runs/{run_id}/approval", json={"approved": True}).status_code == 409
    account = client.get("/api/v1/clients/C-102/account").json()
    assert not {"XOM", "CVX"} & set(account["positions"])


def test_unknown_client_is_404(client: TestClient) -> None:
    assert client.post("/api/v1/runs", json={"client_id": "C-999", "request": "hello"}).status_code == 404


@pytest.mark.timeout(400)
def test_change_replans_and_is_remembered(client: TestClient) -> None:
    """Human in the loop: "Change" re-plans now, and the next run starts from what was learned."""
    client.post("/api/v1/clients/C-103/reset")
    req = {"client_id": "C-103", "request": "Rebalance the Kumar family portfolio.",
           "methods": ["classical"]}
    run_id = client.post("/api/v1/runs", json=req).json()["id"]
    doc = _wait(client, run_id, {"awaiting_approval", "failed", "blocked"})
    assert doc["status"] == "awaiting_approval", doc.get("error")
    first = doc["result"]["optimization"]["proposals"]["classical"]["selected"]
    victim = first[0]

    # an empty change is refused
    empty = client.post(f"/api/v1/runs/{run_id}/approval", json={"action": "change", "changes": {}})
    assert empty.status_code == 409
    change = {"action": "change", "reviewer": "test", "note": f"no {victim}",
              "changes": {"remove_tickers": [victim], "lower_risk": True}, "remember": True}
    assert client.post(f"/api/v1/runs/{run_id}/approval", json=change).status_code == 200
    doc = _wait(client, run_id, {"awaiting_approval", "failed", "blocked"})
    assert doc["status"] == "awaiting_approval"
    second = doc["result"]["optimization"]["proposals"]["classical"]["selected"]
    assert victim not in second
    assert doc["result"]["revision"] == 1
    assert victim in doc["result"]["effective_rules"]["excluded_tickers"]
    assert doc["result"]["compliance"]["passed"]

    prefs = client.get("/api/v1/clients/C-103/preferences").json()
    assert {(p["kind"], p["value"]) for p in prefs} >= {("exclude_ticker", victim), ("lower_risk", "true")}
    assert client.post(f"/api/v1/runs/{run_id}/approval", json={"action": "reject", "note": "not now"}).status_code == 200
    assert _wait(client, run_id, {"rejected", "failed"})["status"] == "rejected"

    # the next run applies the learned preference from the start
    run2 = client.post("/api/v1/runs", json=req).json()["id"]
    doc2 = _wait(client, run2, {"awaiting_approval", "failed", "blocked"})
    assert victim not in doc2["result"]["optimization"]["proposals"]["classical"]["selected"]
    assert doc2["result"]["revision"] == 0
    assert any("learned" in s for s in doc2["result"]["applied"]["sources"])
    # the rejection reason was remembered too ("remember" defaults to on); forget everything
    current = client.get("/api/v1/clients/C-103/preferences").json()
    assert ("note", "not now") in {(p["kind"], p["value"]) for p in current}
    for p in current:
        assert client.delete(f"/api/v1/clients/C-103/preferences/{p['id']}").status_code == 200
    assert client.get("/api/v1/clients/C-103/preferences").json() == []


@pytest.mark.timeout(300)
def test_india_client_uses_nse_data_and_sebi_documents(client: TestClient) -> None:
    client.post("/api/v1/clients/C-201/reset")
    started = client.post("/api/v1/runs", json={
        "client_id": "C-201", "request": "Rebalance the trust. What risks do Reliance and TCS report?",
        "methods": ["classical", "quantum"]})
    run_id = started.json()["id"]
    doc = _wait(client, run_id, {"awaiting_approval", "failed", "blocked"})
    assert doc["status"] == "awaiting_approval", doc.get("error")
    assert doc["market"] == "IN" and doc["currency"] == "INR" and doc["benchmark_name"] == "Nifty 50"
    r = doc["result"]
    assert r["rules"]["excluded_tickers"] == ["ITC"]
    assert "ITC" not in r["optimization"]["proposals"]["classical"]["selected"]
    assert r["optimization"]["qubits"] == 17
    assert {s["doc_type"] for s in r["research"]["sources"]} <= {"ar_risk", "ar_mdna", "brsr", "facts"}
    assert {s["ticker"] for s in r["research"]["sources"]} >= {"RELIANCE", "TCS"}
    assert "benchmark" in r["backtest"]["metrics"]
