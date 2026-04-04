"""
Central security utilities for Skanorder.
Handles: env config, field encryption, rate limiting, security headers.
"""
import os, base64, hmac, hashlib
from pathlib import Path
from dotenv import load_dotenv
from cryptography.fernet import Fernet

# Load .env if present
load_dotenv(Path(__file__).parent / ".env")

# ── Environment ───────────────────────────────────────────────

def _require_env(key: str, default: str = None) -> str:
    val = os.getenv(key, default)
    if not val:
        raise RuntimeError(
            f"Required environment variable {key} is not set. "
            f"Copy .env.example to .env and fill in the values."
        )
    return val

SECRET_KEY    = _require_env("SECRET_KEY", "dev-only-change-in-prod-32bytesmin!")
APP_ENV       = os.getenv("APP_ENV", "development")
CORS_ORIGINS  = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",")]
MP_WEBHOOK_SECRET = os.getenv("MP_WEBHOOK_SECRET", "")

# Warn if weak SECRET_KEY in production
if APP_ENV == "production" and SECRET_KEY == "dev-only-change-in-prod-32bytesmin!":
    raise RuntimeError("SECRET_KEY must be changed in production!")

# ── Field-level encryption for sensitive DB columns ──────────

_raw_enc_key = os.getenv("FIELD_ENCRYPTION_KEY", "")

def _derive_fernet_key(hex_key: str) -> bytes:
    """Derive a 32-byte Fernet key from a hex string."""
    raw = bytes.fromhex(hex_key) if hex_key else os.urandom(32)
    return base64.urlsafe_b64encode(raw[:32])

_fernet = Fernet(_derive_fernet_key(_raw_enc_key)) if _raw_enc_key else None

def encrypt_field(plaintext: str) -> str:
    """Encrypt a string field for DB storage. Returns base64 ciphertext."""
    if not _fernet or not plaintext:
        return plaintext
    return _fernet.encrypt(plaintext.encode()).decode()

def decrypt_field(ciphertext: str) -> str:
    """Decrypt a field from DB storage."""
    if not _fernet or not ciphertext:
        return ciphertext
    try:
        return _fernet.decrypt(ciphertext.encode()).decode()
    except Exception:
        # Fallback: might be pre-encryption plaintext
        return ciphertext

# ── MercadoPago webhook signature ────────────────────────────

def verify_mp_signature(request_headers: dict, raw_body: bytes) -> bool:
    """
    Verify MercadoPago webhook X-Signature header.
    MP sends: X-Signature: ts=<timestamp>,v1=<signature>
    and X-Request-Id header.
    """
    if not MP_WEBHOOK_SECRET:
        # No secret configured → skip validation (dev mode only)
        if APP_ENV == "production":
            return False  # Reject unsigned webhooks in prod
        return True

    sig_header = request_headers.get("x-signature", "")
    request_id = request_headers.get("x-request-id", "")

    parts = dict(p.split("=", 1) for p in sig_header.split(",") if "=" in p)
    ts = parts.get("ts", "")
    v1 = parts.get("v1", "")

    if not ts or not v1:
        return False

    # MP signing template: id:<request_id>;request-id:<request_id>;ts:<ts>;
    signing_str = f"id:{request_id};request-id:{request_id};ts:{ts};"
    expected = hmac.new(
        MP_WEBHOOK_SECRET.encode(),
        signing_str.encode(),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected, v1)

# ── Security response headers ─────────────────────────────────

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}
