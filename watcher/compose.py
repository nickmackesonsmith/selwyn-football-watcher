"""
Compose the daily email content for each team.

Determines which posts are due today based on:
- Monday of game week → fixture announcement
- 2 days before kick-off → volunteer ask
- Day before kick-off (evening run) → day-before reminder
- Any change detected → change notification (handled separately)
"""

import logging
from datetime import date, datetime, timedelta

import pytz

from .diff import ChangeEvent
from .sporty import kickoff_dt, opponent_name, fetch_recent_results, fetch_standings
from .teams import TEAMS
from .templates import (
    cancellation_notice,
    change_notification,
    day_before_reminder,
    fixture_announcement,
    reinstatement_notice,
    volunteer_ask,
)
from .weather import get_forecast_line

logger = logging.getLogger(__name__)
NZ = pytz.timezone("Pacific/Auckland")


def _today_nz() -> date:
    return datetime.now(NZ).date()


def _fixtures_for_team(all_fixtures: list[dict], grade_id: int) -> list[dict]:
    """Filter fixtures to a specific grade (team)."""
    return [f for f in all_fixtures if f.get("GradeId") == grade_id]


def _is_first_monday_of_month(d: date) -> bool:
    return d.weekday() == 0 and d.day <= 7


def _format_result_line(fixture: dict, team_key: str) -> str | None:
    """Format last weekend's result for display in the email."""
    from .sporty import is_home_game, SELWYN_ORG_ID
    home_score = fixture.get("HomeScore")
    away_score = fixture.get("AwayScore")
    if home_score is None or away_score is None:
        return None

    ko = kickoff_dt(fixture)
    opp = opponent_name(fixture)
    grade = fixture.get("GradeName", "")
    round_name = fixture.get("RoundName", "")
    team = TEAMS[team_key]

    if is_home_game(fixture):
        sel_score = home_score
        opp_score = away_score
    else:
        sel_score = away_score
        opp_score = home_score

    if sel_score > opp_score:
        result = "won"
    elif sel_score < opp_score:
        result = "lost"
    else:
        result = "drew"

    return (
        f"**Last weekend's result — {team['display_name']}**\n"
        f"{team['display_name']} {sel_score} — {opp} {opp_score} ({result})\n"
        f"{grade}, {round_name} ({ko.strftime('%-d %B')})"
    )


def _format_standings(grade_id: int, comp_id: int, team_key: str) -> str:
    """Fetch and format monthly standings."""
    team = TEAMS[team_key]
    try:
        standings_data = fetch_standings(comp_id, grade_id)
        if not standings_data:
            return ""
        # Try to find Selwyn in standings
        selwyn_row = None
        total_teams = 0
        rows = []
        # API returns phases structure
        for item in standings_data:
            if isinstance(item, dict):
                rows = item.get("Rows") or item.get("Teams") or []
                break
        total_teams = len(rows)
        for row in rows:
            org_id = row.get("OrganisationId") or row.get("OrgId")
            if org_id == 11255:
                selwyn_row = row
                break

        if not selwyn_row:
            return ""

        pos = selwyn_row.get("Position") or selwyn_row.get("Rank", "?")
        played = selwyn_row.get("Played") or selwyn_row.get("P", 0)
        won = selwyn_row.get("Won") or selwyn_row.get("W", 0)
        drew = selwyn_row.get("Drawn") or selwyn_row.get("D", 0)
        lost = selwyn_row.get("Lost") or selwyn_row.get("L", 0)
        gf = selwyn_row.get("GoalsFor") or selwyn_row.get("GF", 0)
        ga = selwyn_row.get("GoalsAgainst") or selwyn_row.get("GA", 0)
        pts = selwyn_row.get("Points") or selwyn_row.get("Pts", 0)
        gd = gf - ga
        gd_str = f"+{gd}" if gd >= 0 else str(gd)
        grade_name = team["display_name"]

        return (
            f"**League standing — {grade_name}**\n"
            f"Position: {pos} of {total_teams}\n"
            f"Played {played} — Won {won}, Drew {drew}, Lost {lost}\n"
            f"Goals {gf}/{ga} ({gd_str}) | Points: {pts}"
        )
    except Exception as exc:
        logger.warning("Could not format standings: %s", exc)
        return ""


