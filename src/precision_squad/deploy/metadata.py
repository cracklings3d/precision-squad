"""Bootstrap metadata tracking."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from .writer import WriteOutcome


class BootstrapOutcome(Enum):
    """Outcome of a bootstrap operation."""

    SUCCESS = "success"
    NO_OP = "no_op"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass
class BootstrapMetadata:
    """Metadata tracking for bootstrap operations."""

    managed_by: str
    version: str
    last_bootstrap: str
    outcomes: dict[str, str]


def load_bootstrap_metadata(project_root: Path) -> BootstrapMetadata | None:
    """Load bootstrap metadata if it exists.

    Args:
        project_root: The project root directory.

    Returns:
        BootstrapMetadata if bootstrap metadata exists, None otherwise.
    """
    meta_path = project_root / ".precision-squad" / "bootstrap" / "bootstrap.json"
    if not meta_path.exists():
        return None

    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        if data.get("managed_by") != "precision-squad":
            return None
        return BootstrapMetadata(
            managed_by=data.get("managed_by", "precision-squad"),
            version=data.get("version", "1.0"),
            last_bootstrap=data.get("last_bootstrap", ""),
            outcomes=data.get("outcomes", {}),
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def save_bootstrap_metadata(
    project_root: Path,
    outcomes: dict[str, WriteOutcome],
) -> None:
    """Save bootstrap metadata after a successful bootstrap operation.

    Args:
        project_root: The project root directory.
        outcomes: Dictionary mapping file paths to their write outcomes.
    """
    meta_dir = project_root / ".precision-squad" / "bootstrap"
    meta_dir.mkdir(parents=True, exist_ok=True)
    meta_path = meta_dir / "bootstrap.json"

    timestamp = datetime.now(timezone.utc).isoformat()
    outcome_strs = {path: outcome.value for path, outcome in outcomes.items()}

    metadata = BootstrapMetadata(
        managed_by="precision-squad",
        version="1.0",
        last_bootstrap=timestamp,
        outcomes=outcome_strs,
    )

    meta_path.write_text(json.dumps(asdict(metadata), indent=2), encoding="utf-8")
