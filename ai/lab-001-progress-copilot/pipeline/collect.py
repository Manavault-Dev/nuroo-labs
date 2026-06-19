"""
Collect child progress data from Firestore.

Exports per-child records including:
  - progress scores (6 domains)
  - completed tasks with dailyId and category
  - specialist notes (visibleToParent=false included for AI context)
  - parent feedback (mood + comment)
  - activity timeline (tasksAttempted / tasksCompleted per day)

Usage:
    python collect.py --org <orgId> --out datasets/raw/
    python collect.py --user <userId> --out datasets/raw/
    python collect.py --all --out datasets/raw/          # requires superAdmin
"""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, firestore

# ---------------------------------------------------------------------------
# Firebase init
# ---------------------------------------------------------------------------

def init_firebase() -> firestore.Client:
    cred_path = os.environ.get("FIREBASE_CREDENTIALS")
    if not cred_path:
        raise EnvironmentError(
            "Set FIREBASE_CREDENTIALS env var to your service-account JSON path"
        )
    if not firebase_admin._apps:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
    return firestore.client()


# ---------------------------------------------------------------------------
# Collectors
# ---------------------------------------------------------------------------

def collect_child(db: firestore.Client, user_id: str) -> dict | None:
    """Return a single child record ready for cleaning."""
    user_ref = db.collection("users").document(user_id)
    user_snap = user_ref.get()
    if not user_snap.exists:
        return None

    data = user_snap.to_dict()

    # Tasks
    tasks_snap = (
        db.collection("tasks")
        .where("userId", "==", user_id)
        .stream()
    )
    tasks = []
    for t in tasks_snap:
        td = t.to_dict()
        tasks.append({
            "id": t.id,
            "title": td.get("title"),
            "category": td.get("category"),
            "dailyId": td.get("dailyId"),
            "completed": td.get("completed", False),
            "completedAt": _ts(td.get("completedAt")),
            "difficulty": td.get("difficulty"),
        })

    # Specialist notes (org context)
    notes_snap = (
        db.collection("specialistNotes")
        .where("childId", "==", user_id)
        .stream()
    )
    notes = []
    for n in notes_snap:
        nd = n.to_dict()
        notes.append({
            "id": n.id,
            "specialistName": nd.get("specialistName"),
            "text": nd.get("text"),
            "tags": nd.get("tags", []),
            "visibleToParent": nd.get("visibleToParent", True),
            "createdAt": _ts(nd.get("createdAt")),
        })

    # Parent feedback
    feedback_snap = (
        db.collection("parentFeedback")
        .where("userId", "==", user_id)
        .order_by("timestamp", direction=firestore.Query.DESCENDING)
        .limit(30)
        .stream()
    )
    feedback = []
    for f in feedback_snap:
        fd = f.to_dict()
        feedback.append({
            "mood": fd.get("mood"),
            "comment": fd.get("comment"),
            "timestamp": _ts(fd.get("timestamp")),
        })

    return {
        "userId": user_id,
        "collectedAt": datetime.now(timezone.utc).isoformat(),
        "progress": data.get("progress", {}),
        "lastTaskDate": data.get("lastTaskDate"),
        "tasks": tasks,
        "specialistNotes": notes,
        "parentFeedback": feedback,
    }


def collect_org(db: firestore.Client, org_id: str) -> list[dict]:
    """Return records for all children in an organization."""
    members_snap = (
        db.collection("organizations")
        .document(org_id)
        .collection("children")
        .stream()
    )
    records = []
    for m in members_snap:
        record = collect_child(db, m.id)
        if record:
            record["orgId"] = org_id
            records.append(record)
    return records


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def save(records: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"raw_{stamp}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"✅ Saved {len(records)} records → {out_file}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Collect Nuroo data from Firestore")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--user", help="Single userId")
    group.add_argument("--org", help="orgId — export all children in org")
    group.add_argument("--all", action="store_true", help="Export all users (superAdmin only)")
    parser.add_argument("--out", default="datasets/raw", help="Output directory")
    args = parser.parse_args()

    db = init_firebase()
    out = Path(args.out)

    if args.user:
        record = collect_child(db, args.user)
        records = [record] if record else []
    elif args.org:
        records = collect_org(db, args.org)
    else:
        all_snap = db.collection("users").stream()
        records = []
        for u in all_snap:
            r = collect_child(db, u.id)
            if r:
                records.append(r)

    if not records:
        print("⚠️  No records found.")
        return

    save(records, out)


if __name__ == "__main__":
    main()
