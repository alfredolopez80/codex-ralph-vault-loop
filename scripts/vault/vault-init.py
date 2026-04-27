#!/usr/bin/env python3
from __future__ import annotations

import argparse

from _vault_common import copy_vault_templates, default_agent, default_project, init_vault, vault_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize the local Ralph vault structure.")
    parser.add_argument("--project", default=default_project())
    parser.add_argument("--agent", default=default_agent())
    args = parser.parse_args()

    created = init_vault(args.project, args.agent)
    templates = copy_vault_templates()
    print(f"VAULT_INIT_OK {vault_dir()}")
    for directory in created:
        print(directory)
    for template in templates:
        print(f"VAULT_TEMPLATE_OK {template}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