def _coming_up_footer(fixtures: list[dict], team_key: str) -> str:
    """Return the next 2 upcoming fixtures as a footer block."""
    today = _today_nz()
    team = TEAMS[team_key]
    upcoming = sorted(
        [f for f in fixtures if kickoff_dt(f).date() >= today],
        key=lambda f: kickoff_dt(f)
    )[:2]

    if not upcoming:
        return f"Coming up — {team['display_name']}\n(No further fixtures published yet)"

    lines = [f"Coming up — {team['display_name']}"]
    for fx in upcoming:
        ko = kickoff_dt(fx)
        opp = opponent_name(fx)
        home_away = "home" if fx.get("HomeOrganisationId") == 11255 else "away"
        lines.append(f"- {ko.strftime('%a %-d %b')}, {ko.strftime('%-I:%M %p')}, {home_away} vs {opp}")

    return "\n".join(lines)


def _bye_week_notice(fixtures: list[dict], team_key: str) -> str | None:
    """
    If no fixture falls in the current Mon-Sun window, return a bye-week notice.
    """
    team = TEAMS[team_key]
    today = _today_nz()
    # Monday of this week
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)

    this_week = [
        f for f in fixtures
        if monday <= kickoff_dt(f).date() <= sunday
    ]

    if this_week:
        return None

    # Find next fixture after this week
    future = sorted(
        [f for f in fixtures if kickoff_dt(f).date() > sunday],
        key=lambda f: kickoff_dt(f)
    )
    training_day = team["training_day"]
    training_time_str = team["training_time"]
    training_loc = team["training_location"]

    # Format training time nicely
    h, m = training_time_str.split(":")
    dt_t = datetime.now().replace(hour=int(h), minute=int(m))
    training_time_nice = dt_t.strftime("%-I:%M %p")

    if future:
        next_fx = future[0]
        ko = kickoff_dt(next_fx)
        opp = opponent_name(next_fx)
        home_away = "home" if next_fx.get("HomeOrganisationId") == 11255 else "away"
        next_str = f"{ko.strftime('%-d %b')}, {_kickoff_time_from_dt(ko)}, {home_away} vs {opp}"
        return (
            f"No game this week — {team['display_name']}. "
            f"Training continues as normal — {training_day}s {training_time_nice}, {training_loc}. "
            f"Next fixture: {next_str}."
        )
    else:
        return (
            f"No game this week — {team['display_name']}. "
            f"Training continues as normal — {training_day}s {training_time_nice}, {training_loc}. "
            f"No further fixtures published yet."
        )


def _kickoff_time_from_dt(dt: datetime) -> str:
    return dt.strftime("%-I:%M %p")


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def compose_morning_posts(
    team_key: str,
    fixtures: list[dict],
    today: date | None = None,
) -> list[tuple[str, str]]:
    """
    Determine which posts are due this morning and compose them.

    Returns list of (heading, post_text) tuples.
    Monday → fixture announcement
    2 days before → volunteer ask
    """
    team = TEAMS[team_key]
    today = today or _today_nz()
    posts: list[tuple[str, str]] = []

    for fx in fixtures:
        ko = kickoff_dt(fx)
        ko_date = ko.date()

        # Skip past fixtures
        if ko_date < today:
            continue

        days_until = (ko_date - today).days

        # Monday of game week → announcement (if game is Mon-Sun this week)
        # We fire on the Monday before the game week.
        # "Monday of game week" = kick-off is within the next 7 days
        # and today is Monday.
        if today.weekday() == 0 and 0 < days_until <= 7:
            heading = f"Fixture announcement — {ko.strftime('%a %-d %b')} vs {opponent_name(fx)}"
            post = fixture_announcement(fx, team_key)
            posts.append((heading, post))

        # 2 days before → volunteer ask
        if days_until == 2:
            heading = f"Volunteer ask — {ko.strftime('%a %-d %b')} vs {opponent_name(fx)}"
            post = volunteer_ask(fx, team_key)
            posts.append((heading, post))

    return posts


def compose_evening_posts(
    team_key: str,
    fixtures: list[dict],
    today: date | None = None,
) -> list[tuple[str, str]]:
    """
    Compose day-before reminder if there's a game tomorrow.
    Includes weather forecast.
    """
    today = today or _today_nz()
    tomorrow = today + timedelta(days=1)
    posts: list[tuple[str, str]] = []

    for fx in fixtures:
        ko = kickoff_dt(fx)
        if ko.date() == tomorrow:
            lat = fx.get("LocationLat")
            lng = fx.get("LocationLng")
            weather_line = ""
            if lat and lng:
                weather_line = get_forecast_line(lat, lng, ko)
            heading = f"Day-before reminder — {ko.strftime('%a %-d %b')} vs {opponent_name(fx)}"
            post = day_before_reminder(fx, team_key, weather_line)
            posts.append((heading, post))

    return posts


