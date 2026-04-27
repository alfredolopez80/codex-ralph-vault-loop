from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "security"))

from sensitive_content import classify_text, is_red, redact_text  # noqa: E402


def private_key_fixture() -> str:
    begin = "-----" + "BEGIN " + "OPENSSH " + "PRIVATE" + " KEY" + "-----"
    end = "-----" + "END " + "OPENSSH " + "PRIVATE" + " KEY" + "-----"
    return begin + "\nfixture-body\n" + end


def jwt_fixture() -> str:
    return "eyJ" + "hbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signaturepart"


def test_sensitive_detector_covers_secret_families() -> None:
    samples = [
        "api_key" + "=fixture-value",
        "token" + "=fixture-value",
        "access_token" + "=fixture-value",
        jwt_fixture(),
        private_key_fixture(),
        "seed phrase: abandon ability able about above absent absorb abstract absurd abuse access accident",
        "wallet private_key=" + "0x" + ("a" * 64),
        "DATABASE_URL=postgres://user:pass@example.test:5432/app",
        "cat .env",
        "customer_id=12345",
    ]

    for sample in samples:
        report = classify_text(sample)
        assert report.classification == "RED", sample
        assert report.findings, sample


def test_redaction_public_output_does_not_include_secret_value() -> None:
    secret = "secret" + "=abc123"
    redacted, changed = redact_text(secret)

    assert changed is True
    assert secret not in redacted
    assert "[REDACTED:" in redacted
    assert is_red(secret)
