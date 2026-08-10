from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLANS = ROOT / "scripts" / "plans"
HOOKS = ROOT / ".codex" / "hooks"
import sys

for candidate in (str(PLANS), str(HOOKS)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from progress_context import (  # noqa: E402
    ContextRequest,
    ContextSource,
    SourceResolution,
    derive_context_epoch,
    emit_context,
    legacy_fallback,
    render_capsule,
    resolve_context_source,
    select_new_state_source,
)


def source(*, plan_id: str = "demo", generation: int = 4, writer: str = "writer") -> ContextSource:
    return ContextSource(
        plan_id=plan_id,
        state={
            "plan_id": plan_id,
            "generation": generation,
            "status": "active",
            "phase": "verification",
            "objective": "Preserve bounded recovery state without repeating full history.",
            "latest_decision": {"summary": "Use the canonical state and journal as the source."},
            "next_action": "Run the focused recovery and hook-boundary tests.",
            "open_blockers": [],
            "open_questions": [],
            "validation": {"unit": "pass", "integration": "pending"},
            "writer_session_id": writer,
        },
        events=(
            {
                "kind": "decision",
                "summary": "Use the canonical state and journal as the source.",
            },
        ),
    )


class FakeLedger:
    def __init__(self) -> None:
        self.keys: set[tuple[object, ...]] = set()
        self.calls = 0

    def claim_context_emission(self, record: dict[str, object]):
        self.calls += 1
        key = tuple(record[key] for key in ("project_id", "workspace_instance_id", "session_id", "context_epoch", "plan_id", "progress_generation", "capsule_kind"))
        emitted = key not in self.keys
        if emitted:
            self.keys.add(key)
        return type("Claim", (), {"emitted": emitted})()


class FakeStore:
    def __init__(self, states: dict[str, dict[str, object]], manifest: dict[str, object]) -> None:
        self.states = states
        self.manifest = manifest

    def read_manifest(self):
        return self.manifest

    def read_state(self, plan_id: str):
        return self.states.get(plan_id)

    def read_events(self, plan_id: str):
        return ({"kind": "decision", "summary": "state"},)


def request(*, event: str, session: str = "new", epoch: str = "epoch", **kwargs: object) -> ContextRequest:
    return ContextRequest(
        profile="luna",
        verified=True,
        project_id="project",
        workspace_instance_id="workspace",
        session_id=session,
        context_epoch=epoch,
        event=event,
        **kwargs,
    )


def test_source_priority_and_ambiguity_never_falls_back_on_ambiguous_state() -> None:
    states = {
        "one": {"plan_id": "one", "status": "active", "generation": 1},
        "two": {"plan_id": "two", "status": "active", "generation": 2},
    }
    store = FakeStore(
        states,
        {
            "plans": [
                {"plan_id": "one", "status": "active", "workspace_instance_id": "workspace"},
                {"plan_id": "two", "status": "active", "workspace_instance_id": "workspace"},
            ]
        },
    )
    ambiguous = select_new_state_source(store, workspace_instance_id="workspace")
    assert ambiguous.source is None
    assert ambiguous.reason == "ambiguous_active_state"
    fallback_calls = 0

    def fallback():
        nonlocal fallback_calls
        fallback_calls += 1
        return source(plan_id="legacy")

    resolved = resolve_context_source(new_resolution=ambiguous, legacy_loader=fallback)
    assert resolved.source is None
    assert fallback_calls == 0

    single = FakeStore({"one": states["one"]}, {"plans": [{"plan_id": "one", "status": "active", "workspace_instance_id": "workspace"}]})
    selected = select_new_state_source(single, workspace_instance_id="workspace")
    assert selected.reason == "single_active_state"
    assert selected.source and selected.source.source == "state"


def test_legacy_fallback_parses_html_once_and_only_after_new_state_misses(tmp_path: Path) -> None:
    notes = tmp_path / "demo-implementation-notes.html"
    notes.write_text("safe legacy body", encoding="utf-8")
    calls = 0

    def parser(text: str, *, include_summary: bool = False):
        nonlocal calls
        calls += 1
        assert text == "safe legacy body"
        return [
            type(
                "Entry",
                (),
                {
                    "category": "decision",
                    "fields": {
                        "Decision": "Keep recovery bounded.",
                        "Reason": "Avoid history injection.",
                        "Impact": "Recovery remains deterministic.",
                        "Status": "active",
                    },
                },
            )()
        ]

    recovered = legacy_fallback(plan_id="demo", notes_path=notes, parser=parser)
    assert recovered and recovered.source == "legacy"
    assert calls == 1
    assert recovered.state["generation"] == 0


@pytest.mark.parametrize(
    ("profile", "verified", "kind", "byte_limit", "word_limit"),
    [
        ("luna", True, "full", 512, 80),
        ("luna", True, "delta", 256, 35),
        ("luna", True, "expanded", 1024, 180),
        ("terra", True, "full", 192, 32),
        ("sol", True, "full", 96, 40),
        ("unknown", False, "expanded", 96, 40),
    ],
)
def test_capsules_are_stable_labeled_and_within_profile_budgets(profile: str, verified: bool, kind: str, byte_limit: int, word_limit: int) -> None:
    rendered = render_capsule(source(), kind=kind, profile=profile, verified=verified)
    assert len(rendered.encode("utf-8")) <= byte_limit
    assert len(rendered.split()) <= word_limit
    assert "Authority:" in rendered
    assert "/Users/" not in rendered
    assert "sha256:" not in rendered
    assert "Implementation progress" in rendered or "Progress:" in rendered


def test_lifecycle_tiers_and_shared_ledger_dedupe() -> None:
    ledger = FakeLedger()
    current = source(generation=4, writer="old")
    assert not emit_context(current, request(event="ordinary"), ledger=ledger).emitted

    startup = emit_context(current, request(event="startup", session="new", epoch="startup-1"), ledger=ledger)
    assert startup.emitted and startup.capsule_kind == "full"
    retry = emit_context(current, request(event="startup", session="new", epoch="startup-1"), ledger=ledger)
    assert not retry.emitted and retry.ledger_hit and retry.capsule == ""

    compact = emit_context(current, request(event="compact", session="new", epoch="compact-1"), ledger=ledger)
    assert compact.emitted and compact.capsule_kind == "full"
    assert not emit_context(current, request(event="compact", session="new", epoch="compact-1"), ledger=ledger).emitted

    external = emit_context(source(generation=5, writer="old"), request(event="external", session="new", epoch="resume-1", external_writer=True), ledger=ledger)
    assert external.emitted and external.capsule_kind == "delta"

    explicit = emit_context(current, request(event="explicit", session="new", epoch="explicit-1"), ledger=ledger)
    assert explicit.emitted and explicit.capsule_kind == "expanded"
    unknown = emit_context(current, request(event="resume", session="unknown", epoch="resume-unknown"), ledger=ledger)
    assert not unknown.emitted and unknown.reason == "unknown_session"
    same_writer = emit_context(current, request(event="resume", session="old", epoch="resume-old"), ledger=ledger)
    assert not same_writer.emitted and same_writer.reason == "same_session_writer"


def test_context_epoch_boundaries_are_deterministic() -> None:
    assert derive_context_epoch(None, "startup", "session-a") == "startup:session-a"
    assert derive_context_epoch("startup:session-a", "resume", "session-a") == "resume:session-a"
    assert derive_context_epoch("resume:session-a", "compact", "session-a") == "compact:session-a"
    assert derive_context_epoch("compact:session-a", "clear", "session-a") == "reset:session-a"
    assert derive_context_epoch("", "ordinary", "session-a") == "session:session-a"


def test_tight_pointer_budget_keeps_authority_label_without_paths_or_hashes() -> None:
    long_source = ContextSource(
        plan_id="p" * 180,
        state={"status": "active", "phase": "x" * 180, "generation": 99},
    )
    for profile, verified in (("sol", True), ("unknown", False)):
        rendered = render_capsule(long_source, kind="full", profile=profile, verified=verified)
        assert len(rendered.encode("utf-8")) <= 96
        assert "Authority: user instructions/repo files prevail." in rendered
