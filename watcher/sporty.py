"""Sporty API client for fetching College Sport fixtures."""

import logging
import time
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

SPORTY_BASE = "https://www.sporty.co.nz"
FIXTURE_DATES_URL = f"{SPORTY_BASE}/api/v2/competition/widget/fixture/Dates"
RECENT_RESULTS_URL = f"{SPORTY_BASE}/api/v2/competition/widget/fixture/RecentResults"
STANDINGS_URL = f"{SPORTY_BASE}/api/v2/competition/widget/standings/Phase/Table"

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.sporty.co.nz/collegesport/draws-results",
    "Origin": "https://www.sporty.co.nz",
}

SELWYN_ORG_ID = 11255
COMP_IDS = [12756, 12758]  # Football Boys Season + Knockout Cup
SEASON_FROM = "2026-04-01T00:00:00"
SEASON_TO = "2026-09-30T23:59:59"


def _post_with_retry(url: str, payload: Any, retries: int = 2) -> dict:
    """POST to a Sporty endpoint, retrying once on failure."""
    for attempt in range(retries + 1):
        try:
            resp = requests.post(url, json=payload, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            if attempt < retries:
                logger.warning("Sporty request failed (attempt %d): %s — retrying in 30s", attempt + 1, exc)
                time.sleep(30)
            else:
                raise


def fetch_fixtures(grade_ids: list[int]) -> list[dict]:
    """
    Fetch all season fixtures for the given grade IDs.

    Returns a list of fixture dicts from the Sporty API.
    Raises on network/API failure after retries.
    """
    payload = {
        "CompIds": COMP_IDS,
        "OrgIds": [SELWYN_ORG_ID],
        "GradeIds": grade_ids,
        "From": SEASON_FROM,
        "To": SEASON_TO,
    }
    logger.info("Fetching fixtures for grade IDs %s", grade_ids)
    data = _post_with_retry(FIXTURE_DATES_URL, payload)
    fixtures = data.get("Fixtures") or []
    logger.info("Received %d fixtures", len(fixtures))
    return fixtures


def fetch_recent_results(grade_ids: list[int]) -> list[dict]:
    """Fetch recently completed fixtures (with scores) for the given grade IDs."""
    payload = {
        "CompIds": COMP_IDS,
        "OrgIds": [SELWYN_ORG_ID],
        "GradeIds": grade_ids,
        "From": SEASON_FROM,
        "To": SEASON_TO,
    }
    logger.info("Fetching recent results for grade IDs %s", grade_ids)
    data = _post_with_retry(RECENT_RESULTS_URL, payload)
    fixtures = data.get("Fixtures") or []
    # Keep only completed ones (StatusName == "Result" or score is set)
    completed = [
        f for f in fixtures
        if f.get("HomeScore") is not None and f.get("AwayScore") is not None
    ]
    logger.info("Found %d completed results", len(completed))
    return completed


def fetch_standings(comp_id: int, grade_id: int) -> list[dict]:
    """Fetch league table standings for a competition/grade."""
    payload = {
        "CompIds": [comp_id],
        "GradeIds": [grade_id],
        "OrgIds": [SELWYN_ORG_ID],
        "From": SEASON_FROM,
        "To": SEASON_TO,
    }
    logger.info("Fetching standings for comp %d, grade %d", comp_id, grade_id)
    try:
        data = _post_with_retry(STANDINGS_URL, payload)
        return data.get("Standings") or data.get("Phases") or []
    except Exception as exc:
        logger.warning("Could not fetch standings: %s", exc)
        return []


def opponent_name(fixture: dict) -> str:
    """
    Return a clean opponent name.
    Prefer OrgName over TeamName — some schools enter just '2nd XI'
    without a school prefix, making raw TeamName useless.
    """
    is_home = fixture.get("HomeOrganisationId") == SELWYN_ORG_ID
    if is_home:
        org = fixture.get("AwayOrgName") or fixture.get("AwayTeamName") or "Unknown"
    else:
        org = fixture.get("HomeOrgName") or fixture.get("HomeTeamName") or "Unknown"
    return org.strip()


def is_home_game(fixture: dict) -> bool:
    """Return True if Selwyn is the home team."""
    return fixture.get("HomeOrganisationId") == SELWYN_ORG_ID


def is_school_day(fixture: dict) -> bool:
    """Return True if the fixture falls on a weekday (Mon-Fri)."""
    ko = kickoff_dt(fixture)
    return ko.weekday() < 5  # 0=Monday, 4=Friday


def kickoff_dt(fixture: dict) -> datetime:
    """Parse the kick-off datetime from the fixture, returning a timezone-aware NZ datetime."""
    from dateutil import parser
    import pytz
    nz = pytz.timezone("Pacific/Auckland")
    dt_str = fixture.get("From", "")
    dt = parser.parse(dt_str)
    if dt.tzinfo is None:
        dt = nz.localize(dt)
    else:
        dt = dt.astimezone(nz)
    return dt


def maps_link(fixture: dict) -> str | None:
    """Return a Google Maps URL for the fixture venue, or None for home games."""
    if is_home_game(fixture):
        return None
    lat = fixture.get("LocationLat")
    lng = fixture.get("LocationLng")
    if lat is None or lng is None:
        return None
    return f"https://maps.google.com/?q={lat},{lng}"
