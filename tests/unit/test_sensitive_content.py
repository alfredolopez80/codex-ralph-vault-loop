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


def postgres_url(user: str, segment: str) -> str:
    return "postgres" + "://" + user + ":" + segment + "@host/db"


def printf_database_url(user_argument: str, credential_argument: str) -> str:
    formatter = "%" + "s"
    return "printf '" + postgres_url(formatter, formatter) + "' " + user_argument + " " + credential_argument


def printf_database_url_in_command_substitution(user_argument: str, credential_argument: str) -> str:
    return "dsn=\"$(" + printf_database_url(user_argument, credential_argument) + ")\""


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


def test_sensitive_detector_allows_safe_references_without_values() -> None:
    env_name = "." + "env"
    access_name = "ACCESS" + "_" + "TO" + "KEN"
    token_name = "TO" + "KEN"
    api_name = "api" + "_" + "key"
    samples = [
        f"Mention {env_name} in the policy without reading its contents.",
        f"Document the {access_name} variable name without a value.",
        f"Search for {token_name} references before changing the guard.",
        f"Review the {api_name} field name in docs.",
    ]

    for sample in samples:
        report = classify_text(sample)
        assert report.classification == "GREEN", sample
        assert not report.findings, sample


def test_sensitive_detector_allows_runtime_generated_database_urls() -> None:
    scheme = "postgres" + "ql"
    pw_name = "app_" + "pass" + "word"
    url_prefix = scheme + "://control_api_runtime:"
    samples = [
        url_prefix + "${" + pw_name + "}@postgres/control_api",
        url_prefix + "$" + pw_name + "@postgres/control_api",
        "DATABASE_URL=" + url_prefix + "${" + pw_name + "}@postgres/control_api",
        "db_url: " + url_prefix + "$" + pw_name + "@postgres/control_api",
        "DATABASE_URL=redis" + "://:${" + "REDIS_PASSWORD" + "}@redis:6379/0",
        "db_url: postgres" + "://:${" + "DB_PASSWORD" + "}@host/db",
    ]

    for sample in samples:
        report = classify_text(sample)
        assert report.classification == "GREEN", sample
        assert not report.findings, sample


def test_sensitive_detector_allows_printf_database_url_template_only_as_full_credential_segment() -> None:
    formatter = "%" + "s"
    runtime_variable = "$" + "DB_PASSWORD"
    braced_runtime_variable = "${" + "DB_PASSWORD" + "}"
    allowed = [
        postgres_url("user", runtime_variable),
        postgres_url("user", braced_runtime_variable),
    ]
    blocked = [
        postgres_url(formatter, formatter),
        postgres_url("user", "actual-value"),
        postgres_url("user", "prefix-" + formatter),
        postgres_url("user", formatter + "-suffix"),
    ]

    for sample in allowed:
        report = classify_text(sample)
        assert report.classification == "GREEN", sample
        assert not report.findings, sample

    for sample in blocked:
        report = classify_text(sample)
        assert report.classification == "RED", sample
        assert any(finding.kind == "database_url" for finding in report.findings), sample


def test_sensitive_detector_requires_runtime_printf_credential_argument() -> None:
    runtime_user = "$" + "user"
    runtime_credential = "$" + "DB_PASSWORD"
    literal_credential = "hun" + "ter2"

    safe_report = classify_text(printf_database_url(runtime_user, runtime_credential))
    blocked_report = classify_text(printf_database_url("app", literal_credential))

    assert safe_report.classification == "GREEN"
    assert blocked_report.classification == "RED"
    assert any(finding.kind == "database_url" for finding in blocked_report.findings)


def test_sensitive_detector_requires_runtime_credential_for_printf_command_substitution() -> None:
    runtime_credential = "$" + "DB_PASSWORD"
    literal_credential = "hun" + "ter2"

    safe_report = classify_text(printf_database_url_in_command_substitution("$user", runtime_credential))
    blocked_report = classify_text(printf_database_url_in_command_substitution("app", literal_credential))

    assert safe_report.classification == "GREEN"
    assert blocked_report.classification == "RED"


def test_sensitive_detector_blocks_printf_templates_with_unsupported_prior_placeholder() -> None:
    unsupported_formatter = "%" + "q"
    formatter = "%" + "s"
    template = postgres_url(unsupported_formatter, formatter)
    runtime_user = "$" + "user"
    runtime_credential = "$" + "DB_PASSWORD"
    sample = "printf '" + template + "' " + runtime_user + " " + runtime_credential

    report = classify_text(sample)

    assert report.classification == "RED"


def test_sensitive_detector_blocks_all_printf_literal_credential_bypasses() -> None:
    runtime_credential = "$" + "DB_PASSWORD"
    literal_credential = "hun" + "ter2"
    quoted_credential = "'" + runtime_credential + "'"
    escaped_credential = "\\" + runtime_credential
    direct = printf_database_url("app", literal_credential)
    samples = [
        printf_database_url("app", quoted_credential),
        printf_database_url("app", escaped_credential),
        "printf ok; " + direct,
        "LC_ALL=C " + direct,
        "env FOO=1 " + direct,
        "printf -v DATABASE_URL 'postgres://%s:%s@host/db' app " + literal_credential,
        "printf 'postgres://%s:%s@host/db' app " + runtime_credential + " app " + literal_credential,
        "-" + direct,
    ]

    for sample in samples:
        report = classify_text(sample)
        assert report.classification == "RED", sample


def test_sensitive_detector_blocks_literal_database_url_passwords_and_suffixes() -> None:
    scheme = "postgres" + "ql"
    pw_name = "app_" + "pass" + "word"
    samples = [
        scheme + "://control_api_runtime:hunter2@postgres/control_api",
        scheme + "://control_api_runtime:${" + pw_name + "}hunter2@postgres/control_api",
        scheme + "://control_api_runtime:$" + pw_name + "-hunter2@postgres/control_api",
        scheme + "://control_api_runtime:$(printf hunter2)@postgres/control_api",
        "connection-string: \"" + scheme + "://control:$" + "(python3 -c 'print(\"hunter2\")')@postgres/control_api\"",
        "DATABASE_URL=" + scheme + "://control_api_runtime:hunter2@postgres/control_api",
        scheme + "://control:${" + pw_name + "}@hunter2@postgres/control_api",
        "DATABASE_URL=" + scheme + "://control:${" + pw_name + "}@hunter2@postgres/control_api",
    ]

    for sample in samples:
        report = classify_text(sample)
        assert report.classification == "RED", sample
        assert any(finding.kind == "database_url" for finding in report.findings), sample
