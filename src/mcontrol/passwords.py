"""RCON password generation. Decision 010."""

import secrets


def generate() -> str:
    """Return a fresh URL-safe RCON password (~192 bits of entropy)."""
    return secrets.token_urlsafe(24)
