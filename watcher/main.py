"""
Main entry point for the Selwyn Football Watcher.

Called by GitHub Actions workflows with one argument:
    python -m watcher.main morning
    python -m watcher.main evening
    python -m watcher.main morning --test   (sends [TEST] emails, no commit)

Flow:
1. Load snapshot
2. Fetch fixtures for both teams
3. Diff — detect changes
4. Fire change emails immediately (high importance)
5. Compose scheduled posts for each team
6. Send daily email if anything to report
7. Regenerate .ics + schedule docs
8. Commit updated snapshot back to repo
"""

import argparse
import logging
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import pytz

from .compose import (
    build_email_body,
    compose_change_emails,
    compose_evening_posts,
    compose_morning_posts,
)
from .diff import diff_fixtures
from .email_sender import send_email, send_health_alert
from .ics_gen import write_ics_files
from .schedule_gen import write_schedule_files
from .snapshot import load_snapshot, save_snapshot
from .sporty import fetch_fixtures, kickoff_dt, opponent_name
from .teams import TEAMS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

NZ = pytz.timezone("Pacific/Auckland")
DOCS_DIR = Path("docs")
REPO_ROOT = Path(".")


def _today_nz() -> date:
    return datetime.now(NZ).date()


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
             f"chore: update fixtures snapshot {datetime.now(NZ).strftime('%Y-%m-%d %H:%M %Z')}"],
            check=True, capture_output=True,
        )
        subprocess.run(["git", "push"], check=True, capture_output=True)
        logger.info("Committed and pushed changes")
    except subprocess.CalledProcessError as exc:
        logger.error("Git commit failed: %s", exc)
        send_health_alert("Git commit failed", str(exc))


def _build_change_subject(change_posts: list[tuple[str, str, bool]], team_key: str, is_game_day: bool) -> str:
    team = TEAMS[team_key]
    prefix = "🚨🚨 GAME DAY CHANGE" if is_game_day else "🚨 FIXTURE CHANGE"
    return f"{prefix} — {team['display_name']}"


def run(run_type: str, test_mode: bool = False) -> None:
    """Main watcher run — morning or evening."""
    logger.info("=== Selwyn Football Watcher — %s run ===", run_type.upper())
    today = _today_nz()
    errors: list[str] = []

    # 1. Load snapshot
    snapshot = load_snapshot()

    # 2. Fetch all fixtures (both teams together — API allows multi-grade)
    try:
        all_fixtures = fetch_fixtures([712053, 712067])  # both grade IDs
    except Exception as exc:
        msg = f"Sporty API fetch failed: {exc}"
        logger.error(msg)
        send_health_alert("Sporty fetch failed", msg)
        return  # Can't proceed without fixtures

    if not all_fixtures:
        send_health_alert("Sporty returned empty fixture list", "No fixtures returned — API may be down or IDs changed.")
        return

    # 3. Diff — detect changes
    changes, new_snapshot = diff_fixtures(all_fixtures, snapshot)

    # 4. Process each team separately
    for team_key, team in TEAMS.items():
        grade_id = team["grade_id"]
        team_fixtures = [f for f in all_fixtures if f.get("GradeId") == grade_id]

        # 4a. Change notifications (fire immediately, high importance)
        team_changes = [ch for ch in changes if ch.grade_id == grade_id]
        if team_changes:
            change_posts = compose_change_emails(team_changes, team_key)
            if change_posts:
                any_game_day = any(gd for _, _, gd in change_posts)
                subject = _build_change_subject(change_posts, team_key, any_game_day)
                body_parts = []
                for heading, post, is_gd in change_posts:
                    group = team["teamreach_group_name"]
                    body_parts.append(
                        f"**{heading}**\n_(paste into \"{group}\")_\n\n```\n{post}\n```"
                    )
                body = "\n\n---\n\n".join(body_parts)
                try:
                    send_email(subject, body, high_importance=True, test_mode=test_mode)
                except Exception as exc:
                    errors.append(f"Change email failed for {team_key}: {exc}")
                    logger.error("Change email send failed: %s", exc)

        # 4b. Scheduled posts for this run type
        if run_type == "morning":
            posts = compose_morning_posts(team_key, team_fixtures, today)
            subject_prefix = f"[{team['display_name']}] TeamReach posts for {today.strftime('%a %-d %b')}"
        else:
            posts = compose_evening_posts(team_key, team_fixtures, today)
            subject_prefix = f"[{team['display_name']}] Day-before reminder for {today.strftime('%a %-d %b')}"

        # 4c. Build and send daily email
        body = build_email_body(
            team_key=team_key,
            fixtures=team_fixtures,
            all_fixtures_for_team=team_fixtures,
            posts=posts,
            run_type=run_type,
            today=today,
            test_mode=test_mode,
        )

        if body:
            try:
                send_email(subject_prefix, body, high_importance=False, test_mode=test_mode)
            except Exception as exc:
                errors.append(f"Daily email failed for {team_key}: {exc}")
                logger.error("Daily email send failed for %s: %s", team_key, exc)

    # 5. Regenerate .ics and schedule docs
    try:
        write_ics_files(all_fixtures, DOCS_DIR)
        _write_index_html()
    except Exception as exc:
        logger.error("ICS generation failed: %s", exc)
        errors.append(f"ICS generation failed: {exc}")

    try:
        write_schedule_files(all_fixtures, REPO_ROOT)
    except Exception as exc:
        logger.error("Schedule doc generation failed: %s", exc)

    # 6. Save new snapshot and commit
    save_snapshot(new_snapshot)
    _commit_changes(test_mode)

    # 7. Health check — report any accumulated errors
    if errors:
        send_health_alert(
            "Errors during watcher run",
            f"Run type: {run_type}\nDate: {today}\n\nErrors:\n" + "\n".join(errors),
        )

    logger.info("=== Run complete ===")


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
    parser.add_argument("run_type", choices=["morning", "evening"], help="Which run to execute")
    parser.add_argument("--test", action="store_true", help="Test mode — send [TEST] emails, skip git commit")
    args = parser.parse_args()
    run(args.run_type, test_mode=args.test)


if __name__ == "__main__":
    main()
