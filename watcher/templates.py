"""
TeamReach post templates.

All posts must stay under 800 characters (TeamReach hard limit).
Templates use plain prose — no colons as headers, no emojis in the posts
themselves (emojis are fine in email subject lines, which are manager-facing only).
"""

from datetime import datetime, timedelta

from .sporty import is_home_game, is_school_day, kickoff_dt, maps_link, opponent_name
from .teams import TEAMS


def _day_label(dt: datetime) -> str:
    """Return e.g. 'Friday' or 'Saturday'."""
    return dt.strftime("%A")


def _date_label(dt: datetime) -> str:
    """Return e.g. 'Friday 1 May'."""
    return dt.strftime("%-d %B")  # Linux only — works fine in GitHub Actions


def _arrival_time(dt: datetime, warmup_minutes: int) -> str:
    """Return the arrival time string, e.g. '8:00 AM'."""
    arrival = dt - timedelta(minutes=warmup_minutes)
    return arrival.strftime("%-I:%M %p")


def _kickoff_time(dt: datetime) -> str:
    """Return formatted kick-off time, e.g. '3:45 PM'."""
    return dt.strftime("%-I:%M %p")


def _attendance_deadline(dt: datetime) -> str:
    """
    Return the day players should update attendance by.
    Saturday game → Wednesday
    Friday game → Tuesday
    Other weekdays → 2 days before
    """
    weekday = dt.weekday()  # 0=Mon, 5=Sat, 6=Sun
    if weekday == 5:  # Saturday
        return "Wednesday"
    elif weekday == 4:  # Friday
        return "Tuesday"
    else:
        deadline = dt - timedelta(days=2)
        return deadline.strftime("%A")


def fixture_announcement(fixture: dict, team_key: str) -> str:
    """
    Template 1 — Fixture announcement (Monday of game week).
    Max 800 chars. Verified safe even with longest school names.
    """
    team = TEAMS[team_key]
    ko = kickoff_dt(fixture)
    opp = opponent_name(fixture)
    home = is_home_game(fixture)
    home_away = "HOME" if home else "AWAY"
    arrival = _arrival_time(ko, team["warmup_minutes_before"])
    ko_str = _kickoff_time(ko)
    deadline = _attendance_deadline(ko)
    venue = fixture.get("VenueName", "TBC")
    grade = fixture.get("GradeName", "")
    round_name = fixture.get("RoundName", "")
    coach = team["coach_first_name"]
    display = team["display_name"]
    audience = team["audience"]

    map_link = maps_link(fixture)
    maps_part = f"\n{map_link}" if map_link else ""

    if audience == "players":
        post = (
            f"This week's game — {display}\n"
            f"vs {opp} ({grade}, {round_name})\n"
            f"{_day_label(ko)} {_date_label(ko)}\n"
            f"Kick-off {ko_str}\n"
            f"{venue} ({home_away})"
            f"{maps_part}\n"
            f"Arrive {arrival} for warm-up and team talk\n"
            f"Update your attendance in TeamReach by {deadline} so {coach} can plan the squad."
        )
        if not home and is_school_day(fixture) and team["include_van_note_for_school_day_aways"]:
            post += f"\n{team['coach_first_name']} to confirm van travel arrangements separately."
    else:
        post = (
            f"This week's game — {display}\n"
            f"vs {opp}\n"
            f"{_day_label(ko)} {_date_label(ko)}\n"
            f"Kick-off {ko_str}\n"
            f"{venue} ({home_away})"
            f"{maps_part}\n"
            f"Arrive {arrival} for warm-up with {coach}\n"
            f"Players, please update your attendance in TeamReach by {deadline} so {coach} can plan the squad. Thanks team."
        )

    assert len(post) <= 800, f"Announcement too long ({len(post)} chars): {post[:80]}..."
    return post.strip()


def volunteer_ask(fixture: dict, team_key: str) -> str:
    """
    Template 2 — Volunteer ask (2 days before kick-off).

    Asks for two parents to run the line (one per half). Optionally
    acknowledges the previous game's volunteers if `last_volunteers` is
    set in the team config — update that field in teams.py after each game.
    """
    team = TEAMS[team_key]
    ko = kickoff_dt(fixture)
    opp = opponent_name(fixture)
    day = _day_label(ko)
    audience = team["audience"]

    # Acknowledge last game's volunteers if recorded
    thanks = ""
    last_volunteers = team.get("last_volunteers")
    if last_volunteers:
        thanks = f"Thanks to {last_volunteers} who ran the line last time 👏\n"

    if audience == "players":
        post = (
            f"Volunteers needed — {day}'s game vs {opp}\n"
            f"{thanks}"
            f"We need two parents willing to run the line for a half each — if you can help, please reply here. Cheers."
        )
    else:
        post = (
            f"Volunteers needed — {day}'s game vs {opp}\n"
            f"{thanks}"
            f"We need two parents willing to run the line for a half each — if you can help please reply here. Cheers team."
        )

    assert len(post) <= 800, f"Volunteer ask too long ({len(post)} chars)"
    return post.strip()


