"""Interactive bootstrap helpers for consuming projects."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .deploy import (
    BootstrapPrerequisiteError,
    ManagedFileConflict,
    WriteOutcome,
    check_bootstrap_prerequisites,
    describe_outcome,
    save_bootstrap_metadata,
    write_managed_surface,
)


def build_bootstrap_parser() -> argparse.ArgumentParser:
    """Build the bootstrap-skill parser."""
    parser = argparse.ArgumentParser(
        prog="precision-squad-bootstrap-skill",
        description="Bootstrap a consuming project with precision-squad skill and config.",
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Project root where SKILL.md and .precision-squad/ should be written.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing unmanaged SKILL.md if it differs from the managed template.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt.",
    )
    return parser


def _print_dry_run(project_root: Path) -> None:
    """Print what would happen during a bootstrap run."""
    print("This bootstrap will install the precision-squad project skill and config.")
    print(f"Target project root: {project_root}")
    print("What will happen:")
    print("- A project-local SKILL.md file will be written.")
    print("- A .precision-squad/precision-squad.toml config file will be written.")
    print("- A .precision-squad/bootstrap/ metadata directory will be created.")
    print("- No other project files will be modified.")
    print("")
    print("Managed files are bounded to:")
    print("  - ./SKILL.md")
    print("  - ./.precision-squad/precision-squad.toml")
    print("  - ./.precision-squad/bootstrap/**")
    print("")
    print("Existing user-managed files will NOT be overwritten.")


def _print_results(outcomes: dict[str, WriteOutcome]) -> None:
    """Print bootstrap results."""
    print("")
    print("Bootstrap completed.")
    print("Results:")
    for path_str, outcome in outcomes.items():
        print(f"  {path_str}: {describe_outcome(outcome)}")


def _confirm_bootstrap(project_root: Path) -> bool:
    """Ask for bootstrap confirmation."""
    print("")
    response = input("Continue and bootstrap the project? [y/N]: ").strip().lower()
    if response not in {"y", "yes"}:
        print("Bootstrap cancelled. No files were changed.")
        return False
    return True


def main(argv: Sequence[str] | None = None) -> int:
    """Run the interactive skill bootstrap flow."""
    parser = build_bootstrap_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    project_root = Path(args.project_root).resolve()

    print("precision-squad bootstrap")
    print(f"Project root: {project_root}")

    _print_dry_run(project_root)

    if not args.yes:
        if not _confirm_bootstrap(project_root):
            return 0

    try:
        check_bootstrap_prerequisites(project_root)
    except BootstrapPrerequisiteError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        outcomes = write_managed_surface(project_root, force=args.force)
        save_bootstrap_metadata(project_root, outcomes)
    except ManagedFileConflict as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except BootstrapPrerequisiteError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Bootstrap failed: {exc}", file=sys.stderr)
        return 1

    _print_results(outcomes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
