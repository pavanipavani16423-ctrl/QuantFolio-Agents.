"""Risk agent - a separate A2A service ("owned by the risk team").

Skills
* market-risk-profile : expected returns, covariance, volatility, beta, VaR and drawdown for
                        a list of tickers over the estimation window (market-data MCP server)
* portfolio-risk-check: risk of a proposed portfolio and a pass/fail against a volatility
                        limit, with plain-language warnings
"""

from typing import Any

from a2a.types import AgentSkill

from app.a2a.common import SkillContext, SkillExecutor, agent_card
from app.config import get_settings
from app.mcp.hub import MCPHub

NAME = "risk-agent"


async def market_risk_profile(data: dict[str, Any], ctx: SkillContext) -> dict[str, Any]:
    settings = get_settings()
    async with MCPHub(settings.mcp_transport, settings.mcp_timeout_seconds,
                      recorder=ctx.record_tool) as hub:
        stats = await hub.toolbox("risk_agent").call(
            "market", "get_market_stats", tickers=data["tickers"],
            start=data.get("start", settings.train_start), end=data.get("end", settings.train_end),
        )
    vols = stats["volatility"]
    riskiest = sorted(vols, key=lambda t: -vols[t])[:3]
    calmest = sorted(vols, key=lambda t: vols[t])[:3]
    notes = [
        f"Most volatile: {', '.join(f'{t} ({vols[t]:.0%})' for t in riskiest)}.",
        f"Least volatile: {', '.join(f'{t} ({vols[t]:.0%})' for t in calmest)}.",
        f"Covariance shrinkage (Ledoit-Wolf): {stats['covariance_shrinkage']:.2f}.",
    ]
    return {**stats, "notes": notes}


async def portfolio_risk_check(data: dict[str, Any], ctx: SkillContext) -> dict[str, Any]:
    settings = get_settings()
    async with MCPHub(settings.mcp_transport, settings.mcp_timeout_seconds,
                      recorder=ctx.record_tool) as hub:
        risk = await hub.toolbox("risk_agent").call(
            "market", "get_portfolio_risk", weights=data["weights"],
            start=data.get("start", settings.train_start), end=data.get("end", settings.train_end),
        )
    limit = data.get("max_volatility")
    warnings = []
    if limit is not None and risk["volatility"] > limit + 1e-6:
        warnings.append(f"Volatility {risk['volatility']:.1%} is above the {limit:.0%} limit.")
    if risk["max_drawdown"] > 0.25:
        warnings.append(f"Historical max drawdown {risk['max_drawdown']:.1%} is large.")
    if risk["beta"] > 1.2:
        warnings.append(f"Beta {risk['beta']:.2f}: moves more than the market.")
    return {**risk, "max_volatility": limit,
            "within_limit": limit is None or risk["volatility"] <= limit + 1e-6,
            "warnings": warnings}


SKILLS = {"market-risk-profile": market_risk_profile, "portfolio-risk-check": portfolio_risk_check}


def card(base_url: str):  # noqa: ANN201
    return agent_card(
        "Risk Agent",
        "Market and portfolio risk analytics (Ledoit-Wolf covariance, VaR, beta, drawdown).",
        base_url,
        [
            AgentSkill(id="market-risk-profile", name="Market risk profile",
                       description="Return and risk statistics for a list of tickers.",
                       tags=["risk", "covariance", "var"],
                       examples=['{"tickers": ["AAPL", "MSFT"], "start": "2024-01-02", "end": "2026-04-30"}']),
            AgentSkill(id="portfolio-risk-check", name="Portfolio risk check",
                       description="Volatility, beta, VaR, CVaR and drawdown of a weighted portfolio, "
                       "checked against a volatility limit.",
                       tags=["risk", "limits"]),
        ],
    )


def executor() -> SkillExecutor:
    return SkillExecutor(NAME, SKILLS)
