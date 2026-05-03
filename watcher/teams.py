"""Team configuration constants for the Selwyn football watcher."""

SELWYN_ORG_ID = 11255

TEAMS = {
    "2ndxi": {
        "display_name": "Selwyn 2nd XI",
        "audience": "players",
        "coach_first_name": "Will",
        "coach_full_name": "Will Litchfield",
        "training_day": "Thursday",
        "training_time": "15:30",
        "training_location": "Back Field",
        "warmup_minutes_before": 60,
        "teamreach_group_name": "Selwyn 2ndXI Boys Football 2026",
        "teamreach_code": "selwyn2ndxi2026",
        "grade_id": 712053,
        "comp_ids": [12756, 12758],
        "include_van_note_for_school_day_aways": True,
        # Update after each game with first names of who ran the line, e.g. "Sarah and Mike"
        # Set back to None once acknowledged in the next volunteer ask post.
        "last_volunteers": None,
    },
    "13a": {
        "display_name": "Selwyn 13A Boys",
        "audience": "parents",
        "coach_first_name": "Mojtaba",
        "coach_full_name": "Mojtaba Sayed",
        "training_day": "Tuesday",
        "training_time": "07:00",
        "training_location": "Front Field",
        "warmup_minutes_before": 60,
        "teamreach_group_name": "Selwyn 13A Boys Football 2026",
        "teamreach_code": "13afooty2026",
        "grade_id": 712067,
        "comp_ids": [12756, 12758],
        "include_van_note_for_school_day_aways": False,
        # Update after each game with first names of who ran the line, e.g. "Sarah and Mike"
        # Set back to None once acknowledged in the next volunteer ask post.
        "last_volunteers": None,
    },
}
