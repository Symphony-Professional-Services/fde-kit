"""
Async Circle of Trust (CoT) authentication backend for a Symphony extension app.

Implements the app-backend half of Symphony's bidirectional trust flow:
https://docs.developers.symphony.com/building-extension-applications-on-symphony/app-authentication/circle-of-trust-authentication

The frontend counterpart is the `circleOfTrust` config passed to `ADK.start()`
in the ADK controller (`templates/frontend/controller.js`). ADK drives three callbacks,
which map one-to-one onto the three endpoints here:

    getAppToken()                     -> POST /api/v1/cot/token
    validateAppToken(tokenA, tokenS)  -> POST /api/v1/cot/tokens/validate
    validateJwt(jwt)                  -> POST /api/v1/cot/jwt/validate

Outbound pod requests execute asynchronously via `httpx.AsyncClient` (`trust_env=True`,
`verify=True`, `follow_redirects=False`) — reusing `src.core.http_client.get_http_client()`
automatically when hosted inside a `template-mcp` server so SRE Secure Web Proxy
(`HTTPS_PROXY` / `NO_PROXY`) and connection pooling work out of the box without blocking
the ASGI event loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import time
import urllib.parse
from pathlib import Path
from threading import Lock
from typing import Any

import httpx
import jwt
from cryptography.x509 import load_pem_x509_certificate
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger("cot-auth")

# appId must match `appGroupId` in the admin-portal app bundle and the `id`
# passed to ADK.start() in the controller.
APP_ID = os.getenv("SYMPHONY_APP_ID", "{{APP_ID}}")

# Pod used for backend-to-backend auth. This is the Symphony pod, NOT our own
# ingress host -- {{APP_HOST}} serves this app, it does not serve /login/v1/... .
POD_HOST = os.getenv("SYMPHONY_POD_HOST", "{{POD_HOST}}")

# PEM private key whose public half is registered as `rsaKey` in the app bundle.
APP_PRIVATE_KEY_PATH = os.getenv("SYMPHONY_APP_PRIVATE_KEY_PATH", "/app/secrets/{{APP_ID}}-private-key.pem")

# The pod expires Ts within five minutes; consume each (Ta, Ts) pair atomically once.
_PAIR_TTL_SECONDS = 300
_MAX_CACHED_PAIRS = 2048
_HTTP_TIMEOUT = 8.0
_MAX_BODY_BYTES = 1_048_576
_HOSTNAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$", re.IGNORECASE)

# Ta -> (Ts, expires_at). Guarded by a lock for concurrent ASGI requests.
_token_pairs: dict[str, tuple[str, float]] = {}
_token_pairs_lock = Lock()

_cert_cache: dict[str, Any] = {"pem": None, "pod_host": None, "expires_at": 0.0}
_cert_lock = asyncio.Lock()

_private_key_cache: dict[str, Any] = {"key": None, "pem": None}
_private_key_lock = Lock()

_fallback_http_client: httpx.AsyncClient | None = None


class CotError(Exception):
    """Raised when the CoT handshake cannot be completed."""


def _get_async_client() -> httpx.AsyncClient:
    """Reuse `template-mcp`'s lifespan-pooled SWP-aware client when available."""
    try:
        from src.core.http_client import get_http_client  # type: ignore[import-not-found]

        return get_http_client()
    except Exception:
        global _fallback_http_client
        if _fallback_http_client is None or _fallback_http_client.is_closed:
            _fallback_http_client = httpx.AsyncClient(
                trust_env=True,
                verify=True,
                follow_redirects=False,
                timeout=httpx.Timeout(connect=3.0, read=_HTTP_TIMEOUT, write=_HTTP_TIMEOUT, pool=3.0),
            )
        return _fallback_http_client


