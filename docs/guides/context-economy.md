# Context Economy Operator Guide

Use these commands when the next step is inspection, not implementation.

## Repo Map

```bash
python3 scripts/maintenance/needle-map.py --mode repo --root .
```

For a narrower surface:

```bash
rg --files AGENTS.md .codex/hooks scripts tests 2>&1 | head -c 6000
```

## Logs And Text Needles

```bash
python3 scripts/maintenance/needle-map.py --mode logs --root ~/.ralph-codex --needle "fallback_used"
```

The tool skips noisy, generated, binary, and runtime-heavy paths by default and
reads only bounded prefixes of candidate files.

## JSON And CSV

```bash
python3 scripts/maintenance/needle-map.py --mode json --path report.json --needle "selected_memory_ids"
python3 scripts/maintenance/needle-map.py --mode csv --path metrics.csv --needle "latency"
```

These commands report shape, columns, sampled rows, and compact matching lines
instead of dumping the full file into the transcript.

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

Runtime continuity belongs under Ralph runtime paths, for example:

```text
~/.ralph-codex/projects/<project_id>/handoffs/latest.md
```

Do not create repo-root handoff files for durable memory unless a project-level
contract explicitly requires that path.
