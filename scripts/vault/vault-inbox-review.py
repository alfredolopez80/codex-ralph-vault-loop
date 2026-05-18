#!/usr/bin/env python3
from __future__ import annotations

import argparse

from _vault_common import default_project
from _vault_graduation import review


def main() -> int:
    parser = argparse.ArgumentParser(description="Review MiVault project inbox candidates without canonical promotion.")
    parser.add_argument("--project", default=default_project())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = review(args.project, apply=False)
    if args.json:
        import json

        print(json.dumps(report, indent=2, sort_keys=True))
    if report["ask_user"]:
        print(f"GRADUATION_REVIEW_REQUIRED count={report['ask_user']}")
    print(
        "VAULT_INBOX_REVIEW_OK "
        f"auto={report['auto_graduate']} review={report['ask_user']} skipped={report['skipped']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
