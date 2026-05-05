from __future__ import annotations

from typing import Any


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value in {"true", "false"}:
        return value == "true"
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value.strip('"').strip("'")


def safe_load(text: str) -> dict[str, Any]:
    """Small YAML subset parser for this repo's scorecard files."""
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]
    last_key_at_indent: dict[int, tuple[Any, str]] = {}
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if line.startswith("- "):
            while stack and indent < stack[-1][0]:
                stack.pop()
        else:
            while stack and indent <= stack[-1][0]:
                stack.pop()
        parent = stack[-1][1]
        if line.startswith("- "):
            if not isinstance(parent, list):
                container, key = last_key_at_indent[indent]
                parent = []
                container[key] = parent
                stack.append((indent, parent))
            parent.append(_parse_scalar(line[2:]))
            continue
        key, separator, value = line.partition(":")
        if not separator:
            raise ValueError(f"unsupported YAML line: {raw_line}")
        if not isinstance(parent, dict):
            raise ValueError(f"mapping line under non-mapping parent: {raw_line}")
        key = key.strip()
        if value.strip():
            parent[key] = _parse_scalar(value)
            last_key_at_indent[indent + 2] = (parent, key)
        else:
            container: dict[str, Any] = {}
            parent[key] = container
            stack.append((indent, container))
            last_key_at_indent[indent + 2] = (parent, key)
    return root
