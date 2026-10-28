"""Security layers (mapped to the OWASP Top 10 for LLM Applications, 2025):

* LLM01 prompt injection        - app.guardrails.injection on requests, passages and notes;
                                  spotlighting of retrieved text
* LLM02 sensitive information   - app.guardrails.pii before storage, models and traces
                                  (Langfuse mask)
* LLM05 improper output handling- app.guardrails.output; orders are validated by the broker
* LLM06 excessive agency        - per-agent MCP tool permissions; orders need a signed,
                                  single-use, short-lived approval token bound to the exact
                                  orders a person approved (app.security.approvals)
* LLM07 system prompt leakage   - prompt-extraction requests are blocked; no secrets in prompts
* LLM08 vector store weaknesses - retrieval filters per client/market; poisoned passages are
                                  quarantined
* LLM10 unbounded consumption   - request size limit, per-address rate limit, tool-call budget
                                  per run, run timeout
Plus a hash-chained audit log of every decision (app.db.database.AuditRow).
"""
