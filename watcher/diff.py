"""
Change detection: compare current Sporty fixtures against the saved snapshot.

The snapshot tracks the last-known state of every fixture by its Sporty Id.
Each run compares the freshly fetched fixtures against the snapshot and
produces a list of ChangeEvent objects describing what happened.

Critical rule: compare against the MOST RECENT snapshot, not an original
baseline — fixtures can change multiple times in a week and each change
must be independently reported.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Fields we consider "material" — a change to any of these fires an alert
MATERIAL_FIELDS = ["From", "VenueId", "VenueName", "HomeTeamId", "AwayTeamId", "StatusName"]
CANCELLED_STATUSES = {"Cancelled", "Postponed", "Abandoned"}


@dataclass
class ChangeEvent:
    fixture_id: int
    grade_id: int
    change_type: str        # "new" | "changed" | "cancelled" | "reverted"
    fixture: dict           # current fixture data
    old_fixture: Optional[dict] = None  # previous fixture data (None for "new")
    changed_fields: list[str] = field(default_factory=list)


def diff_fixtures(
    current: list[dict],
    snapshot: dict[str, dict],  # keyed by str(fixture["Id"])
) -> tuple[list[ChangeEvent], dict[str, dict]]:
    """
    Compare current fixtures against snapshot.

    Returns:
        (changes, new_snapshot)
        - changes: list of ChangeEvent
        - new_snapshot: updated snapshot to save for next run
    """
    changes: list[ChangeEvent] = []
    new_snapshot: dict[str, dict] = {}

    current_by_id: dict[str, dict] = {str(f["Id"]): f for f in current}

    # Check for new fixtures and changes
    for fid, fx in current_by_id.items():
        new_snapshot[fid] = fx
        old_fx = snapshot.get(fid)

        if old_fx is None:
            # Brand new fixture — announce it
            logger.info("New fixture detected: %s", fid)
            changes.append(ChangeEvent(
                fixture_id=fx["Id"],
                grade_id=fx.get("GradeId", 0),
                change_type="new",
                fixture=fx,
            ))
            continue

        # Check for cancellation
        current_status = fx.get("StatusName", "")
        old_status = old_fx.get("StatusName", "")
        if current_status in CANCELLED_STATUSES and old_status not in CANCELLED_STATUSES:
            logger.info("Fixture %s cancelled (was %s)", fid, old_status)
            changes.append(ChangeEvent(
                fixture_id=fx["Id"],
                grade_id=fx.get("GradeId", 0),
                change_type="cancelled",
                fixture=fx,
                old_fixture=old_fx,
            ))
            continue

        # Check for reversion from cancelled back to active
        if old_status in CANCELLED_STATUSES and current_status not in CANCELLED_STATUSES:
            logger.info("Fixture %s reinstated (was cancelled)", fid)
            changes.append(ChangeEvent(
                fixture_id=fx["Id"],
                grade_id=fx.get("GradeId", 0),
                change_type="reverted",
                fixture=fx,
                old_fixture=old_fx,
            ))
            continue

        # Check material field changes
        changed_fields = []
        for field_name in MATERIAL_FIELDS:
            old_val = old_fx.get(field_name)
            new_val = fx.get(field_name)
            if old_val != new_val:
                changed_fields.append(field_name)

        if changed_fields:
            logger.info("Fixture %s changed fields: %s", fid, changed_fields)
            changes.append(ChangeEvent(
                fixture_id=fx["Id"],
                grade_id=fx.get("GradeId", 0),
                change_type="changed",
                fixture=fx,
                old_fixture=old_fx,
                changed_fields=changed_fields,
            ))

    # Note: we don't track fixtures disappearing entirely — that's rare and
    # usually means a scheduling error. If StatusName is present, use that instead.

    if not changes:
        logger.info("No fixture changes detected")

    return changes, new_snapshot
