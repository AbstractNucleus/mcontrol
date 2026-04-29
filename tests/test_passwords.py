import re

from mcontrol import passwords


def test_generate_returns_url_safe_string():
    pwd = passwords.generate()
    # token_urlsafe(24) produces a 32-char string of [A-Za-z0-9_-].
    assert len(pwd) == 32
    assert re.fullmatch(r"[A-Za-z0-9_\-]+", pwd)


def test_generate_returns_distinct_values():
    pwds = {passwords.generate() for _ in range(20)}
    # Cryptographically-random; the chance of any collision in 20 pulls is negligible.
    assert len(pwds) == 20
