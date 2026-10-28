"""Signed approval tokens: the only way an agent can get orders executed.

When a person approves, the approval step issues a token that binds
    run id, client id, reviewer, a hash of the exact orders, and an expiry
with HMAC-SHA256. The broker verifies it before trading and rejects a token that is forged,
expired, for another client, or for different orders (an agent cannot change the orders after
the human saw them). Each token works once (the broker keeps used token ids).

The key comes from APPROVAL_SECRET, or a random key stored in data/.approval_secret (git
ignored), so the API process and stdio MCP servers share it.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from typing import Any


class ApprovalError(Exception):
    pass


def _secret_file() -> Path:
    from app.data import store

    return store.data_dir() / ".approval_secret"


def _secret() -> bytes:
    from app.config import get_settings

    configured = get_settings().approval_secret
    if configured and configured.get_secret_value():
        return configured.get_secret_value().encode()
    path = _secret_file()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "x", encoding="utf-8") as fh:  # exclusive: two processes, one key
                fh.write(secrets.token_hex(32))
        except FileExistsError:
            pass
    return path.read_text(encoding="utf-8").strip().encode()


def orders_hash(trades: list[dict[str, Any]]) -> str:
    canonical = sorted((t["ticker"], t["side"], int(t["shares"])) for t in trades)
    return hashlib.sha256(json.dumps(canonical).encode()).hexdigest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue(run_id: str, client_id: str, reviewer: str, trades: list[dict[str, Any]],
          ttl_seconds: int = 900) -> str:
    claims = {"jti": f"{run_id}:{secrets.token_hex(6)}", "run": run_id, "client": client_id,
              "reviewer": reviewer, "orders": orders_hash(trades), "n": len(trades),
              "exp": int(time.time()) + ttl_seconds}
    body = _b64(json.dumps(claims, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify(token: str, client_id: str, trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Returns the claims, or raises ApprovalError with the reason."""
    try:
        body, sig = token.split(".")
        claims = json.loads(_unb64(body))
    except Exception as exc:  # noqa: BLE001 - any malformed token
        raise ApprovalError("malformed approval token") from exc
    expected = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        raise ApprovalError("approval token signature is invalid")
    if claims.get("exp", 0) < time.time():
        raise ApprovalError("approval token has expired")
    if claims.get("client") != client_id:
        raise ApprovalError("approval token is for another client")
    if claims.get("orders") != orders_hash(trades):
        raise ApprovalError("orders differ from the ones the reviewer approved")
    return claims
