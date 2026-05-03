"""
Main entry point for the Selwyn Football Watcher.

Called by GitHub Actions workflows with one argument:
    python -m watcher.main morning
    python -m watcher.main evening
    python -m watcher.main morning --test   (sends [TEST] emails, no commit, no TR posts)

Flow:
1.  Load snapshot (fixtures + TeamReach event ID map)
2.  Fetch fixtures from Sporty
3.  Diff — detect changes
4.  Sync TeamReach calendar: create/update/delete events to match Sporty (always)
5.  Send daily email summary with drafted posts + coming-up footer (always)
6.  If post_teamreach=True: post scheduled messages to TeamReach
    If post_teamreach=False (default): email only — review and trigger manually
7.  If post_teamreach=True and changes detected: also post change notifications to TR
8.  Regenerate .ics and schedule docs
9.  Commit updated snapshot back to repo

IMPORTANT: post_teamreach defaults to False. The automated schedule never posts
messages automatically. Nick reviews the email and manually triggers the workflow
with post_teamreach=True when he's happy with what it will send.
"""

import argparse
import json
import logging
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pytz

from .compose import (
    build_email_body,
    compose_change_emails,
    compose_evening_posts,
    compose_morning_posts,
)
from .diff import ChangeEvent, diff_fixtures
from .email_sender import send_email, send_health_alert
from .ics_gen import write_ics_files
from .schedule_gen import write_schedule_files
from .snapshot import load_snapshot, save_snapshot
from .sporty import (
    fetch_fixtures,
    is_home_game,
    kickoff_dt,
    opponent_name,
)
from .teams import TEAMS
from .templates import fixture_announcement, volunteer_ask, day_before_reminder
from . import teamreach as tr

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

NZ = pytz.timezone("Pacific/Auckland")
DOCS_DIR = Path("docs")
REPO_ROOT = Path(".")

CANCELLED_STATUSES = {"Cancelled", "Postponed", "Abandoned"}

# Selwyn College home ground
SELWYN_LAT = -36.861778
SELWYN_LNG = 174.838745
SELWYN_ADDRESS = "203-245 Kohimarama Road, Kohimarama, Auckland 1071, New Zealand"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _today_nz() -> date:
    return datetime.now(NZ).date()


def _fixture_event_title(fixture: dict) -> str:
    """Generate a TeamReach calendar event title for a Sporty fixture."""
    opp = opponent_name(fixture)
    ha = "Home" if is_home_game(fixture) else "Away"
    return f"Football vs {opp} ({ha})"


def _fixture_venue(fixture: dict) -> tuple[str, str, float, float]:
    """
    Extract venue details from a Sporty fixture.
    Returns (location_name, address, lat, lng).
    """
    if is_home_game(fixture):
        return "Selwyn College", SELWYN_ADDRESS, SELWYN_LAT, SELWYN_LNG

    venue = fixture.get("VenueName") or "Away venue"
    lat = float(fixture.get("LocationLat") or SELWYN_LAT)
    lng = float(fixture.get("LocationLng") or SELWYN_LNG)
    address = f"{venue}, Auckland, New Zealand"
    return venue, address, lat, lng


def _team_key_for_fixture(fixture: dict) -> str:
    """Return the team key ('2ndxi' or '13a') for a fixture."""
    return "13a" if fixture.get("GradeId") == 712067 else "2ndxi"


# ---------------------------------------------------------------------------
# TeamReach event sync
# ---------------------------------------------------------------------------

