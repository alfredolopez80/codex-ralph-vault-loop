from __future__ import annotations

try:
    from .context_common import *  # noqa: F403
except ImportError:  # pragma: no cover - direct script-path compatibility
    from context_common import *  # noqa: F403
