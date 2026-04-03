from __future__ import annotations

import argparse
import sys

from .config import Paths
from .display import as_json, format_breakdown, format_session, format_summary
from .ingest import get_session, get_session_details
from .metrics import summarize_models, summarize_month, summarize_projects, summarize_today, summarize_week


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codex-stats", description="Local usage analytics for Codex.")
    parser.add_argument("--json", action="store_true", dest="json_output", help="Output JSON.")
    subparsers = parser.add_subparsers(dest="command")

    today_parser = subparsers.add_parser("today", help="Show today's usage summary.")
    today_parser.add_argument("--json", action="store_true", dest="json_output", help="Output JSON.")

    week_parser = subparsers.add_parser("week", help="Show the last 7 days of usage.")
    week_parser.add_argument("--json", action="store_true", dest="json_output", help="Output JSON.")

    month_parser = subparsers.add_parser("month", help="Show the last 30 days of usage.")
    month_parser.add_argument("--json", action="store_true", dest="json_output", help="Output JSON.")

    session_parser = subparsers.add_parser("session", help="Show a session summary.")
    session_parser.add_argument("--id", dest="session_id", help="Specific session ID.")
    session_parser.add_argument("--json", action="store_true", dest="json_output", help="Output JSON.")

    models_parser = subparsers.add_parser("models", help="Show usage by model.")
    models_parser.add_argument("--json", action="store_true", dest="json_output", help="Output JSON.")

    project_parser = subparsers.add_parser("project", help="Show usage by project.")
    project_parser.add_argument("--json", action="store_true", dest="json_output", help="Output JSON.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    paths = Paths.discover()

    if args.command in (None, "today"):
        summary = summarize_today(paths)
        if args.json_output:
            print(as_json(summary.to_dict()))
        else:
            print(format_summary(summary))
        return 0

    if args.command == "week":
        summary = summarize_week(paths)
        if args.json_output:
            print(as_json(summary.to_dict()))
        else:
            print(format_summary(summary))
        return 0

    if args.command == "month":
        summary = summarize_month(paths)
        if args.json_output:
            print(as_json(summary.to_dict()))
        else:
            print(format_summary(summary))
        return 0

    if args.command == "session":
        session = get_session(paths, session_id=args.session_id)
        if session is None:
            print("No Codex session found.", file=sys.stderr)
            return 1
        details = get_session_details(paths, session)
        if args.json_output:
            print(as_json(details.to_dict()))
        else:
            print(format_session(details))
        return 0

    if args.command == "models":
        entries = summarize_models(paths)
        if args.json_output:
            print(as_json({"models": [entry.to_dict() for entry in entries]}))
        else:
            print(format_breakdown("Model Usage", entries))
        return 0

    if args.command == "project":
        entries = summarize_projects(paths)
        if args.json_output:
            print(as_json({"projects": [entry.to_dict() for entry in entries]}))
        else:
            print(format_breakdown("Project Usage", entries))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
