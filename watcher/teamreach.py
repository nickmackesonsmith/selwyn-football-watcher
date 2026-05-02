"""
TeamReach API client.

Reverse-engineered from iOS app traffic (Stream proxy, 2026-05-01).

Confirmed endpoints (all POST to https://appserv.teamreach.com/369/):
  group_events.php          — list events
  group_events_create.php   — create event (multipart/form-data)
  group_events_update.php   — update or delete event (action=update|delete)
  group_messages.php        — list messages
  group_message_post.php    — post new message (inferred from naming pattern)
  group_comment_post.php    — post comment on a message

Auth: every request includes uid + token params.
Token is long-lived; stored as TEAMREACH_TOKEN GitHub secret.
UID is Nick's user ID (3594459); stored as TEAMREACH_UID.
"""

import logging
import os
from datetime import datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)

BASE = "https://appserv.teamreach.com/369"
APP_ID = "teamreach"

# Group IDs confirmed from grouplist_user.php (2026-05-01)
GROUPS: dict[str, str] = {
    "2ndxi": "805225",
    "13a": "805064",
}

_DEFAULT_UID = os.environ.get("TEAMREACH_UID", "3594459")
_DEFAULT_TOKEN = os.environ.get("TEAMREACH_TOKEN", "")


class TeamReachError(Exception):
    """Raised when the TeamReach API returns an unexpected response."""


def _request(
    path: str,
    params: dict,
    multipart: bool = False,
    timeout: int = 20,
) -> dict:
    """POST to a TeamReach API endpoint and return the parsed JSON response."""
    url = f"{BASE}/{path.lstrip('/')}"
    try:
        if multipart:
            # event create uses multipart/form-data
            resp = requests.post(
                url,
                files={k: (None, str(v)) for k, v in params.items()},
                timeout=timeout,
            )
        else:
            resp = requests.post(url, data=params, timeout=timeout)

        resp.raise_for_status()

        ct = resp.headers.get("Content-Type", "")
        if "json" in ct:
            result = resp.json()
            # Some endpoints (e.g. group_events_create.php) return JSON null on
            # success — treat that as rc=0 rather than propagating None upward.
            if result is None:
                return {"rc": 0}
            return result
        # Some endpoints return XML (e.g. push registration) — treat as success
        return {"rc": 0, "raw": resp.text}

    except requests.RequestException as exc:
        raise TeamReachError(f"Request to {path} failed: {exc}") from exc


def _base_params(uid: Optional[str] = None, token: Optional[str] = None) -> dict:
    """Build the common auth params included in every request."""
    return {
        "i": APP_ID,
        "uid": uid or _DEFAULT_UID,
        "token": token or _DEFAULT_TOKEN,
    }


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

def post_message(
    group_id: str,
    message: str,
    uid: Optional[str] = None,
    token: Optional[str] = None,
) -> str:
    """
    Post a new message to a group's feed.

    Returns the new message ID (msid) as a string.
    Raises TeamReachError on failure.

    Endpoint confirmed from HAR capture: group_message_create.php
    Uses multipart/form-data (same as event create and message-with-image).
    """
    p = _base_params(uid, token)
    p.update({
        "gid": group_id,
        "msg": message,
        "tz": "Pacific/Auckland",
        "is_comments_on": "0",
        "is_schedule_on": "0",
        "is_direct_message": "0",
    })
    data = _request("group_message_create.php", p, multipart=True)
    if data.get("rc", -1) != 0:
        raise TeamReachError(f"post_message failed (rc={data.get('rc')}): {data}")
    msid = str(data.get("msid", ""))
    logger.info("Posted message to group %s → msid=%s", group_id, msid)
    return msid


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def list_events(
    group_id: str,
    uid: Optional[str] = None,
    token: Optional[str] = None,
) -> list[dict]:
    """Return all events (past and upcoming) for the given group."""
    p = _base_params(uid, token)
    p.update({
        "gid": group_id,
        "eid": "0",
        "tz": "Pacific/Auckland",
        "ts": "0",
        "rmets": "",
    })
    data = _request("group_events.php", p)
    return data.get("events", [])


