"""Agent memory, in the four layers of the CoALA taxonomy (Sumers et al., 2023), as used by
LangGraph's long-term store and Letta/MemGPT:

    layer        what                                         where                lifetime
    working      the run's state: request, findings, plan     LangGraph checkpoint one run (survives restarts)
    episodic     what happened in earlier reviews of a client  episodes table       until forgotten
    semantic     facts about a client: removed stocks, caps,   client_preferences   until forgotten
                 lower risk (they tighten the mandate)
    procedural   how to work for this client: the advisor's    client_preferences   until forgotten
                 notes, reused as writing guidance            (kind = note)

plus a semantic cache of checked research answers (research_cache), keyed by market,
companies and the index version, matched by embedding similarity.

Memory is written only from human decisions, and everything read back passes the guardrails
first (prompt injection, personal data), so a poisoned note cannot steer later runs.
"""

from app.memory.manager import MemoryManager

__all__ = ["MemoryManager"]
