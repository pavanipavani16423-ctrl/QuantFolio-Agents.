"""Input rail: the first step of every run, before any agent or model sees the request.

Prompt injection is detected in two stages: weighted patterns (precise, explainable), then -
only if the patterns find nothing - semantic similarity to a bank of attack intents (catches
paraphrases). The second stage's threshold is calibrated on benign requests.
"""

from app.guardrails import Finding, injection, scope, worst


def semantic_check(text: str, threshold: float | None) -> tuple[bool, str]:
    if threshold is None:
        return False, ""
    from app.guardrails.semantic import detector

    similarity, intent = detector().score(text)
    return similarity >= threshold, f'close to a known attack ("{intent}", similarity {similarity:.2f})'


def check_request(text: str, market: str, pii_counts: dict[str, int], threshold: float = 1.0,
                  semantic_threshold: float | None = None) -> tuple[str, list[Finding]]:
    """Returns (verdict, findings). `text` is already PII-redacted (see RunService.start)."""
    findings = []
    if pii_counts:
        kinds = ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in pii_counts.items())
        findings.append(Finding("input", "personal_data", "fixed",
                                f"removed before storage, models and traces: {kinds}"))
    else:
        findings.append(Finding("input", "personal_data", "pass", "no personal data found"))
    result = injection.scan(text)
    if result.is_attack(threshold):
        findings.append(Finding("input", "prompt_injection", "block", f"prompt injection detected ({result.describe()})"))
    else:
        hit, detail = semantic_check(text, semantic_threshold)
        if hit:
            findings.append(Finding("input", "prompt_injection", "block", f"prompt injection detected: {detail}"))
        else:
            findings.append(Finding("input", "prompt_injection", "warn" if result.score > 0 else "pass",
                                    f"no injection found (pattern score {result.score:.1f})"))
    policy = scope.check(text, market)
    findings.append(Finding("input", "scope_policy", "pass" if policy.allowed else "block", policy.detail))
    return worst(findings), findings