def create_event(
    group_id: str,
    title: str,
    event_time: datetime,
    end_time: datetime,
    location: str,
    address: str,
    lat: float,
    lng: float,
    details: str = "",
    attendance: bool = True,
    uid: Optional[str] = None,
    token: Optional[str] = None,
) -> str:
    """
    Create a calendar event in a group.

    Returns the new event ID (eid) as a string.
    Raises TeamReachError on failure.

    Uses multipart/form-data, matching observed iOS app behaviour.
    The double-slash path (/369//group_events_create.php) also matches
    exactly what the app sends.
    """
    fmt = "%Y-%m-%d %H:%M:%S"
    p = _base_params(uid, token)
    p.update({
        "gid": group_id,
        "title": title,
        "event_time": event_time.strftime(fmt),
        "event_end_time": end_time.strftime(fmt),
        "location": location,
        "address": address,
        "latitude": f"{lat:.6f}",
        "longitude": f"{lng:.6f}",
        "event_details": details,
        "tz": "Pacific/Auckland",
        "is_forecast_on": "1",
        "is_attendance_set": "1" if attendance else "0",
        "is_who_available_set": "1",
        "reoccurring": "None",
        "is_all_day": "0",
        "map_type": "roadmap",
        "label1": "",
        "value1": "",
        "label2": "",
        "value2": "",
    })
    # Note: double slash in path matches observed app URL (/369//group_events_create.php)
    data = _request("/group_events_create.php", p, multipart=True)
    if data.get("rc", -1) != 0:
        raise TeamReachError(f"create_event failed (rc={data.get('rc')}): {data}")
    eid = str(data.get("eid", ""))
    if not eid:
        # TR sometimes returns null/empty body on successful event creation
        # (observed in prod May 2026). Log a warning so we know to watch for it,
        # but don't crash — the event was likely created successfully.
        logger.warning("create_event: API returned no eid for group=%s title=%r — event may still exist", group_id, title)
    else:
        logger.info("Created event in group %s → eid=%s %r", group_id, eid, title)
    return eid


def update_event(
    group_id: str,
    event_id: str,
    title: str,
    event_time: datetime,
    end_time: datetime,
    location: str,
    address: str,
    lat: float,
    lng: float,
    details: str = "",
    uid: Optional[str] = None,
    token: Optional[str] = None,
) -> bool:
    """
    Update an existing event's details.

    Returns True on success.
    """
    fmt = "%Y-%m-%d %H:%M:%S"
    p = _base_params(uid, token)
    p.update({
        "action": "update",
        "gid": group_id,
        "eid": event_id,
        "dt": "0",
        "title": title,
        "event_time": event_time.strftime(fmt),
        "event_end_time": end_time.strftime(fmt),
        "location": location,
        "address": address,
        "latitude": f"{lat:.6f}",
        "longitude": f"{lng:.6f}",
        "event_details": details,
        "tz": "Pacific/Auckland",
        "is_forecast_on": "1",
        "is_attendance_set": "1",
        "is_who_available_set": "1",
        "reoccurring": "None",
        "is_all_day": "0",
        "map_type": "roadmap",
    })
    data = _request("group_events_update.php", p)
    ok = data.get("rc", -1) == 0
    logger.info("Updated event group=%s eid=%s ok=%s", group_id, event_id, ok)
    return ok


def delete_event(
    group_id: str,
    event_id: str,
    uid: Optional[str] = None,
    token: Optional[str] = None,
) -> bool:
    """
    Delete an event from the group calendar.

    Returns True on success.
    """
    p = _base_params(uid, token)
    p.update({
        "action": "delete",
        "gid": group_id,
        "eid": event_id,
        "dt": "0",
    })
    data = _request("group_events_update.php", p)
    ok = data.get("rc", -1) == 0
    logger.info("Deleted event group=%s eid=%s ok=%s", group_id, event_id, ok)
    return ok
