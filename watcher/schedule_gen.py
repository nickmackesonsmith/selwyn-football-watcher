"""
Season schedule markdown generator.

Produces a clean, human-readable .md file per team listing all
published fixtures, formatted for fast manual entry into TeamReach.
"""

import logging
from datetime import timedelta
from pathlib import Path

from .sporty import is_home_game, kickoff_dt, maps_link, opponent_name
from .teams import TEAMS

logger = logging.getLogger(__name__)


def _arrival_str(ko, warmup_minutes: int) -> str:
    from datetime import timedelta
    arrival = ko - timedelta(minutes=warmup_minutes)
    return arrival.strftime("%-I:%M %p")


def build_schedule_md(team_key: str, fixtures: list[dict]) -> str:
    """
    Build a season schedule markdown document for the given team.
    Suitable for printing or displaying on phone while entering into TeamReach.
    """
    team = TEAMS[team_key]
    team_fixtures = sorted(
        [f for f in fixtures if f.get("GradeId") == team["grade_id"]],
        key=lambda f: kickoff_dt(f)
    )

    lines = [
        f"# {team['display_name']} — Season Schedule 2026",
        f"",
        f"Coach: {team['coach_full_name']}  ",
        f"TeamReach group: {team['teamreach_group_name']}  ",
        f"",
        f"---",
        f"",
        f"## Recurring Training",
        f"",
        f"**Every {team['training_day']}**  ",
        _format_time_24h(team['training_time']) + f"  ",
        f"Location: Selwyn College, {team['training_location']}  ",
        f"Season runs May–August 2026  ",
        f"",
        f"---",
        f"",
        f"## Fixtures ({len(team_fixtures)} published)",
        f"",
    ]

    if not team_fixtures:
        lines.append("_No fixtures published yet — check back soon._")
        return "\n".join(lines)

    for fx in team_fixtures:
        ko = kickoff_dt(fx)
        opp = opponent_name(fx)
        home = is_home_game(fx)
        home_away = "HOME" if home else "AWAY"
        venue = fx.get("VenueName", "TBC")
        venue_addr = fx.get("VenueAddress") or ""
        grade = fx.get("GradeName", "")
        round_name = fx.get("RoundName", "")
        status = fx.get("StatusName", "")
        arrival = _arrival_str(ko, team["warmup_minutes_before"])
        map_url = maps_link(fx)

        lines.append(f"### {ko.strftime('%a %-d %b %Y')} — vs {opp} ({home_away})")
        lines.append(f"")
        lines.append(f"| Field | Value |")
        lines.append(f"|-------|-------|")
        lines.append(f"| **Title** | `{team['display_name']} vs {opp} ({home_away})` |")
        lines.append(f"| **Date** | {ko.strftime('%A, %-d %B %Y')} |")
        lines.append(f"| **Kick-off** | {ko.strftime('%-I:%M %p')} |")
        lines.append(f"| **Arrival** | {arrival} (warm-up) |")
        lines.append(f"| **Venue** | {venue} |")
        if venue_addr:
            lines.append(f"| **Address** | {venue_addr} |")
        if map_url:
            lines.append(f"| **Map** | [{map_url}]({map_url}) |")
        lines.append(f"| **Grade** | {grade} — {round_name} |")
        lines.append(f"| **Status** | {status} |")
        lines.append(f"")

        # TeamReach toggles reminder
        lines.append(f"_TeamReach toggles: Forecast / Who's Available / Take Attendance / Reminder (1 day before)_")
        lines.append(f"")
        lines.append(f"---")
        lines.append(f"")

    return "\n".join(lines)


def _format_time_24h(time_str: str) -> str:
    """Convert '15:30' to '3:30 PM'."""
    from datetime import datetime
    dt = datetime.strptime(time_str, "%H:%M")
    return dt.strftime("%-I:%M %p")


def write_schedule_files(fixtures: list[dict], output_dir: Path) -> None:
    """Write season schedule .md files for both teams."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for team_key in ["2ndxi", "13a"]:
        md = build_schedule_md(team_key, fixtures)
        out_path = output_dir / f"season_schedule_{team_key}.md"
        out_path.write_text(md, encoding="utf-8")
        logger.info("Written %s", out_path)
