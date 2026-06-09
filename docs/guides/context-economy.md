# Context Economy Operator Guide

Use this page when the next step is inspection. The goal is to find the few
files worth reading while keeping repo state out of the transcript.

## Repo Map

```bash
python3 scripts/context/repo_map.py --root . --max-files 120 --max-depth 4 2>&1 | head -c 6000
```

For a narrower surface:

```bash
rg --files AGENTS.md .codex/hooks scripts tests 2>&1 | head -c 6000
```

## Logs And Text Needles

```bash
python3 scripts/context/compact_logs.py ~/.ralph-codex/projects/example/log.txt --keyword fallback_used --limit 30 2>&1 | head -c 6000
```

The tool skips generated output, media files, and runtime-heavy directories. It
reads bounded prefixes only.

## JSON And CSV

```bash
python3 scripts/context/summarize_json.py report.json 2>&1 | head -c 6000
python3 scripts/context/summarize_data.py metrics.csv 2>&1 | head -c 6000
```

These commands return shape, columns, sampled rows, and short matching lines.
Open the raw file only after the summary names the exact area to inspect.

## Command Output Bounds

Use a byte cap when output size is unknown:

```bash
COMMAND 2>&1 | head -c 6000
```

For files, prefer ranged reads:

```bash
sed -n '1,160p' path/to/file.py
```

Avoid full-file display commands for large files, generated assets, archived
sessions, runtime memory dumps, and binary/media artifacts.

## Continuity

Runtime continuity belongs under Ralph runtime paths:

```text
~/.ralph-codex/projects/<project_id>/handoffs/latest.md
```

Do not create repo-root handoff files for durable memory unless a project-level
contract explicitly requires that path.
