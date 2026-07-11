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
_RUNTIME_DB_PASSWORD_REF = r"(?:\$\{[A-Za-z_][A-Za-z0-9_]*\}|\$[A-Za-z_][A-Za-z0-9_]*)"
_DB_URL_START = re.compile(r"(?i)\b" + _DB_SCHEMES + r"://")
_DB_URL_ASSIGNMENT_START = re.compile(
    r"(?i)\b(?:database_url|db_url|sqlalchemy_database_uri|mongo_uri|redis_url)\s*[:=]\s*['\"]?"
)
_RUNTIME_DB_PASSWORD_REF_FULL = re.compile(_RUNTIME_DB_PASSWORD_REF)
_PRINTF_DB_CREDENTIAL_REF_FULL = re.compile(r"%s")
_WORD = r"[a-z]{3,12}"


def _database_url_authority_end(text: str, start: int) -> int:
    """Return the end of a URL authority, preserving nested command substitutions."""
    depth = 0
    index = start
    while index < len(text):
        if depth:
            if text[index] == "(":
                depth += 1
            elif text[index] == ")":
                depth -= 1
            index += 1
            continue
        if text.startswith("$(", index):
            depth = 1
            index += 2
            continue
        if text[index].isspace() or text[index] in "'\"<>/":
            break
        index += 1
    return index


def _database_url_credential_spans(text: str) -> list[tuple[int, int]]:
    """Find DB URLs whose credential segment is not exactly a runtime variable."""
    spans: list[tuple[int, int]] = []
    for match in _DB_URL_START.finditer(text):
        authority_end = _database_url_authority_end(text, match.end())
        authority = text[match.end() : authority_end]
        separator = authority.rfind("@")
        if separator < 0:
            continue
        userinfo = authority[:separator]
        colon = userinfo.find(":")
        if colon < 0:
            continue
        credential_segment = userinfo[colon + 1 :]
        if (
            _RUNTIME_DB_PASSWORD_REF_FULL.fullmatch(credential_segment)
            or _PRINTF_DB_CREDENTIAL_REF_FULL.fullmatch(credential_segment)
        ):
            continue
        spans.append((match.start(), authority_end))
    return spans


def _database_url_assignment_spans(text: str) -> list[tuple[int, int]]:
    """Find URL-setting assignments except a DB URL with an exact runtime variable."""
    spans: list[tuple[int, int]] = []
    for match in _DB_URL_ASSIGNMENT_START.finditer(text):
        value_start = match.end()
        url_match = _DB_URL_START.match(text, value_start)
        if url_match:
            authority_end = _database_url_authority_end(text, url_match.end())
            authority = text[url_match.end() : authority_end]
            separator = authority.rfind("@")
            if separator >= 0:
                userinfo = authority[:separator]
                colon = userinfo.find(":")
                credential_segment = userinfo[colon + 1 :] if colon >= 0 else None
                if credential_segment is not None and (
                    _RUNTIME_DB_PASSWORD_REF_FULL.fullmatch(credential_segment)
                    or _PRINTF_DB_CREDENTIAL_REF_FULL.fullmatch(credential_segment)
                ):
                    continue
            # The credentialed URL is redacted by _database_url_credential_spans.
            continue
        value_end = value_start
        while value_end < len(text) and not text[value_end].isspace() and text[value_end] not in "'\"":
            value_end += 1
        if value_end > value_start:
            spans.append((match.start(), value_end))
    return spans


def _database_url_findings(text: str) -> list[tuple[str, tuple[int, int]]]:
    findings = [("database_url_with_credentials", span) for span in _database_url_credential_spans(text)]
    findings.extend(("database_url_assignment", span) for span in _database_url_assignment_spans(text))
    return findings


def _replace_spans(text: str, spans: list[tuple[int, int]], replacement: str) -> tuple[str, bool]:
    redacted = text
    changed = False
    for start, end in sorted(set(spans), reverse=True):
        redacted = redacted[:start] + replacement + redacted[end:]
        changed = True
    return redacted, changed

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
    for label, _span in _database_url_findings(text):
        key = ("database_url", label)
        if key not in seen:
            findings.append(SensitiveFinding(kind="database_url", label=label))
            seen.add(key)
    return tuple(findings)


def redact_text(text: str) -> tuple[str, bool]:
    database_spans = [span for _label, span in _database_url_findings(text)]
    redacted, changed = _replace_spans(text, database_spans, "[REDACTED:database_url]")
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
