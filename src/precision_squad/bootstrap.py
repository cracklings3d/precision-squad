"""Interactive bootstrap helpers for consuming projects."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .cli import _install_skill, build_parser


def build_bootstrap_parser() -> argparse.ArgumentParser:
    """Build the bootstrap-skill parser."""
    parser = argparse.ArgumentParser(
        prog="precision-squad-bootstrap-skill",
        description="Install the precision-squad project skill into a consuming repository.",
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Project root where SKILL.md should be written.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing SKILL.md file.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the interactive skill bootstrap flow."""
    parser = build_bootstrap_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    project_root = Path(args.project_root).resolve()
    skill_path = project_root / "SKILL.md"

    print("This bootstrap will install the precision-squad project skill.")
    print(f"Target project root: {project_root}")
    print(f"Target file: {skill_path}")
    if args.force:
        print("Overwrite mode: enabled")
    print("What will happen:")
    print("- A project-local SKILL.md file will be written.")
    print("- No other project files will be modified.")
    print("- Existing SKILL.md files are left alone unless --force is used.")

    if not args.yes:
        response = input("Continue and install the skill? [y/N]: ").strip().lower()
        if response not in {"y", "yes"}:
            print("Bootstrap cancelled. No files were changed.")
            return 0

    install_args = build_parser().parse_args(
        [
            "install-skill",
            "--project-root",
            str(project_root),
            *( ["--force"] if args.force else [] ),
        ]
    )

    try:
        return _install_skill(install_args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
