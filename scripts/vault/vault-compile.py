#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from _vault_common import default_project, iter_markdown_files, sanitize_slug, vault_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile project vault notes into one handoff file.")
    parser.add_argument("--project", default=default_project())
    parser.add_argument("--output")
    args = parser.parse_args()

    root = vault_dir()
    project = sanitize_slug(args.project)
    source_root = root / "projects" / project
    output = Path(args.output) if args.output else source_root / "handoffs" / "compiled.md"
    output.parent.mkdir(parents=True, exist_ok=True)

    sections = [f"# Compiled Vault Notes - {project}", ""]
    for path in iter_markdown_files(source_root):
        if path == output:
            continue
        sections.extend([f"## {path.relative_to(root)}", "", path.read_text(encoding="utf-8").strip(), ""])

    output.write_text("\n".join(sections).rstrip() + "\n", encoding="utf-8")
    print(f"VAULT_COMPILE_OK {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
