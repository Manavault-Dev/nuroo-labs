#!/usr/bin/env python3
"""
Phase 2: AI Summary — generate structured progress reports via Claude API.

Takes context files built by build_context.py and calls Claude to produce
a concise, actionable summary in Russian for specialists and parents.

Usage:
    python summarize.py --in datasets/contexts/contexts_20240619_120000.json
    python summarize.py --in datasets/contexts/  --out datasets/summaries/
    python summarize.py --in datasets/contexts/  --model claude-haiku-4-5  # cost-optimised
"""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = """Ты — AI-ассистент платформы Nuroo для специалистов по развитию детей.
Тебе даётся контекст прогресса ребёнка, собранный из базы данных.
Твоя задача — составить краткий, понятный отчёт на русском языке.

Структура отчёта:
1. **Краткое резюме** (2–3 предложения об общей картине)
2. **Сильные стороны** (домены с высоким прогрессом)
3. **Зоны роста** (домены с низким прогрессом, конкретные рекомендации)
4. **Активность** (оценка вовлечённости ребёнка и семьи)
5. **Следующий шаг** (одна конкретная рекомендация специалисту)

Тон: профессиональный, но тёплый. Без общих фраз — только конкретика из данных."""


def build_prompt(narrative: str) -> str:
    return f"""Вот контекст прогресса ребёнка:

{narrative}

Составь структурированный отчёт согласно инструкции."""


def summarize_child(
    client: anthropic.Anthropic,
    context: dict,
    model: str,
) -> dict:
    narrative = context.get("narrative_context", "")
    user_id = context.get("userId", "unknown")

    message = client.messages.create(
        model=model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_prompt(narrative)}],
    )

    summary_text = message.content[0].text if message.content else ""

    return {
        "userId": user_id,
        "model": model,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "inputTokens": message.usage.input_tokens,
        "outputTokens": message.usage.output_tokens,
        "summary": summary_text,
        "structured_context": context.get("structured_context", {}),
    }


def process_file(
    in_path: Path,
    out_dir: Path,
    model: str,
    client: anthropic.Anthropic,
    limit: int | None = None,
) -> int:
    with open(in_path, encoding="utf-8") as f:
        contexts = json.load(f)

    if limit:
        contexts = contexts[:limit]

    total_in = len(contexts)
    summaries = []
    for i, ctx in enumerate(contexts, 1):
        uid = ctx.get("userId", "?")
        try:
            result = summarize_child(client, ctx, model)
            summaries.append(result)
            print(f"  [{i}/{total_in}] ✅ {uid} — {result['outputTokens']} tokens")
        except anthropic.APIError as e:
            print(f"  [{i}/{total_in}] ❌ {uid} — {e}")
            summaries.append({"userId": uid, "error": str(e)})

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    stem = in_path.stem.replace("contexts_", "summaries_")
    out_file = out_dir / f"{stem}_{stamp}.json"

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(summaries, f, ensure_ascii=False, indent=2)

    print(f"✅ {in_path.name} → {out_file.name}  ({len(summaries)} summaries)")
    return len(summaries)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate AI summaries for Nuroo child progress")
    parser.add_argument("--in", dest="input", required=True, help="Context JSON file or directory")
    parser.add_argument("--out", default="datasets/summaries", help="Output directory")
    parser.add_argument(
        "--model",
        default="claude-haiku-4-5",
        help="Claude model ID (default: claude-haiku-4-5; use claude-opus-4-8 for higher quality)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max number of records to process (useful for testing)",
    )
    args = parser.parse_args()

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("❌ ANTHROPIC_API_KEY not set. Add it to .env or environment.")

    client = anthropic.Anthropic(api_key=api_key)
    in_path = Path(args.input)
    out_dir = Path(args.out)

    files = [in_path] if in_path.is_file() else sorted(in_path.glob("contexts_*.json"))
    if not files:
        raise SystemExit("⚠️  No contexts_*.json files found.")

    print(f"🤖 Model: {args.model}")
    if args.limit:
        print(f"⚡ Limit: {args.limit} records")

    total = 0
    for f in files:
        print(f"\n📄 Processing {f.name}…")
        total += process_file(f, out_dir, args.model, client, limit=args.limit)

    print(f"\n✅ Done — {total} summaries generated → {out_dir}/")


if __name__ == "__main__":
    main()
