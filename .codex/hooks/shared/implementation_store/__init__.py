"""Canonical implementation-progress store core.

This package is deliberately unreferenced by lifecycle dispatchers until the
later integration phase.  Importing it has no filesystem side effects.
"""

from .io import CorruptRecordError, StoreIOError, WriteMetadata
from .paths import (
    PlanPaths,
    StorePathError,
    StorePaths,
    ensure_store_layout,
    resolve_primary_checkout_root,
    resolve_store_paths,
    validate_plan_id,
)
from .schema import (
    CURRENT_SCHEMA_VERSION,
    STATE_HARD_LIMIT_BYTES,
    STATE_PATCH_KEYS,
    STATE_TARGET_BYTES,
    STATE_WARNING_BYTES,
    MATERIAL_EVENT_KINDS,
    FutureSchemaError,
    RedContentError,
    SchemaError,
    event_record_hash,
    new_state,
    state_semantic_hash,
    state_size_band,
    validate_event,
    validate_manifest,
    validate_operation_id,
    validate_state,
)
from .store import IdempotencyError, ImplementationStore, IntegrityError, StoreError, StoreResult

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "STATE_HARD_LIMIT_BYTES",
    "STATE_PATCH_KEYS",
    "STATE_TARGET_BYTES",
    "STATE_WARNING_BYTES",
    "CorruptRecordError",
    "FutureSchemaError",
    "IdempotencyError",
    "ImplementationStore",
    "IntegrityError",
    "MATERIAL_EVENT_KINDS",
    "PlanPaths",
    "RedContentError",
    "SchemaError",
    "StoreError",
    "StoreIOError",
    "StorePathError",
    "StorePaths",
    "StoreResult",
    "WriteMetadata",
    "ensure_store_layout",
    "event_record_hash",
    "new_state",
    "resolve_primary_checkout_root",
    "resolve_store_paths",
    "state_semantic_hash",
    "state_size_band",
    "validate_event",
    "validate_manifest",
    "validate_operation_id",
    "validate_plan_id",
    "validate_state",
]
