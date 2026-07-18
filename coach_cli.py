# -*- coding: utf-8 -*-
"""Офлайн-CLI коуча (Stage B1).

Пример:
    python coach_cli.py reports/friend_clip3.json \
        --frames reports/evidence/friend_clip3 \
        --out coach_friend_clip3.json

Провайдер LLM — флаг --provider (gemini | anthropic) или env COACH_PROVIDER
(по умолчанию gemini); ключ под провайдера — GEMINI_API_KEY / ANTHROPIC_API_KEY
из окружения / .env; модель — --model или COACH_MODEL.
"""
import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Sequence


def collect_frames(frames_dir: Path) -> List[Path]:
    """Отсортированный список jpg-улик из каталога."""
    return sorted(frames_dir.glob("*.jpg"))


def main(argv: Optional[Sequence[str]] = None, client=None) -> int:
    parser = argparse.ArgumentParser(
        description="Коуч: evidence-JSON + кадры-улики -> CoachReport через Claude"
    )
    parser.add_argument("report", help="путь к evidence-JSON движка")
    parser.add_argument(
        "--frames", default=None, help="каталог с аннотированными кадрами-уликами"
    )
    parser.add_argument("--out", required=True, help="куда записать CoachReport JSON")
    parser.add_argument("--model", default=None, help="переопределить модель LLM")
    parser.add_argument(
        "--provider", default=None,
        help="провайдер LLM: gemini | anthropic (по умолчанию из COACH_PROVIDER)")
    args = parser.parse_args(argv)

    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    frames = collect_frames(Path(args.frames)) if args.frames else []

    if client is None:
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass
        from coach.providers.factory import create_coach_client

        client = create_coach_client(provider=args.provider, model=args.model)

    from coach.validate import run_coach_validated

    result = run_coach_validated(client, report, frames)
    if result.coach_failed:
        print(
            "Коуч не прошёл groundedness-валидацию "
            f"({result.attempts} попытки):",
            file=sys.stderr,
        )
        for error in result.errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    from coach.drill_catalog import finalize_plan

    coach_report = result.coach_report
    plan = finalize_plan(coach_report.drills, report.get("findings", []))
    out_doc = coach_report.model_dump()
    out_doc["drills"] = [d.model_dump() for d in plan.drills]
    out_doc["caveats"] = out_doc["caveats"] + plan.extra_caveats

    out_path = Path(args.out)
    out_path.write_text(
        json.dumps(out_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"CoachReport записан: {out_path} (попыток: {result.attempts})")
    print(f"Дриллов: {len(out_doc['drills'])}, "
          f"объяснений: {len(coach_report.findings_explained)}, "
          f"оговорок: {len(out_doc['caveats'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
