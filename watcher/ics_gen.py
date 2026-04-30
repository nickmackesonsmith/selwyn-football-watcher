"""
iCalendar (.ics) feed generator.

Produces one .ics file per team containing all season fixtures and
recurring training events. These are hosted on GitHub Pages so
anyone (Nick, coaches) can subscribe in Apple/Google Calendar.

Fixture events use the Sporty fixture Id as a stable UID so that
calendar app updates replace (not duplicate) changed events.
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path

import pytz
from icalendar import Calendar, Event, vText, vDatetime, vRecur

from .sporty import is_home_game, kickoff_dt, maps_link, opponent_name
from .teams import TEAMS

logger = logging.getLogger(__name__)

NZ = pytz.timezone("Pacific/Auckland")
DOMAIN = "selwyn-football-watcher.github.io"

# Football season training runs roughly May–August.
# Weekly recurring events end on these dates.
TRAINING_END = {
    "2ndxi": datetime(2026, 8, 27, 15, 30, tzinfo=NZ),  # Last Thursday
    "13a":   datetime(2026, 8, 25, 7, 0, tzinfo=NZ),    # Last Tuesday
}

TRAINING_START = {
    "2ndxi": datetime(2026, 5, 7, 15, 30, tzinfo=NZ),   # First Thu in May
    "13a":   datetime(2026, 5, 5, 7, 0, tzinfo=NZ),     # First Tue in May
}


def _make_event_uid(fixture_id: int, team_key: str) -> str:
    return f"selwyn-{team_key}-fixture-{fixture_id}@{DOMAIN}"


def _make_training_uid(team_key: str) -> str:
    return f"selwyn-{team_key}-training-2026@{DOMAIN}"


def _safe_text(value: str) -> vText:
    return vText(value)


def build_ics(team_key: str, fixtures: list[dict]) -> bytes:
    """
    Build an iCalendar feed for the given team.

    Returns the raw .ics bytes.
    """
    team = TEAMS[team_key]
    cal = Calendar()
    cal.add("prodid", f"-//Selwyn Football Watcher//{team['display_name']}//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", _safe_text(f"{team['display_name']} Fixtures 2026"))
    cal.add("x-wr-timezone", _safe_text("Pacific/Auckland"))
    cal.add("x-wr-caldesc", _safe_text(
        f"Fixtures and training for {team['display_name']} 2026. "
        "Auto-updated from Sporty / College Sport."
    ))

    # --- Fixture events ---
    team_fixtures = [f for f in fixtures if f.get("GradeId") == team["grade_id"]]
    for fx in team_fixtures:
        ko = kickoff_dt(fx)
        end = ko + timedelta(hours=2)  # Default 2h window
        opp = opponent_name(fx)
        home = is_home_game(fx)
        home_away = "HOME" if home else "AWAY"
        venue = fx.get("VenueName", "TBC")
        venue_addr = fx.get("VenueAddress") or venue
        grade = fx.get("GradeName", "")
        round_name = fx.get("RoundName", "")
        lat = fx.get("LocationLat")
        lng = fx.get("LocationLng")
        map_url = maps_link(fx)

        summary = f"{team['display_name']} vs {opp} ({home_away})"

        description_parts = [
            f"{grade}, {round_name}",
            f"Arrive {_arrival_str(ko, team['warmup_minutes_before'])} for warm-up",
        ]
        if map_url:
            description_parts.append(f"Map: {map_url}")
        status = fx.get("StatusName", "")
        if status and status != "Confirmed":
            description_parts.append(f"Status: {status}")

        event = Event()
        event.add("uid", _make_event_uid(fx["Id"], team_key))
        event.add("summary", summary)
        event.add("dtstart", ko)
        event.add("dtend", end)
        event.add("location", _safe_text(f"{venue}, {venue_addr}"))
        event.add("description", _safe_text("\n".join(description_parts)))
        if lat and lng:
            event.add("geo", (lat, lng))
        event.add("status", "CONFIRMED" if fx.get("StatusName") == "Confirmed" else "TENTATIVE")
        event.add("sequence", 0)

        cal.add_component(event)

    # --- Recurring training event ---
    training_start = TRAINING_START[team_key]
    training_end_dt = training_start + timedelta(hours=1)  # 1-hour session
    until = TRAINING_END[team_key]

    rrule = {
        "FREQ": "WEEKLY",
        "BYDAY": _rrule_day(team["training_day"]),
        "UNTIL": until,
    }

    training_event = Event()
    training_event.add("uid", _make_training_uid(team_key))
    training_event.add("summary", _safe_text(f"{team['display_name']} Training"))
    training_event.add("dtstart", training_start)
    training_event.add("dtend", training_end_dt)
    training_event.add("location", _safe_text(f"Selwyn College, {team['training_location']}"))
    training_event.add("description", _safe_text(
        f"Weekly training — {team['display_name']}\n"
        f"Coach: {team['coach_full_name']}"
    ))
    training_event.add("rrule", rrule)
    cal.add_component(training_event)

    return cal.to_ical()


def _arrival_str(ko: datetime, warmup_minutes: int) -> str:
    arrival = ko - timedelta(minutes=warmup_minutes)
    return arrival.strftime("%-I:%M %p")


def _rrule_day(day_name: str) -> str:
    """Convert day name to RRULE BYDAY code."""
    mapping = {
        "Monday": "MO",
        "Tuesday": "TU",
        "Wednesday": "WE",
        "Thursday": "TH",
        "Friday": "FR",
        "Saturday": "SA",
        "Sunday": "SU",
    }
    return mapping[day_name]


def write_ics_files(fixtures: list[dict], docs_dir: Path) -> None:
    """Write .ics files for both teams into the docs/ directory."""
    docs_dir.mkdir(parents=True, exist_ok=True)
    for team_key in ["2ndxi", "13a"]:
        ics_bytes = build_ics(team_key, fixtures)
        out_path = docs_dir / f"fixtures_{team_key}.ics"
        out_path.write_bytes(ics_bytes)
        logger.info("Written %s (%d bytes)", out_path, len(ics_bytes))