def _validated_pod_host() -> str:
    raw = os.getenv("SYMPHONY_POD_HOST", POD_HOST).strip()
    if not raw or raw.startswith("{{"):
        raise CotError("SYMPHONY_POD_HOST is not configured.")
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in raw):
        raise CotError("Invalid SYMPHONY_POD_HOST: control or whitespace characters forbidden.")
    if any(ch in raw for ch in ("@", "?", "#", "\\")):
        raise CotError("Invalid SYMPHONY_POD_HOST: forbidden URL characters.")

    if "://" in raw:
        parsed = urllib.parse.urlsplit(raw)
        if parsed.scheme.lower() != "https" or parsed.path not in ("", "/"):
            raise CotError("Invalid SYMPHONY_POD_HOST: expected bare hostname or https:// host without path.")
    else:
        if "/" in raw:
            raise CotError("Invalid SYMPHONY_POD_HOST: '/' is forbidden.")
        parsed = urllib.parse.urlsplit(f"//{raw}")

    hostname = (parsed.hostname or "").rstrip(".")
    if not hostname or ".." in hostname or not _HOSTNAME_RE.match(hostname):
        raise CotError(f"Invalid SYMPHONY_POD_HOST hostname: {raw}")
    return f"{hostname}:{parsed.port}" if parsed.port else hostname


# ---------------------------------------------------------------------------
# Token pair store (bounded TTL + one-time atomic consumption)
# ---------------------------------------------------------------------------


def _prune_expired(now: float) -> None:
    for token_a in [k for k, (_, exp) in _token_pairs.items() if exp <= now]:
        del _token_pairs[token_a]


def _store_pair(token_a: str, token_s: str) -> None:
    now = time.time()
    with _token_pairs_lock:
        _prune_expired(now)
        if len(_token_pairs) >= _MAX_CACHED_PAIRS:
            oldest_key = next(iter(_token_pairs))
            _token_pairs.pop(oldest_key, None)
        _token_pairs[token_a] = (token_s, now + _PAIR_TTL_SECONDS)


def _consume_pair(token_a: str, token_s: str) -> bool:
    """Atomically verify and consume (Ta, Ts) once so captured pairs cannot be replayed."""
    now = time.time()
    with _token_pairs_lock:
        _prune_expired(now)
        stored = _token_pairs.get(token_a)
        if not stored or not secrets.compare_digest(stored[0], token_s):
            return False
        _token_pairs.pop(token_a, None)
        return True


# ---------------------------------------------------------------------------
# Step 6: authenticate our backend against the pod (async httpx)
# ---------------------------------------------------------------------------


def _load_private_key() -> str:
    env_pem = os.getenv("SYMPHONY_APP_PRIVATE_KEY", "").strip()
    if env_pem and "PRIVATE KEY" in env_pem:
        return env_pem

    path = Path(os.getenv("SYMPHONY_APP_PRIVATE_KEY_PATH", APP_PRIVATE_KEY_PATH))
    try:
        resolved = path.resolve()
        st = resolved.stat()
    except OSError as exc:
        raise CotError(
            "App RSA private key is not configured or unreadable. Set SYMPHONY_APP_PRIVATE_KEY_PATH "
            "or mount the key; its public half must be registered as `rsaKey` in the app bundle."
        ) from exc

    cache_key = (str(resolved), st.st_mtime_ns, st.st_size)
    with _private_key_lock:
        if _private_key_cache["key"] == cache_key and _private_key_cache["pem"]:
            return str(_private_key_cache["pem"])

    pem_text = resolved.read_text(encoding="utf-8")
    with _private_key_lock:
        _private_key_cache["key"] = cache_key
        _private_key_cache["pem"] = pem_text
    return pem_text


def _build_auth_token() -> str:
    """Build the RS512 `authToken` JWT signed by our 4096-bit RSA private key."""
    now = int(time.time())
    app_id = os.getenv("SYMPHONY_APP_ID", APP_ID).strip() or APP_ID
    return str(
        jwt.encode(
            {"sub": app_id, "iat": now, "exp": now + 300},
            _load_private_key(),
            algorithm="RS512",
        )
    )


