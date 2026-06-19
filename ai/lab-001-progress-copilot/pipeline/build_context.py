"""
Build structured context for AI Summary and RAG from cleaned records.

Output per child:
  - narrative_context: plain-text summary of all data (for LLM prompt)
  - structured_context: JSON with key facts (for RAG retrieval)

Usage:
    python build_context.py --in datasets/cleaned/cleaned_raw_20240619.json --out datasets/contexts/
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

DOMAIN_LABELS = {
    "communication": "Коммуникация",
    "motor_skills": "Моторика",
    "social": "Социальные навыки",
    "cognitive": "Когнитивное развитие",
    "sensory": "Сенсорная обработка",
    "behavior": "Поведение",
}

MOOD_LABELS = {
    "good": "хорошо",
    "ok": "нормально",
    "hard": "сложно",
}


def build_context(record: dict) -> dict:
    progress = record.get("progress", {})
    tasks = record.get("tasks", [])
    notes = record.get("specialistNotes", [])
    feedback = record.get("parentFeedback", [])

    # --- Progress narrative ---
    progress_lines = []
    for domain, label in DOMAIN_LABELS.items():
        score = progress.get(domain, 0)
        level = _level(score)
        progress_lines.append(f"  • {label}: {score}/100 ({level})")

    dominant = record.get("dominantDomain", "")
    dominant_label = DOMAIN_LABELS.get(dominant, dominant)

    # --- Task statistics ---
    total = len(tasks)
    completed = record.get("totalTasksCompleted", 0)
    rate = round(completed / total * 100) if total else 0
    streak = record.get("streakDays", 0)

    # Recent completed tasks (last 10)
    recent_completed = [
        t for t in tasks if t.get("completed")
    ][-10:]
    task_titles = ", ".join(t["title"] for t in recent_completed if t.get("title")) or "нет данных"

    # --- Specialist notes ---
    specialist_text = ""
    if notes:
        note_lines = []
        for n in notes[-5:]:  # last 5 notes
            date = n.get("createdAt", "")[:10] if n.get("createdAt") else ""
            name = n.get("specialistName", "Специалист")
            text = n.get("text", "").strip()
            tags = ", ".join(n.get("tags") or [])
            line = f"  [{date}] {name}: {text}"
            if tags:
                line += f" (теги: {tags})"
            note_lines.append(line)
        specialist_text = "\n".join(note_lines)
    else:
        specialist_text = "  Заметок специалистов нет."

    # --- Parent feedback ---
    feedback_text = ""
    if feedback:
        mood_counts: dict[str, int] = {}
        comments = []
        for f in feedback:
            mood = f.get("mood", "ok")
            mood_counts[mood] = mood_counts.get(mood, 0) + 1
            if f.get("comment"):
                comments.append(f.get("comment"))
        mood_summary = ", ".join(
            f"{MOOD_LABELS.get(k, k)}: {v}x" for k, v in mood_counts.items()
        )
        feedback_text = f"  Настроение родителя: {mood_summary}"
        if comments:
            feedback_text += f"\n  Последние комментарии: {'; '.join(comments[-3:])}"
    else:
        feedback_text = "  Обратной связи от родителя нет."

    # --- Assemble narrative ---
    narrative = f"""=== Контекст ребёнка ({record['userId']}) ===
Дата сбора: {record.get('collectedAt', '')[:10]}

[Прогресс по областям развития]
{chr(10).join(progress_lines)}
Доминирующая область: {dominant_label}

[Активность]
  Всего задач: {total}, выполнено: {completed} ({rate}%)
  Серия активных дней: {streak}
  Недавние выполненные задачи: {task_titles}

[Заметки специалистов]
{specialist_text}

[Обратная связь родителя]
{feedback_text}
""".strip()

    # --- Structured context for RAG ---
    structured = {
        "userId": record["userId"],
        "orgId": record.get("orgId"),
        "collectedAt": record.get("collectedAt"),
        "progress": progress,
        "dominantDomain": dominant,
        "totalTasksCompleted": completed,
        "completionRate": rate,
        "streakDays": streak,
        "recentTaskTitles": [t["title"] for t in recent_completed if t.get("title")],
        "specialistNoteCount": len(notes),
        "recentNotes": [
            {"specialist": n.get("specialistName"), "text": n.get("text"), "tags": n.get("tags")}
            for n in notes[-3:]
        ],
        "parentMoodSummary": {
            m: sum(1 for f in feedback if f.get("mood") == m)
            for m in ["good", "ok", "hard"]
        },
    }

    return {
        "userId": record["userId"],
        "narrative_context": narrative,
        "structured_context": structured,
    }


def _level(score: int) -> str:
    if score < 30:
        return "начальный уровень"
    if score < 70:
        return "средний уровень"
    return "продвинутый уровень"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build AI context from cleaned Nuroo records")
    parser.add_argument("--in", dest="input", required=True, help="Cleaned JSON file or directory")
    parser.add_argument("--out", default="datasets/contexts", help="Output directory")
    args = parser.parse_args()

    in_path = Path(args.input)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    files = [in_path] if in_path.is_file() else sorted(in_path.glob("cleaned_*.json"))
    if not files:
        print("⚠️  No cleaned_*.json files found.")
        return

    all_contexts = []
    for f in files:
        with open(f, encoding="utf-8") as fh:
            records = json.load(fh)
        contexts = [build_context(r) for r in records]
        all_contexts.extend(contexts)
        print(f"✅ {f.name} → {len(contexts)} contexts built")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"contexts_{stamp}.json"
    with open(out_file, "w", encoding="utf-8") as fh:
        json.dump(all_contexts, fh, ensure_ascii=False, indent=2)

    print(f"\n✅ Total: {len(all_contexts)} contexts → {out_file}")


if __name__ == "__main__":
    main()
