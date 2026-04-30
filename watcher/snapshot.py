"""
Snapshot management — read/write the fixture state persisted in snapshot.json.

The snapshot is committed back to the repo after each run so the next run
can diff against the most recent state.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SNAPSHOT_PATH = Path("snapshot.json")


def load_snapshot() -> dict[str, dict]:
    """
    Load the snapshot from snapshot.json.

    Returns an empty dict if the file doesn't exist or is corrupt.
    On first run this is normal — all fixtures will be treated as "new".
    """
    if not SNAPSHOT_PATH.exists():
        logger.info("No snapshot found — treating all fixtures as new")
        return {}

    try:
        data = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Snapshot is not a dict")
        logger.info("Loaded snapshot with %d fixtures", len(data))
        return data
    except Exception as exc:
        logger.warning("Could not load snapshot (%s) — starting fresh", exc)
        return {}


def save_snapshot(snapshot: dict[str, dict]) -> None:
    """Write the snapshot to snapshot.json."""
    SNAPSHOT_PATH.write_text(
        json.dumps(snapshot, indent=2, default=str),
        encoding="utf-8",
    )
    logger.info("Saved snapshot with %d fixtures", len(snapshot))
