from __future__ import annotations

"""
Clean and normalize raw Firestore export.

What this does:
  - Drops records with no progress scores
  - Fills missing progress fields with 0
  - Deduplicates tasks by id
  - Filters out empty/null specialist notes
  - Normalizes mood values to canonical set
  - Adds derived fields: total_completed, streak_days, dominant_domain

Usage:
    python clean.py --in datasets/raw/raw_20240619_120000.json --out datasets/cleaned/
    python clean.py --in datasets/raw/ --out datasets/cleaned/   # batch all files
"""

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROGRESS_DOMAINS = [
    "communication",
    "motor_skills",
    "social",
    "cognitive",
    "sensory",
    "behavior",
]

MOOD_MAP = {
    "good": "good",
    "ok": "ok",
    "hard": "hard",
    "bad": "hard",   # legacy alias
    "great": "good", # legacy alias
}


def clean_record(raw: dict) -> dict | None:
    progress = raw.get("progress") or {}

    # Drop records with no meaningful progress data
    if not any(progress.get(d) for d in PROGRESS_DOMAINS):
        return None

    # Normalize progress scores: fill missing with 0, clamp 0–100
    clean_progress = {
        d: max(0, min(100, int(progress.get(d) or 0)))
        for d in PROGRESS_DOMAINS
    }

    # Derived: dominant domain (highest score)
    dominant = max(clean_progress, key=lambda k: clean_progress[k])

    # Tasks: deduplicate, keep only meaningful fields
    seen_ids: set[str] = set()
    tasks = []
    for t in raw.get("tasks") or []:
        tid = t.get("id")
        if not tid or tid in seen_ids:
            continue
        seen_ids.add(tid)
        tasks.append({
            "id": tid,
            "title": (t.get("title") or "").strip(),
            "category": t.get("category"),
            "dailyId": t.get("dailyId"),
            "completed": bool(t.get("completed")),
            "completedAt": t.get("completedAt"),
            "difficulty": t.get("difficulty"),
        })

    total_completed = sum(1 for t in tasks if t["completed"])

    # Streak: count consecutive days with at least 1 completed task
    completed_days = sorted(
        {t["dailyId"] for t in tasks if t["completed"] and t.get("dailyId")},
        reverse=True,
    )
    streak = _calc_streak(completed_days)

    # Specialist notes: drop blank text
    notes = [
        n for n in (raw.get("specialistNotes") or [])
        if (n.get("text") or "").strip()
    ]

    # Parent feedback: normalize mood
    feedback = []
    for f in (raw.get("parentFeedback") or []):
        mood = MOOD_MAP.get(f.get("mood") or "", None)
        if not mood:
            continue
        feedback.append({
            "mood": mood,
            "comment": (f.get("comment") or "").strip() or None,
            "timestamp": f.get("timestamp"),
        })

    return {
        "userId": raw["userId"],
        "orgId": raw.get("orgId"),
        "collectedAt": raw.get("collectedAt"),
        "cleanedAt": datetime.now(timezone.utc).isoformat(),
        "progress": clean_progress,
        "dominantDomain": dominant,
        "totalTasksCompleted": total_completed,
        "streakDays": streak,
        "lastTaskDate": raw.get("lastTaskDate"),
        "tasks": tasks,
        "specialistNotes": notes,
        "parentFeedback": feedback,
    }


def _calc_streak(sorted_days: list[str]) -> int:
    if not sorted_days:
        return 0
    streak = 1
    for i in range(1, len(sorted_days)):
        prev = datetime.fromisoformat(sorted_days[i - 1])
        curr = datetime.fromisoformat(sorted_days[i])
        if (prev - curr).days == 1:
            streak += 1
        else:
            break
    return streak


def clean_file(in_path: Path, out_dir: Path) -> int:
    with open(in_path, encoding="utf-8") as f:
        raw_records = json.load(f)

    cleaned = []
    skipped = 0
    for r in raw_records:
        result = clean_record(r)
        if result:
            cleaned.append(result)
        else:
            skipped += 1

    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"cleaned_{in_path.stem}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=2)

    print(f"✅ {in_path.name} → {out_file.name}  ({len(cleaned)} clean, {skipped} skipped)")
    return len(cleaned)


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean raw Nuroo Firestore export")
    parser.add_argument("--in", dest="input", required=True, help="Raw JSON file or directory")
    parser.add_argument("--out", default="datasets/cleaned", help="Output directory")
    args = parser.parse_args()

    in_path = Path(args.input)
    out_dir = Path(args.out)

    if in_path.is_dir():
        files = sorted(in_path.glob("raw_*.json"))
        if not files:
            print("⚠️  No raw_*.json files found.")
            return
        total = sum(clean_file(f, out_dir) for f in files)
        print(f"\n✅ Total clean records: {total}")
    else:
        clean_file(in_path, out_dir)


if __name__ == "__main__":
    main()
