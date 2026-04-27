from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SensitiveFinding:
    kind: str
    label: str
    severity: str = "RED"

    def public_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "label": self.label, "severity": self.severity}


@dataclass(frozen=True)
class SensitiveReport:
    classification: str
    findings: tuple[SensitiveFinding, ...]
    redacted_text: str
    changed: bool

    def public_dict(self) -> dict[str, object]:
        return {
            "classification": self.classification,
            "changed": self.changed,
            "findings": [finding.public_dict() for finding in self.findings],
        }


def _known_prefix(*parts: str) -> str:
    return "".join(parts)


_PRIVATE_KEY_PEM = (
    r"-{5}" + "BEGIN" + r"\s+[A-Z0-9 ]{0,32}" + "PRIVATE" + r"\s+KEY-{5}"
    r".*?"
    r"-{5}" + "END" + r"\s+[A-Z0-9 ]{0,32}" + "PRIVATE" + r"\s+KEY-{5}"
)

_DB_SCHEMES = r"(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis|rediss)"
_WORD = r"[a-z]{3,12}"

PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "api_key",
        "known_api_key_prefix",
        re.compile(
            r"\b(?:"
            + "|".join(
                re.escape(prefix)
                for prefix in (
                    _known_prefix("s", "k-"),
                    _known_prefix("AI", "za"),
                    _known_prefix("gh", "p_"),
                    _known_prefix("github", "_pat_"),
                    "glpat-",
                    "xoxb-",
                    "xoxp-",
                    "SG.",
                )
            )
            + r")[A-Za-z0-9_.\-=]{16,}\b"
        ),
    ),
    (
        "secret_assignment",
        "secret_like_assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|x-api-key|token|access[_-]?token|refresh[_-]?token|"
            r"id[_-]?token|secret|client[_-]?secret|password|credential|private[_-]?key)"
            r"\s*[:=]\s*['\"]?[^'\"\s]{4,}"
        ),
    ),
    (
        "oauth_token",
        "oauth_or_bearer_token",
        re.compile(
            r"(?i)\b(?:oauth[_-]?token|bearer)\b\s*[:=]?\s*['\"]?[A-Za-z0-9_.\-]{16,}"
        ),
    ),
    (
        "jwt",
        "jwt_token",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
    (
        "private_key",
        "private_key_pem",
        re.compile(_PRIVATE_KEY_PEM, re.IGNORECASE | re.DOTALL),
    ),
    (
        "seed_phrase",
        "wallet_seed_phrase",
        re.compile(
            r"(?is)\b(?:seed\s+phrase|recovery\s+phrase|mnemonic)\b.{0,200}\b(?:"
            + _WORD
            + r"\s+){11,23}"
            + _WORD
            + r"\b"
        ),
    ),
    (
        "wallet_material",
        "wallet_private_material",
        re.compile(
            r"(?i)\b(?:wallet|mnemonic|seed|private[_-]?key)[^\n]{0,100}\b(?:0x)?[a-f0-9]{64}\b"
        ),
    ),
    (
        "database_url",
        "database_url_with_credentials",
        re.compile(r"(?i)\b" + _DB_SCHEMES + r"://[^\s'\"<>/]+:[^\s'\"<>@]+@[^\s'\"<>]+"),
    ),
    (
        "database_url",
        "database_url_assignment",
        re.compile(
            r"(?i)\b(?:database_url|db_url|sqlalchemy_database_uri|mongo_uri|redis_url)"
            r"\s*[:=]\s*['\"]?[^'\"\s]+"
        ),
    ),
    (
        "env_file",
        "env_file_reference",
        re.compile(r"(?i)(?:^|[\s/])\.env(?:\.[A-Za-z0-9_-]+)?(?:$|[\s:/])"),
    ),
    (
        "customer_data",
        "customer_sensitive_marker",
        re.compile(
            r"(?i)\b(?:customer[_-]?(?:id|email|name|data)|customer\s+(?:data|record)|"
            r"ssn|social\s+security|patient[_-]?(?:id|record)|personal\s+data|pii|dob)\b"
        ),
    ),
)

CLASSIFICATIONS = {"GREEN", "YELLOW", "RED"}


def normalize_classification(value: str | None) -> str | None:
    if value is None:
        return None
    classification = value.strip().upper()
    if classification not in CLASSIFICATIONS:
        raise ValueError(f"classification must be one of {sorted(CLASSIFICATIONS)}")
    return classification


def scan_text(text: str) -> tuple[SensitiveFinding, ...]:
    findings: list[SensitiveFinding] = []
    seen: set[tuple[str, str]] = set()
    for kind, label, pattern in PATTERNS:
        if pattern.search(text):
            key = (kind, label)
            if key not in seen:
                findings.append(SensitiveFinding(kind=kind, label=label))
                seen.add(key)
    return tuple(findings)


def redact_text(text: str) -> tuple[str, bool]:
    redacted = text
    changed = False
    for kind, _label, pattern in PATTERNS:
        redacted, count = pattern.subn(f"[REDACTED:{kind}]", redacted)
        changed = changed or count > 0
    return redacted, changed


def classify_text(text: object, requested: str | None = None) -> SensitiveReport:
    value = "" if text is None else str(text)
    requested_classification = normalize_classification(requested)
    findings = scan_text(value)
    redacted, changed = redact_text(value)
    if requested_classification == "RED" or findings:
        classification = "RED"
    else:
        classification = requested_classification or "GREEN"
    return SensitiveReport(
        classification=classification,
        findings=findings,
        redacted_text=redacted,
        changed=changed,
    )


def is_red(text: object, requested: str | None = None) -> bool:
    return classify_text(text, requested).classification == "RED"


def public_findings(text: object) -> list[dict[str, str]]:
    return [finding.public_dict() for finding in scan_text("" if text is None else str(text))]