def day_before_reminder(fixture: dict, team_key: str, weather_line: str = "") -> str:
    """
    Template 3 — Day-before reminder (sent at 6 PM the evening before).
    Includes weather forecast if available.
    """
    team = TEAMS[team_key]
    ko = kickoff_dt(fixture)
    opp = opponent_name(fixture)
    arrival = _arrival_time(ko, team["warmup_minutes_before"])
    ko_str = _kickoff_time(ko)
    venue = fixture.get("VenueName", "TBC")
    audience = team["audience"]

    weather_part = f"\nForecast at kick-off — {weather_line}" if weather_line else ""

    if audience == "players":
        sign_off = "See you on the field."
    else:
        # Determine morning vs afternoon for sign-off
        if ko.hour < 12:
            sign_off = "See you in the morning."
        else:
            sign_off = "See you out there."

    post = (
        f"Game tomorrow\n"
        f"vs {opp}\n"
        f"KO {ko_str} — arrive {arrival}\n"
        f"{venue}\n"
        f"Full kit, boots, shin pads, water"
        f"{weather_part}\n"
        f"{sign_off}"
    )

    assert len(post) <= 800, f"Reminder too long ({len(post)} chars)"
    return post.strip()


def change_notification(fixture: dict, old_fixture: dict, team_key: str, changed_fields: list[str]) -> str:
    """
    Template 4 — Fixture change notification.
    Shows previous and current values for all changed fields.
    """
    team = TEAMS[team_key]
    ko = kickoff_dt(fixture)
    opp = opponent_name(fixture)
    day = _day_label(ko)
    audience = team["audience"]
    player_word = "Players" if audience == "players" else "Players"

    # Build was/now lines
    old_ko = kickoff_dt(old_fixture)
    old_venue = old_fixture.get("VenueName", "Unknown")
    old_opp = opponent_name(old_fixture)
    new_venue = fixture.get("VenueName", "TBC")

    was_parts = []
    now_parts = []

    if "From" in changed_fields:
        was_parts.append(f"{_kickoff_time(old_ko)} on {_day_label(old_ko)} {_date_label(old_ko)}")
        now_parts.append(f"{_kickoff_time(ko)} on {day} {_date_label(ko)}")
    if "VenueName" in changed_fields or "VenueId" in changed_fields:
        was_parts.append(old_venue)
        now_parts.append(new_venue)
    if "HomeTeamId" in changed_fields or "AwayTeamId" in changed_fields:
        was_parts.append(f"vs {old_opp}")
        now_parts.append(f"vs {opp}")

    was_str = ", ".join(was_parts) if was_parts else "see previous post"
    now_str = ", ".join(now_parts) if now_parts else "updated details above"

    post = (
        f"Heads up — fixture change\n"
        f"{day}'s game has changed.\n"
        f"Was: {was_str}\n"
        f"Now: {now_str}\n"
        f"{player_word}, please update your attendance if this affects you."
    )

    # Trim if over 800 (rare but possible with long venue names)
    if len(post) > 800:
        post = post[:797] + "..."
    return post.strip()


def cancellation_notice(fixture: dict, old_fixture: dict, team_key: str) -> str:
    """Change notification specifically for cancellations."""
    ko = kickoff_dt(old_fixture)
    opp = opponent_name(old_fixture)
    day = _day_label(ko)
    team = TEAMS[team_key]
    audience = team["audience"]

    post = (
        f"Heads up — fixture cancelled\n"
        f"{day}'s game vs {opp} has been cancelled.\n"
        f"No further action needed for now. I'll update if a replacement fixture is scheduled."
    )

    if len(post) > 800:
        post = post[:797] + "..."
    return post.strip()


def reinstatement_notice(fixture: dict, team_key: str) -> str:
    """A previously cancelled fixture is back on."""
    team = TEAMS[team_key]
    ko = kickoff_dt(fixture)
    opp = opponent_name(fixture)
    day = _day_label(ko)
    ko_str = _kickoff_time(ko)
    venue = fixture.get("VenueName", "TBC")
    arrival = _arrival_time(ko, team["warmup_minutes_before"])

    post = (
        f"Update — game reinstated\n"
        f"{day}'s game vs {opp} is back on.\n"
        f"Kick-off {ko_str}, arrive {arrival}\n"
        f"{venue}\n"
        f"Please update your attendance in TeamReach."
    )

    if len(post) > 800:
        post = post[:797] + "..."
    return post.strip()
