"""Reads and writes the long-term memory layers (see app.memory)."""

import asyncio
from datetime import UTC, datetime
from typing import Any

import numpy as np

from app.config import Settings
from app.db.database import Database
from app.guardrails import Finding
from app.guardrails.injection import scan
from app.guardrails.pii import redact

NOTE_CHARS = 200


def _when(iso: str | None) -> str:
    if not iso:
        return "earlier"
    try:
        return datetime.fromisoformat(iso).astimezone(UTC).strftime("%d %b %Y")
    except ValueError:
        return iso[:10]


class MemoryManager:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    # ---- guards ----------------------------------------------------------------------------
    def is_attack(self, text: str) -> bool:
        """Both stages of the injection detector (patterns, then meaning)."""
        if scan(text).is_attack(self.settings.injection_block_threshold):
            return True
        from app.guardrails.input import semantic_check

        return semantic_check(text, self.settings.semantic_injection_threshold)[0]

    def screen_note(self, text: str) -> tuple[str | None, Finding]:
        """A note may become guidance for later runs only if it is not an instruction attack."""
        clean, pii = redact(text.strip())
        if self.is_attack(clean):
            return None, Finding("memory", "note_injection", "block",
                                 "note not kept as guidance: it reads like an instruction to the AI")
        detail = "note is safe to reuse" + (f"; removed {', '.join(pii)}" if pii else "")
        return clean[:NOTE_CHARS], Finding("memory", "note_injection", "fixed" if pii else "pass", detail)

    # ---- recall ----------------------------------------------------------------------------
    async def recall(self, client_id: str) -> dict[str, Any]:
        prefs = await self.db.preferences(client_id)
        semantic = [p for p in prefs if p["kind"] != "note"]
        procedural, findings = [], []
        for note in [p for p in prefs if p["kind"] == "note"][-self.settings.memory_notes_recalled:]:
            text, finding = self.screen_note(note["value"])
            if text is None:
                findings.append(finding)
                continue
            procedural.append({**note, "value": text})
        episodes = [e for e in await self.db.episodes(client_id, self.settings.memory_episodes_recalled)
                    if not self.is_attack(e["summary"])]
        return {
            "semantic": semantic,
            "procedural": procedural,
            "episodic": [{"run_id": e["run_id"], "outcome": e["outcome"], "summary": e["summary"],
                          "when": _when(e["created_at"]), "created_at": e["created_at"]} for e in episodes],
            "quarantined": [f.to_dict() for f in findings],
        }

    @staticmethod
    def preferences(memory: dict[str, Any]) -> list[dict[str, Any]]:
        """Semantic + screened procedural items, in the shape `effective_rules` expects."""
        return [*memory.get("semantic", []), *memory.get("procedural", [])]

    # ---- write -----------------------------------------------------------------------------
    async def remember_preferences(self, rows: list[dict[str, Any]]) -> list[Finding]:
        keep, findings = [], []
        for row in rows:
            if row["kind"] == "note":
                text, finding = self.screen_note(row["value"])
                findings.append(finding)
                if text is None:
                    continue
                row = {**row, "value": text}
            keep.append(row)
        if keep:
            await self.db.add_preferences(keep)
        return findings

    async def remember_episode(self, client_id: str, run_id: str, outcome: str, state: dict[str, Any],
                               decision: dict[str, Any]) -> str:
        opt = state.get("optimization") or {}
        rec = (opt.get("proposals") or {}).get(opt.get("recommended") or "", {})
        stocks = rec.get("selected", [])
        note = (decision.get("note") or "").strip()
        if note:
            note = redact(note)[0][:120]
            if self.is_attack(note):
                note = "(withheld: it read like an instruction to the AI)"
        verb = {"approved": "approved", "rejected": "rejected", "changed": "asked for changes to"}[outcome]
        summary = (f"{decision.get('reviewer') or 'advisor'} {verb} a {len(stocks)}-stock plan"
                   + (f" ({', '.join(stocks[:10])})" if stocks else "")
                   + (f"; note: \"{note}\"" if note else ""))
        await self.db.add_episode({"client_id": client_id, "run_id": run_id, "outcome": outcome,
                                   "summary": summary,
                                   "data": {"selected": stocks, "weights": rec.get("weights", {}),
                                            "changes": decision.get("changes"),
                                            "revision": state.get("revision", 0)}})
        return summary

    # ---- research cache --------------------------------------------------------------------
    @staticmethod
    def _key(market: str, tickers: list[str], index_digest: str) -> str:
        return f"{market}|{','.join(sorted(tickers))}|{index_digest}"

    async def _embed(self, question: str) -> tuple[np.ndarray, str]:
        from app.rag.index import get_index

        index = await asyncio.to_thread(get_index)
        return await asyncio.to_thread(index.embed_query, question), getattr(index, "digest", "")

    async def cached_research(self, market: str, tickers: list[str], question: str) -> dict[str, Any] | None:
        if not self.settings.research_cache_enabled:
            return None
        vec, digest = await self._embed(question)
        best, best_sim = None, -1.0
        for row in await self.db.cache_candidates(self._key(market, tickers, digest),
                                                  self.settings.research_cache_ttl_hours):
            sim = float(np.dot(vec, np.asarray(row["embedding"], dtype=np.float32)))
            if sim > best_sim:
                best, best_sim = row, sim
        if best is None or best_sim < self.settings.research_cache_similarity:
            return None
        await self.db.cache_hit(best["id"])
        return {"result": best["result"], "similarity": round(best_sim, 4), "question": best["question"],
                "run_id": best["run_id"], "when": _when(best["created_at"])}

    async def cache_research(self, market: str, tickers: list[str], question: str,
                             result: dict[str, Any], run_id: str) -> None:
        if not self.settings.research_cache_enabled:
            return
        vec, digest = await self._embed(question)
        await self.db.cache_put({"key": self._key(market, tickers, digest), "question": question,
                                 "embedding": [round(float(x), 6) for x in vec], "result": result,
                                 "run_id": run_id})
