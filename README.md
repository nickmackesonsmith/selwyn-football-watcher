# Selwyn Football Watcher

Automated fixture watcher for Selwyn College 2nd XI and 13A Boys football teams.

Runs twice daily via GitHub Actions, checks Sporty for fixture changes, and emails
ready-to-paste TeamReach posts to the team manager.

## Teams

| Team | Grade | Coach | Training |
|------|-------|-------|----------|
| Selwyn 2nd XI | Premier League Reserve | Will Litchfield | Thu 3:30pm, Back Field |
| Selwyn 13A Boys | Boys 13A2 | Mojtaba Sayed | Tue 7:00am, Front Field |

## Schedule

- **7:00 AM NZ** — Full fixture check, change detection, Monday announcements, volunteer asks
- **6:00 PM NZ** — Change detection, day-before reminders (with weather forecast)

## Calendar Feeds

Subscribe in Apple/Google Calendar to get fixtures automatically:

- 2nd XI: `https://nickmackeson-smith.github.io/selwyn-football-watcher/fixtures_2ndxi.ics`
- 13A: `https://nickmackeson-smith.github.io/selwyn-football-watcher/fixtures_13a.ics`

## GitHub Secrets Required

| Secret | Value |
|--------|-------|
| `GMAIL_USER` | nickmackesonsmith@gmail.com |
| `GMAIL_APP_PASSWORD` | 16-char app password from myaccount.google.com/apppasswords |

## Manual run

To trigger a test run: Actions → Morning fixtures check → Run workflow → test_mode: true