def _sync_teamreach_events(
    all_fixtures: list[dict],
    changes: list[ChangeEvent],
    tr_map: dict[str, str],
    test_mode: bool,
) -> dict[str, str]:
    """
    Sync Sporty fixtures to TeamReach calendar events.

    Rules:
    - Active fixture with no TR event → create it
    - Active fixture that changed/was reinstated → update the TR event
    - Cancelled fixture with a TR event → delete it
    - Active fixture with existing TR event, no change → leave it alone

    Returns the updated tr_map {str(sporty_fixture_id): teamreach_event_id}.
    """
    changed_ids = {
        str(ch.fixture_id)
        for ch in changes
        if ch.change_type in ("changed", "reverted")
    }
    cancelled_ids = {
        str(ch.fixture_id)
        for ch in changes
        if ch.change_type == "cancelled"
    }

    new_tr_map = dict(tr_map)
    errors: list[str] = []

    for fx in all_fixtures:
        fid = str(fx["Id"])
        team_key = _team_key_for_fixture(fx)
        group_id = tr.GROUPS[team_key]
        status = fx.get("StatusName", "")
        is_cancelled = status in CANCELLED_STATUSES

        ko = kickoff_dt(fx)
        end_time = ko + timedelta(hours=2)
        title = _fixture_event_title(fx)
        location, address, lat, lng = _fixture_venue(fx)
        existing_eid = new_tr_map.get(fid)

        if is_cancelled:
            # Delete TR event if one exists
            if existing_eid:
                if test_mode:
                    logger.info("[TEST] Would delete TR event eid=%s (%s)", existing_eid, title)
                else:
                    try:
                        tr.delete_event(group_id, existing_eid)
                        del new_tr_map[fid]
                        logger.info("Deleted cancelled TR event eid=%s (%s)", existing_eid, title)
                    except tr.TeamReachError as exc:
                        err = f"Delete TR event {existing_eid} failed: {exc}"
                        logger.error(err)
                        errors.append(err)

        elif existing_eid is None:
            # New fixture — create TR event
            if test_mode:
                logger.info("[TEST] Would create TR event: %s @ %s", title, ko.strftime("%a %-d %b %H:%M"))
            else:
                try:
                    eid = tr.create_event(
                        group_id, title, ko, end_time, location, address, lat, lng
                    )
                    new_tr_map[fid] = eid
                    logger.info("Created TR event eid=%s: %s", eid, title)
                except tr.TeamReachError as exc:
                    err = f"Create TR event for fixture {fid} failed: {exc}"
                    logger.error(err)
                    errors.append(err)

        elif fid in changed_ids:
            # Fixture changed — update the TR event to match
            if test_mode:
                logger.info("[TEST] Would update TR event eid=%s: %s", existing_eid, title)
            else:
                try:
                    tr.update_event(
                        group_id, existing_eid, title, ko, end_time, location, address, lat, lng
                    )
                    logger.info("Updated TR event eid=%s: %s", existing_eid, title)
                except tr.TeamReachError as exc:
                    err = f"Update TR event {existing_eid} failed: {exc}"
                    logger.error(err)
                    errors.append(err)
        # else: active fixture, no change — nothing to do

    if errors:
        send_health_alert(
            "TeamReach event sync errors",
            "\n".join(errors),
        )

    return new_tr_map


# ---------------------------------------------------------------------------
# TeamReach message posting
# ---------------------------------------------------------------------------

def _post_to_teamreach(team_key: str, post_text: str, test_mode: bool) -> bool:
    """
    Post a message to the appropriate TeamReach group.
    Returns True on success.
    """
    group_id = tr.GROUPS[team_key]
    if test_mode:
        logger.info("[TEST] Would post to TeamReach group %s:\n%s", group_id, post_text[:80])
        return True
    try:
        msid = tr.post_message(group_id, post_text)
        logger.info("Posted to TeamReach group %s msid=%s", group_id, msid)
        return True
    except tr.TeamReachError as exc:
        logger.error("TeamReach post failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------

def _commit_changes(test_mode: bool) -> None:
    """Commit snapshot.json and generated files back to the repo."""
    if test_mode:
        logger.info("[TEST] Skipping git commit")
        return

    try:
        subprocess.run(
            ["git", "config", "user.name", "selwyn-watcher[bot]"],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "selwyn-watcher@noreply.github.com"],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "add",
             "snapshot.json",
             "season_schedule_2ndxi.md",
             "season_schedule_13a.md",
             "docs/fixtures_2ndxi.ics",
             "docs/fixtures_13a.ics",
             "docs/index.html",
             "docs/hub-data.json",
             ],
            check=True, capture_output=True,
        )
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            capture_output=True,
        )
        if result.returncode == 0:
            logger.info("No changes to commit")
            return

        subprocess.run(
            ["git", "commit", "-m",
             f"chore: update fixtures {datetime.now(NZ).strftime('%Y-%m-%d %H:%M %Z')}"],
            check=True, capture_output=True,
        )
        subprocess.run(["git", "push"], check=True, capture_output=True)
        logger.info("Committed and pushed changes")
    except subprocess.CalledProcessError as exc:
        logger.error("Git commit failed: %s", exc)
        send_health_alert("Git commit failed", str(exc))


