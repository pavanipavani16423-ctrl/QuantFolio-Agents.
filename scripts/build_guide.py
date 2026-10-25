"""Build docs/quantfolio-guide.html: one self-contained, shareable file.

The screenshots in docs/screenshots/guide-*.png are embedded as base64, and the quantum
numbers come from the latest experiments/results/quantum_eval_*.json, so the guide works
offline and can be sent as a single attachment.

    uv run python scripts/build_guide.py
"""

import base64
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SHOTS = ROOT / "docs" / "screenshots"

WALK = [
    ("guide-1-start.png", "Start", "1. Choose the client and ask",
     "The home page has one card. Pick who the portfolio is for, type what you want, press Start.",
     ["Pick a client. Three are in the US and one in India; each card shows its key rules.",
      "Click “Read this client's rules” to see the rules document the agents read.",
      "Type a request or click an example. Name companies if you like (“Reliance”, “TCS”, “Apple”).",
      "Press Start. A plan is ready in about a minute; nothing is traded without you."]),
    ("guide-2-progress.png", "Watch", "2. Watch the agents work",
     "The run page shows five plain stages. Each tab fills in as soon as its agent finishes.",
     ["The progress bar: Understand, Research, Choose stocks, Check & explain, Your decision.",
      "The line under it says what is happening right now.",
      "You can open the Research tab already while the stocks are being chosen."]),
    ("guide-3-decision.png", "Decide", "3. Approve, change or reject",
     "When the plan is ready, the decision box appears at the top with the buy and sell list.",
     ["Sell and Buy lists, with each stock's share of the money before and after.",
      "Approve: the practice trades are placed.",
      "Change: remove a stock, choose a smaller maximum per stock, or ask for less risk. The agents re-plan.",
      "Tick “Remember” and the next plan for this client follows your preference from the start."]),
    ("guide-4-plan.png", "Read", "4. Read the recommendation",
     "The Recommendation tab explains the plan in plain words.",
     ["The headline and a short summary.", "Expected yearly return, expected ups and downs, and number of stocks.",
      "What changes, and the risks to know, with source numbers you can click.",
      "One line on how the quantum computer did compared with the normal one."]),
    ("guide-5-research.png", "Sources", "5. Check the sources",
     "The Research tab answers your question only from the companies' own reports.",
     ["The answer, with numbered sources.", "Click a number to read the exact passage, with a link to the original report.",
      "For Indian companies the sources are the SEBI annual report sections and the BRSR report."]),
    ("guide-6-checks.png", "Checks", "6. See the rules and the quality",
     "The Checks tab shows every client rule and how good the answer is.",
     ["Each rule with a tick or a cross, and “Where it says so” in the rules document.",
      "Rules you added through feedback are listed too.",
      "Quality scores from the AI judge (RAGAS) and simple checks; “Langfuse” opens the full trace."]),
    ("guide-7-details.png", "Details", "7. Details, for experts",
     "The Details tab keeps the technical view out of the way.",
     ["Normal vs quantum vs hybrid: which stocks each picked, how good, how fast.",
      "How the money is split, and the back-test on recent months.",
      "Every agent step, the quantum circuit numbers, A2A messages and MCP tool calls."]),
]


def best_portfolio(client: str) -> list[str]:
    """The proven-optimal stock selection for a client (used by the qubit demo)."""
    from app.agents.optimizer import build_problem
    from app.config import get_settings
    from app.data import store
    from app.data.universe import MARKETS, tickers
    from app.quant.portfolio import select_exact, selection_problem
    from app.quant.stats import market_stats
    from app.schemas import MandateRules

    settings = get_settings()
    market = store.market_of_client(client)
    stats = market_stats(store.prices(market), tickers(market), MARKETS[market].benchmark,
                         settings.train_start, settings.train_end).to_dict()
    truth = json.loads((ROOT / "data" / "eval" / "mandate_truth.json").read_text())[client]
    p = build_problem(stats, MandateRules(client_id=client, **truth))
    sp = selection_problem(p["tickers"], p["sectors"], p["mu"], p["cov"], p["k"], p["risk_aversion"],
                           p["max_sector_weight"])
    return select_exact(sp).selected


def data_uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def main() -> None:
    template = (ROOT / "docs" / "guide" / "template.html").read_text("utf-8")
    walk = []
    for file, short, title, text, points in WALK:
        path = SHOTS / file
        if not path.exists():
            sys.exit(f"missing screenshot {path}")
        walk.append({"img": data_uri(path), "alt": title, "short": short, "title": title,
                     "text": text, "points": points})

    results = sorted((ROOT / "experiments" / "results").glob("quantum_eval_*.json"))
    q = json.loads(results[-1].read_text())
    s = q["summary"]
    xy, x = s["xy"], s["x"]
    best = best_portfolio("C-101")
    html = (template
            .replace("{{BEST_US}}", json.dumps(best))
            .replace("{{WALK}}", json.dumps(walk))
            .replace("{{DATE}}", date.today().isoformat())
            .replace("{{Q_XY_PCT}}", f"{100 * xy['found_optimum'] / xy['runs']:.0f}")
            .replace("{{Q_XY_TEXT}}", f"{xy['found_optimum']} of {xy['runs']} runs; always valid answers")
            .replace("{{Q_X_PCT}}", f"{100 * x['found_optimum'] / x['runs']:.0f}")
            .replace("{{Q_X_TEXT}}", f"{x['found_optimum']} of {x['runs']} runs; only {x['mean_feasible_probability']:.0%} valid answers"))
    out = ROOT / "docs" / "quantfolio-guide.html"
    out.write_text(html, "utf-8")
    print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size / 1e6:.1f} MB); best C-101 portfolio {best}")


if __name__ == "__main__":
    main()
