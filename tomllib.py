from __future__ import annotations

from typing import Any


def _parse_value(value: str) -> Any:
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value in {"true", "false"}:
        return value == "true"
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def loads(text: str) -> dict[str, Any]:
    """Small TOML subset parser for this repo's agent/config files on Python 3.9."""
    root: dict[str, Any] = {}
    current = root
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        raw_line = lines[index]
        index += 1
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = root
            for part in line[1:-1].split("."):
                current = current.setdefault(part, {})
            continue
        key, separator, value = line.partition("=")
        if not separator:
            raise ValueError(f"unsupported TOML line: {raw_line}")
        key = key.strip()
        value = value.strip()
        if value == '"""':
            chunks: list[str] = []
            while index < len(lines):
                next_line = lines[index]
                index += 1
                if next_line.strip() == '"""':
                    break
                chunks.append(next_line)
            current[key] = "\n".join(chunks)
        elif value.startswith("[") and not value.endswith("]"):
            items: list[Any] = []
            while index < len(lines):
                next_line = lines[index].strip()
                index += 1
                if next_line == "]":
                    break
                if next_line and not next_line.startswith("#"):
                    items.append(_parse_value(next_line.rstrip(",")))
            current[key] = items
        elif value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            current[key] = [] if not inner else [_parse_value(item.strip()) for item in inner.split(",")]
        else:
            current[key] = _parse_value(value)
    return root


def load(handle: Any) -> dict[str, Any]:
    data = handle.read()
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    return loads(data)