def _build_change_subject(team_key: str, is_game_day: bool) -> str:
    team = TEAMS[team_key]
    prefix = "🚨🚨 GAME DAY CHANGE" if is_game_day else "🚨 FIXTURE CHANGE"
    return f"{prefix} — {team['display_name']}"


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------

def run(run_type: str, test_mode: bool = False, post_teamreach: bool = False) -> None:
    """
    Main watcher run — morning or evening.

    post_teamreach: if True, actually post messages to TeamReach groups.
                    if False (default), email only — review before posting.
    """
    logger.info(
        "=== Selwyn Football Watcher — %s run (post_teamreach=%s) ===",
        run_type.upper(), post_teamreach,
    )
    today = _today_nz()
    errors: list[str] = []

    # 1. Load snapshot — fixtures + TeamReach event ID map
    snapshot = load_snapshot()
    tr_map: dict[str, str] = snapshot.pop("_teamreach", {})
    # snapshot now contains only fixture data (safe to pass to diff_fixtures)

    # 2. Fetch all fixtures (both teams in one API call)
    try:
        all_fixtures = fetch_fixtures([712053, 712067])
    except Exception as exc:
        msg = f"Sporty API fetch failed: {exc}"
        logger.error(msg)
        send_health_alert("Sporty fetch failed", msg)
        return

    if not all_fixtures:
        send_health_alert(
            "Sporty returned empty fixture list",
            "No fixtures returned — API may be down or grade IDs changed.",
        )
        return

    # 3. Diff against snapshot
    changes, new_snapshot = diff_fixtures(all_fixtures, snapshot)

    # 4. Sync TeamReach calendar events
    tr_map = _sync_teamreach_events(all_fixtures, changes, tr_map, test_mode)

    # 5. Process each team
    for team_key, team in TEAMS.items():
        grade_id = team["grade_id"]
        team_fixtures = [f for f in all_fixtures if f.get("GradeId") == grade_id]

        # --- 5a. Change notifications ---
        team_changes = [ch for ch in changes if ch.grade_id == grade_id]
        if team_changes:
            change_posts = compose_change_emails(team_changes, team_key)
            if change_posts:
                any_game_day = any(is_gd for _, _, is_gd in change_posts)
                subject = _build_change_subject(team_key, any_game_day)
                email_parts = []
                for heading, post_text, is_gd in change_posts:
                    if post_teamreach:
                        posted = _post_to_teamreach(team_key, post_text, test_mode)
                        status = "✓ Posted to TeamReach" if posted else "⚠️ TeamReach post failed — paste manually"
                    else:
                        status = "⏸ Not posted — trigger workflow with 'Post to TeamReach' to send"
                    email_parts.append(
                        f"**{heading}**\n{status}\n\n```\n{post_text}\n```"
                    )
                body = "\n\n---\n\n".join(email_parts)
                try:
                    send_email(subject, body, high_importance=True, test_mode=test_mode)
                except Exception as exc:
                    errors.append(f"Change email failed for {team_key}: {exc}")
                    logger.error("Change email send failed: %s", exc)

        # --- 5b. Scheduled posts ---
        if run_type == "morning":
            posts = compose_morning_posts(team_key, team_fixtures, today)
            subject_prefix = f"[{team['display_name']}] Morning — {today.strftime('%a %-d %b')}"
        else:
            posts = compose_evening_posts(team_key, team_fixtures, today)
            subject_prefix = f"[{team['display_name']}] Evening — {today.strftime('%a %-d %b')}"

        # Post each scheduled message to TeamReach (only if explicitly approved)
        post_statuses: list[tuple[str, str, bool]] = []  # (heading, text, posted_ok)
        for heading, post_text in posts:
            if post_teamreach:
                posted = _post_to_teamreach(team_key, post_text, test_mode)
            else:
                posted = None  # None = not attempted yet (pending review)
            post_statuses.append((heading, post_text, posted))

        # --- 5c. Daily email (summary log) ---
        body = build_email_body(
            team_key=team_key,
            fixtures=team_fixtures,
            all_fixtures_for_team=team_fixtures,
            posts=posts,
            post_statuses=post_statuses,
            run_type=run_type,
            today=today,
            test_mode=test_mode,
        )

        if body:
            try:
                send_email(subject_prefix, body, high_importance=False, test_mode=test_mode)
            except Exception as exc:
                errors.append(f"Daily email failed for {team_key}: {exc}")
                logger.error("Daily email failed for %s: %s", team_key, exc)

    # 6. Regenerate .ics, schedule docs, and hub data
    try:
        write_ics_files(all_fixtures, DOCS_DIR)
        _write_index_html()
    except Exception as exc:
        logger.error("ICS generation failed: %s", exc)
        errors.append(f"ICS generation failed: {exc}")

    try:
        write_hub_data(all_fixtures, tr_map)
    except Exception as exc:
        logger.error("Hub data generation failed: %s", exc)
        errors.append(f"Hub data generation failed: {exc}")

    try:
        write_schedule_files(all_fixtures, REPO_ROOT)
    except Exception as exc:
        logger.error("Schedule doc generation failed: %s", exc)

    # 7. Save updated snapshot (fixtures + TeamReach event IDs)
    new_snapshot["_teamreach"] = tr_map
    save_snapshot(new_snapshot)
    _commit_changes(test_mode)

    # 8. Report accumulated errors
    if errors:
        send_health_alert(
            "Errors during watcher run",
            f"Run type: {run_type}\nDate: {today}\n\nErrors:\n" + "\n".join(errors),
        )

    logger.info("=== Run complete ===")