def compose_change_emails(changes: list[ChangeEvent], team_key: str) -> list[tuple[str, str, bool]]:
    """
    Compose change notification posts.

    Returns list of (heading, post_text, is_game_day) tuples.
    """
    today = _today_nz()
    posts = []

    for ch in changes:
        if ch.grade_id != TEAMS[team_key]["grade_id"]:
            continue

        fx = ch.fixture
        ko = kickoff_dt(fx)
        game_day = ko.date() == today
        opp = opponent_name(fx)
        day_label = ko.strftime("%a %-d %b")

        if ch.change_type == "new":
            post = fixture_announcement(fx, team_key)
            heading = f"New fixture — {day_label} vs {opp}"
            posts.append((heading, post, False))

        elif ch.change_type == "cancelled":
            post = cancellation_notice(fx, ch.old_fixture, team_key)
            heading = f"Fixture cancelled — {day_label} vs {opp}"
            posts.append((heading, post, game_day))

        elif ch.change_type == "reverted":
            post = reinstatement_notice(fx, team_key)
            heading = f"Fixture reinstated — {day_label} vs {opp}"
            posts.append((heading, post, game_day))

        elif ch.change_type == "changed":
            post = change_notification(fx, ch.old_fixture, team_key, ch.changed_fields)
            heading = f"Fixture change — {day_label} vs {opp}"
            posts.append((heading, post, game_day))

    return posts


def build_email_body(
    team_key: str,
    fixtures: list[dict],
    all_fixtures_for_team: list[dict],
    posts: list[tuple[str, str]],
    run_type: str,  # "morning" or "evening"
    today: date | None = None,
    test_mode: bool = False,
    post_statuses: list[tuple[str, str, bool]] | None = None,
) -> str | None:
    """
    Build the full email body for a team's daily brief.
    Returns None if there's nothing to send.

    Includes (where applicable):
    - Last weekend's result
    - Monthly standings (first Monday only)
    - Bye week notice
    - Today's posts (clearly formatted for copy-paste)
    - Coming-up footer
    """
    team = TEAMS[team_key]
    today = today or _today_nz()
    sections: list[str] = []

    # --- Last weekend's result (morning only) ---
    if run_type == "morning":
        one_week_ago = today - timedelta(days=7)
        recent = sorted(
            [f for f in all_fixtures_for_team
             if one_week_ago <= kickoff_dt(f).date() < today
             and f.get("HomeScore") is not None],
            key=lambda f: kickoff_dt(f),
            reverse=True,
        )
        if recent:
            result_line = _format_result_line(recent[0], team_key)
            if result_line:
                sections.append(result_line)

    # --- Monthly standings (first Monday of month, morning only) ---
    if run_type == "morning" and _is_first_monday_of_month(today):
        grade_id = team["grade_id"]
        comp_id = team["comp_ids"][0]  # Use Football Boys Season comp
        standings_str = _format_standings(grade_id, comp_id, team_key)
        if standings_str:
            sections.append(standings_str)

    # --- Bye week notice ---
    bye_notice = _bye_week_notice(all_fixtures_for_team, team_key)
    if bye_notice:
        sections.append(bye_notice)

    # --- Today's posts ---
    if posts:
        # Use statuses if provided (indicates whether TR post succeeded)
        statuses = {heading: ok for heading, _, ok in (post_statuses or [])}
        for heading, post in posts:
            group_name = team["teamreach_group_name"]
            posted_ok = statuses.get(heading)
            if posted_ok is True:
                status_line = "✓ Posted to TeamReach"
            elif posted_ok is False:
                status_line = f"⚠️ TeamReach post failed — paste manually into \"{group_name}\""
            else:
                # None = not attempted (manual review mode)
                status_line = (
                    f"⏸ Not posted yet — if this looks right, go to Actions → "
                    f"Run workflow → set 'Post to TeamReach' = true"
                )
            sections.append(
                f"---\n"
                f"**{heading}**\n"
                f"{status_line}\n\n"
                f"```\n{post}\n```"
            )
    else:
        if not bye_notice and not sections:
            # Truly nothing to report — skip the email
            # But always include the footer so Nick can see what's coming
            pass

    # --- Coming-up footer ---
    footer = _coming_up_footer(all_fixtures_for_team, team_key)
    sections.append(footer)

    # Don't send if the only thing is the footer
    meaningful = [s for s in sections if s != footer]
    if not meaningful and not posts:
        return None

    separator = "\n\n" + ("=" * 50) + "\n\n"
    body = separator.join(sections)

    if test_mode:
        body = "[TEST MODE — no changes committed]\n\n" + body

    return body
