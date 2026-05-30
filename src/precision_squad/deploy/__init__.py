"""Deploy/bootstrap implementation for precision-squad."""

from __future__ import annotations

from .metadata import (
    BootstrapMetadata,
    BootstrapOutcome,
    load_bootstrap_metadata,
    save_bootstrap_metadata,
)
from .prerequisites import (
    BootstrapPrerequisiteError,
    PrerequisiteChecker,
    check_bootstrap_prerequisites,
)
from .templates import DEFAULT_CONFIG_TEMPLATE, SKILL_TEMPLATE
from .writer import (
    ManagedFileConflict,
    ManagedSurface,
    WriteOutcome,
    describe_outcome,
    write_managed_surface,
)

__all__ = [
    "BootstrapMetadata",
    "BootstrapOutcome",
    "BootstrapPrerequisiteError",
    "DEFAULT_CONFIG_TEMPLATE",
    "ManagedFileConflict",
    "ManagedSurface",
    "PrerequisiteChecker",
    "SKILL_TEMPLATE",
    "WriteOutcome",
    "check_bootstrap_prerequisites",
    "describe_outcome",
    "load_bootstrap_metadata",
    "save_bootstrap_metadata",
    "write_managed_surface",
]