SELWYN_ORG_ID = 11255
GRADE_TO_TEAM = {712067: "13a", 712053: "2ndxi"}


def _normalise_fixture_for_hub(f: dict, tr_map: dict) -> dict:
    """Convert a raw Sporty fixture into a hub-friendly dict."""
    grade_id = f.get("GradeId")
    team_key = GRADE_TO_TEAM.get(grade_id, "unknown")
    team = TEAMS.get(team_key, {})
    home_org = f.get("HomeOrganisationId")
    away_org = f.get("AwayOrganisationId")
    home = (home_org == SELWYN_ORG_ID)
    opponent = f.get("AwayOrgName" if home else "HomeOrgName", "Unknown")

    ko_raw = f.get("From", "")
    ko_iso = ko_raw + "+12:00" if ko_raw and "+" not in ko_raw else ko_raw

    hs = f.get("HomeScore")
    as_ = f.get("AwayScore")
    result = None
    if hs not in (None, "") and as_ not in (None, ""):
        hs, as_ = int(hs), int(as_)
        my = hs if home else as_
        opp = as_ if home else hs
        result = f"Won {my}–{opp}" if my > opp else (f"Drew {my}–{opp}" if my == opp else f"Lost {my}–{opp}")

    fid = str(f.get("Id", ""))
    return {
        "id":           fid,
        "team_key":     team_key,
        "display_name": team.get("display_name", team_key),
        "ko_iso":       ko_iso,
        "opponent":     opponent,
        "home_away":    "Home" if home else "Away",
        "venue":        f.get("VenueName", "TBC"),
        "round":        f.get("RoundName", ""),
        "grade":        f.get("GradeName", ""),
        "in_teamreach": fid in tr_map,
        "tr_event_id":  tr_map.get(fid),
        "result":       result,
    }


