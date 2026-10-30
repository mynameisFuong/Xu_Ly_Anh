import hashlib

import pytest

from backend.app.security import hash_password, verify_password


@pytest.mark.parametrize("format", ["legacy", "pbkdf2"])
def test_existing_password_formats_accept_correct_password_and_reject_wrong_password(format):
    stored = hash_password("demo-password")
    if format == "pbkdf2":
        salt = "existing-local-salt"
        digest = hashlib.pbkdf2_hmac("sha256", b"demo-password", salt.encode(), 600_000).hex()
        stored = f"pbkdf2_sha256$600000${salt}${digest}"
    assert verify_password("demo-password", stored)
    assert not verify_password("wrong-password", stored)


@pytest.mark.parametrize("stored", [
    "pbkdf2_sha256$600000$salt",
    "unsupported$600000$salt$digest",
    "pbkdf2_sha256$invalid$salt$digest",
    "pbkdf2_sha256$0$salt$digest",
    "pbkdf2_sha256$2000001$salt$digest",
    "pbkdf2_sha256$600000$salt$non-ascii-ệ",
])
def test_invalid_password_hashes_are_rejected(stored):
    assert not verify_password("demo-password", stored)
