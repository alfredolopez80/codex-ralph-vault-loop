from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".codex" / "hooks"))

from shared.context_budget import classify_command, classify_patch_payload, classify_prompt, text_is_toxic, toxic_text_reasons  # noqa: E402


def long_alpha_payload() -> str:
    return "".join(["A"] * 4100)


def test_detects_base64_data_image_and_long_lines() -> None:
    data_uri_prefix = "data:" + "image/png;" + "base64,"
    assert classify_prompt(data_uri_prefix + long_alpha_payload())
    assert text_is_toxic("prefix " + long_alpha_payload() + " suffix")
    assert toxic_text_reasons("x" * 21, line_limit=20) == ["single line exceeds safe transcript length"]


def test_allows_normal_code_snippets() -> None:
    snippet = "def add(a, b):\n    return a + b\n"
    assert not text_is_toxic(snippet)
    assert classify_prompt(snippet) is None


def test_classifies_binary_and_large_file_display(tmp_path: Path) -> None:
    image = tmp_path / "image.png"
    image.write_bytes(b"not really an image")
    huge = tmp_path / "huge.json"
    huge.write_text("x" * 70000, encoding="utf-8")

    binary = classify_command(f"cat {image}", tmp_path)
    large = classify_command(f"cat {huge}", tmp_path)
    chained_large = classify_command(f"printf before && cat {huge}", tmp_path)

    assert binary and binary.reason_code == "binary_display"
    assert large and large.reason_code == "large_file_display"
    assert chained_large and chained_large.reason_code == "large_file_display"
    assert large.suggested_command and "sed" in large.suggested_command


def test_blocks_base64_encode_but_allows_decode(tmp_path: Path) -> None:
    assert classify_command("base64 fixture.png", tmp_path)
    assert classify_command("base64 --decode fixture.b64", tmp_path) is None
    assert classify_command("base64 -d fixture.b64", tmp_path) is None
    assert classify_command("printf safe | base64", tmp_path)
    assert classify_command("env SAMPLE=1 base64 fixture.png", tmp_path)
    assert classify_command("true && base64 fixture.png", tmp_path)


def test_blocks_high_risk_broad_rg_but_allows_targeted_repo_search(tmp_path: Path) -> None:
    broad = classify_command("rg -n context ~/.codex", tmp_path)
    targeted = classify_command("rg -n context docs .codex/hooks", tmp_path)

    assert broad and broad.reason_code == "broad_rg_high_risk_root"
    assert broad.suggested_command
    assert targeted is None


def test_blocks_full_file_python_print_and_toxic_patch(tmp_path: Path) -> None:
    command = "python3 -c 'print(open(\"huge.json\")." + "read())'"
    assert classify_command(command, tmp_path)
    patch = "*** Begin Patch\n+" + long_alpha_payload() + "\n*** End Patch"
    assert classify_patch_payload(patch)


def test_allows_printf_database_url_template_patch() -> None:
    scheme = "postgres"
    formatter = "%" + "s"
    template = scheme + "://" + formatter + ":" + formatter + "@host/db"
    user_argument = "$" + "user"
    credential_argument = "$" + "credential"
    patch = (
        "*** Begin Patch\n"
        "*** Update File: deploy/scripts/provision-control-api-runtime-roles.sh\n"
        "+printf '" + template + "' " + user_argument + " " + credential_argument + "\n"
        "*** End Patch"
    )

    assert classify_patch_payload(patch) is None