def _build_hub_schedule(raw_fixtures: list[dict]) -> list[dict]:
    """Generate scheduled post items for every fixture in the coming 12 weeks."""
    today = date.today()
    cutoff = today - timedelta(days=14)
    schedule = []

    for f in raw_fixtures:
        grade_id = f.get("GradeId")
        team_key = GRADE_TO_TEAM.get(grade_id)
        if team_key not in TEAMS:
            continue

        ko_raw = f.get("From", "")
        ko_iso = ko_raw + "+12:00" if ko_raw and "+" not in ko_raw else ko_raw
        try:
            ko_dt = datetime.fromisoformat(ko_iso)
            ko_date = ko_dt.date()
        except Exception:
            continue

        if ko_date < cutoff:
            continue

        group_id = tr.GROUPS.get(team_key, "")
        fid = str(f.get("Id", ""))

        for post_type, label, gen_fn in [
            ("fixture_announcement", "Fixture Announcement", fixture_announcement),
            ("volunteer_ask",        "Volunteer Ask",        volunteer_ask),
            ("day_before_reminder",  "Day-Before Reminder",  day_before_reminder),
        ]:
            if post_type == "fixture_announcement":
                sched_date = ko_date - timedelta(days=ko_date.weekday())  # Monday
            elif post_type == "volunteer_ask":
                sched_date = ko_date - timedelta(days=2)
            else:
                sched_date = ko_date - timedelta(days=1)

            try:
                text = gen_fn(f, team_key)
            except Exception as exc:
                text = f"[Template error: {exc}]"

            schedule.append({
                "team_key":          team_key,
                "group_id":          group_id,
                "fixture_id":        fid,
                "opponent":          f.get("AwayOrgName" if f.get("HomeOrganisationId") == SELWYN_ORG_ID else "HomeOrgName", "Unknown"),
                "ko_date":           ko_date.isoformat(),
                "ko_display":        ko_dt.strftime("%-d %b, %-I:%M %p").replace("AM", "am").replace("PM", "pm"),
                "scheduled_iso":     sched_date.isoformat(),
                "scheduled_display": sched_date.strftime("%-d %b"),
                "type":              post_type,
                "label":             label,
                "text":              text,
            })

    return schedule


def write_hub_data(all_fixtures: list[dict], tr_map: dict) -> None:
    """
    Generate docs/hub-data.json with live fixture, schedule, and message data.
    This file is served via GitHub Pages and consumed by the Cowork artifact.
    """
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    fixtures = [_normalise_fixture_for_hub(f, tr_map) for f in all_fixtures]
    schedule = _build_hub_schedule(all_fixtures)

    messages: dict[str, list] = {}
    for key, gid in tr.GROUPS.items():
        try:
            messages[key] = tr.list_messages(gid)
        except Exception as exc:
            messages[key] = []
            logger.warning("Could not fetch TR messages for %s: %s", key, exc)

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "fixtures":   fixtures,
        "schedule":   schedule,
        "messages":   messages,
    }

    out_path = DOCS_DIR / "hub-data.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    logger.info("Wrote hub-data.json (%d fixtures, %d schedule items)", len(fixtures), len(schedule))


def _write_index_html() -> None:
    """Write a simple index.html for the GitHub Pages site."""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Selwyn Football Calendars</title>
<style>body{font-family:sans-serif;max-width:600px;margin:40px auto;padding:20px;}
a{color:#006633;}code{background:#f4f4f4;padding:2px 6px;border-radius:4px;}</style>
</head>
<body>
<h1>Selwyn Football 2026 — Calendar Feeds</h1>
<p>Subscribe to these .ics feeds in Apple Calendar or Google Calendar to get
all fixtures and training automatically. The feeds update daily.</p>

<h2>Selwyn 2nd XI</h2>
<p><a href="fixtures_2ndxi.ics">Download fixtures_2ndxi.ics</a></p>
<p>To subscribe in Apple Calendar: File → New Calendar Subscription → paste this URL:<br>
<code>https://nickmackeson-smith.github.io/selwyn-football-watcher/fixtures_2ndxi.ics</code></p>

<h2>Selwyn 13A Boys</h2>
<p><a href="fixtures_13a.ics">Download fixtures_13a.ics</a></p>
<p>To subscribe in Apple Calendar: File → New Calendar Subscription → paste this URL:<br>
<code>https://nickmackeson-smith.github.io/selwyn-football-watcher/fixtures_13a.ics</code></p>

<hr>
<p><small>Auto-updated from <a href="https://www.sporty.co.nz/collegesport/draws-results">Sporty / College Sport</a>.</small></p>
</body>
</html>"""
    (DOCS_DIR / "index.html").write_text(html, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Selwyn Football Watcher")
    parser.add_argument("run_type", choices=["morning", "evening"])
    parser.add_argument("--test", action="store_true", help="Test mode — [TEST] emails, no commit, no TR posts")
    parser.add_argument("--post-teamreach", action="store_true",
                        help="Post scheduled messages to TeamReach (default: email only)")
    args = parser.parse_args()
    run(args.run_type, test_mode=args.test, post_teamreach=args.post_teamreach)


if __name__ == "__main__":
    main()