async def _read_bounded_stream(resp: httpx.Response, max_bytes: int = _MAX_BODY_BYTES) -> bytes:
    buf = bytearray()
    async for chunk in resp.aiter_bytes():
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise CotError(f"Pod response exceeded {max_bytes} bytes.")
    return bytes(buf)


async def _post_json_async(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    client = _get_async_client()
    app_id = os.getenv("SYMPHONY_APP_ID", APP_ID).strip() or APP_ID
    headers = {"Content-Type": "application/json", "User-Agent": f"{app_id}-server/1.0"}
    try:
        async with client.stream(
            "POST",
            url,
            json=payload,
            headers=headers,
            timeout=_HTTP_TIMEOUT,
            follow_redirects=False,
        ) as resp:
            if 300 <= resp.status_code < 400:
                raise CotError(f"Refusing redirect ({resp.status_code}) from pod authentication endpoint.")
            if resp.status_code >= 400:
                err_bytes = await _read_bounded_stream(resp, max_bytes=4096)
                detail = err_bytes.decode("utf-8", "replace")[:512]
                raise CotError(f"Pod rejected app authentication ({resp.status_code}): {detail}")
            raw_bytes = await _read_bounded_stream(resp)
    except CotError:
        raise
    except Exception as exc:
        raise CotError(f"Could not reach pod at {url}: {exc}") from exc

    try:
        parsed = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        raise CotError("Pod authentication response was not valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise CotError("Pod authentication response must be a JSON object.")
    return parsed


async def authenticate_extension_app() -> str:
    """Steps 5-11: mint Ta, exchange it asynchronously with the pod for Ts, store the pair, return Ta."""
    pod_host = _validated_pod_host()
    token_a = secrets.token_urlsafe(48)
    url = f"https://{pod_host}/login/v1/pubkey/app/authenticate/extensionApp"

    data = await _post_json_async(url, {"appToken": token_a, "authToken": _build_auth_token()})

    token_s = data.get("symphonyToken")
    if not token_s or not isinstance(token_s, str):
        raise CotError("Pod response missing symphonyToken.")
    if data.get("appToken") != token_a:
        raise CotError("Pod echoed a different appToken than the one we sent.")

    _store_pair(token_a, token_s)
    logger.info("CoT: pod authenticated app %s, token pair stored", data.get("appId", APP_ID))
    return token_a


# ---------------------------------------------------------------------------
# Steps 22-25: verify the user identity JWT
# ---------------------------------------------------------------------------


async def fetch_pod_certificate() -> str:
    """Fetch and positive-cache the pod's X.509 signing certificate (PEM) for an hour."""
    pod_host = _validated_pod_host()
    now = time.time()
    if (
        _cert_cache["pem"]
        and _cert_cache["pod_host"] == pod_host
        and now < float(_cert_cache["expires_at"])
    ):
        return str(_cert_cache["pem"])

    async with _cert_lock:
        now = time.time()
        if (
            _cert_cache["pem"]
            and _cert_cache["pod_host"] == pod_host
            and now < float(_cert_cache["expires_at"])
        ):
            return str(_cert_cache["pem"])

        url = f"https://{pod_host}/pod/v1/podcert"
        client = _get_async_client()
        app_id = os.getenv("SYMPHONY_APP_ID", APP_ID).strip() or APP_ID
        headers = {"User-Agent": f"{app_id}-server/1.0"}
        try:
            async with client.stream(
                "GET",
                url,
                headers=headers,
                timeout=_HTTP_TIMEOUT,
                follow_redirects=False,
            ) as resp:
                if 300 <= resp.status_code < 400:
                    raise CotError(f"Refusing redirect ({resp.status_code}) from pod certificate endpoint.")
                if resp.status_code >= 400:
                    raise CotError(f"Pod certificate endpoint returned HTTP {resp.status_code}.")
                raw_bytes = await _read_bounded_stream(resp)
        except CotError:
            raise
        except Exception as exc:
            raise CotError(f"Could not fetch pod certificate from {url}: {exc}") from exc

        try:
            payload = json.loads(raw_bytes.decode("utf-8"))
        except Exception as exc:
            raise CotError("Pod certificate response was not valid JSON.") from exc

        pem = payload.get("certificate") if isinstance(payload, dict) else None
        if not isinstance(pem, str) or not pem.strip():
            raise CotError("Pod certificate response had no 'certificate' field.")

        try:
            load_pem_x509_certificate(pem.encode("utf-8"))
        except Exception as exc:
            raise CotError(f"Pod returned invalid X.509 certificate PEM: {exc}") from exc

        _cert_cache["pem"] = pem
        _cert_cache["pod_host"] = pod_host
        _cert_cache["expires_at"] = now + 3600
        return pem


async def verify_user_jwt(token: str) -> dict[str, Any]:
    """Verify the user identity JWT against the pod X.509 certificate (`RS512`, `verify_sub=False`)."""
    if token.count(".") != 2:
        raise CotError("Malformed JWT structure.")

    pem = await fetch_pod_certificate()
    try:
        public_key = load_pem_x509_certificate(pem.encode("utf-8")).public_key()
    except Exception as exc:
        raise CotError(f"Pod X.509 certificate parsing failed: {exc}") from exc

    try:
        decoded = jwt.decode(
            token,
            public_key,
            algorithms=["RS512"],
            # verify_sub=False: PyJWT >= 2.10 enforces RFC 7519 string `sub`, while Symphony's
            # user JWT carries a numeric userId ("Subject must be a string"). Identity is read
            # from the `user` claim below, with mandatory `exp` verification intact.
            options={"verify_aud": False, "verify_sub": False, "require": ["exp"]},
        )
    except jwt.InvalidTokenError as exc:
        raise CotError(f"User JWT failed verification: {exc}") from exc

    if not isinstance(decoded, dict):
        raise CotError("Decoded JWT claims must be a JSON object.")
    return decoded


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------


async def _json_body(request: Request) -> dict[str, Any]:
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > _MAX_BODY_BYTES:
            return {}
    if not chunks:
        return {}
    try:
        body = json.loads(chunks.decode("utf-8"))
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


async def cot_token(_request: Request) -> JSONResponse:
    """getAppToken(): returns Ta after establishing backend trust with the pod."""
    try:
        return JSONResponse({"appToken": await authenticate_extension_app()})
    except CotError as exc:
        logger.error("CoT token request failed: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=502)


async def cot_validate_tokens(request: Request) -> JSONResponse:
    """validateAppToken(): asserts and consumes the (Ta, Ts) pair once."""
    body = await _json_body(request)
    token_a = body.get("appToken")
    token_s = body.get("symphonyToken")

    if not token_a or not token_s or not isinstance(token_a, str) or not isinstance(token_s, str):
        return JSONResponse({"error": "appToken and symphonyToken are required"}, status_code=400)

    if not _consume_pair(token_a, token_s):
        logger.warning("CoT token pair validation failed")
        return JSONResponse({"error": "token pair does not match"}, status_code=401)

    return JSONResponse({"status": "valid"})


async def cot_validate_jwt(request: Request) -> JSONResponse:
    """validateJwt(): verifies the user identity JWT and returns who the user is."""
    body = await _json_body(request)
    token = body.get("jwt")
    if not token or not isinstance(token, str):
        return JSONResponse({"error": "jwt is required"}, status_code=400)

    try:
        claims = await verify_user_jwt(token)
    except CotError as exc:
        logger.warning("CoT JWT validation failed: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=401)

    user = claims.get("user") if isinstance(claims.get("user"), dict) else {}
    logger.info("CoT: verified user %s", user.get("username") or user.get("id"))
    return JSONResponse(
        {
            "status": "valid",
            "userId": user.get("id"),
            "username": user.get("username"),
            "emailAddress": user.get("emailAddress"),
            "displayName": user.get("displayName"),
        }
    )
