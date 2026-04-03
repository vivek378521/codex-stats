from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .completions import render_completion
from .config import Paths, load_pricing_config
from .config import init_config
from .display import (
    as_json,
    format_breakdown,
    format_compare,
    format_costs,
    format_daily,
    format_doctor,
    format_history,
    format_insights,
    format_report,
    format_report_markdown,
    format_session,
    format_summary,
    format_top,
    resolve_format_options,
)
from .ingest import get_session, get_session_details, iter_session_details
from .metrics import (
    build_report,
    details_for_last_days,
    run_doctor,
    summarize_compare,
    summarize_compare_named,
    summarize_costs,
    summarize_costs_from_details,
    summarize_daily,
    summarize_history,
    summarize_history_from_details,
    summarize_imported_details,
    summarize_insights,
    summarize_insights_from_details,
    summarize_last_days,
    summarize_models,
    summarize_models_from_details,
    summarize_month,
    summarize_project_drilldown,
    summarize_projects,
    summarize_projects_from_details,
    summarize_today,
    summarize_top_sessions,
    summarize_top_sessions_from_details,
    summarize_week,
)
from .transfer import read_imports, write_export


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codex-stats", description="Local usage analytics for Codex.")
    parser.add_argument("--json", action="store_true", dest="json_output", help="Output JSON.")
    parser.add_argument("--days", type=int, help="Show a rolling summary for the last N days.")
    parser.add_argument(
        "--color",
        choices=["auto", "always", "never"],
        default="auto",
        help="Control ANSI color output.",
    )
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

    project_parser = subparsers.add_parser("project", help="Show usage by project or inspect a single project.")
    project_parser.add_argument("name", nargs="?", help="Optional project name for a drilldown view.")
    project_parser.add_argument("--days", type=int, help="Limit a project drilldown to the last N days.")
    project_parser.add_argument("--json", action="store_true", dest="json_output", help="Output JSON.")

    daily_parser = subparsers.add_parser("daily", help="Show per-day usage and a trend graph.")
    daily_parser.add_argument("--json", action="store_true", dest="json_output", help="Output JSON.")
    daily_parser.add_argument("--days", type=int, default=7, help="Number of days to show.")

    compare_parser = subparsers.add_parser("compare", help="Compare the last N days to the previous N days.")
    compare_parser.add_argument("--json", action="store_true", dest="json_output", help="Output JSON.")
    compare_parser.add_argument("--days", type=int, default=7, help="Days per comparison window.")
    compare_parser.add_argument("current", nargs="?", choices=["today", "week", "month"], help="Named current window.")
    compare_parser.add_argument("previous", nargs="?", choices=["yesterday", "last-week", "last-month"], help="Named previous window.")

    history_parser = subparsers.add_parser("history", help="Show recent session history.")
    history_parser.add_argument("--json", action="store_true", dest="json_output", help="Output JSON.")
    history_parser.add_argument("--limit", type=int, default=10, help="Maximum sessions to show.")

    top_parser = subparsers.add_parser("top", help="Show the largest sessions.")
    top_parser.add_argument("--json", action="store_true", dest="json_output", help="Output JSON.")
    top_parser.add_argument("--limit", type=int, default=5, help="Maximum sessions to show.")
    top_parser.add_argument("--project", dest="project_name", help="Filter top sessions to one project.")

    costs_parser = subparsers.add_parser("costs", help="Show estimated cost breakdown.")
    costs_parser.add_argument("--json", action="store_true", dest="json_output", help="Output JSON.")
    costs_parser.add_argument("--days", type=int, help="Use the last N days for the projection basis.")

    insights_parser = subparsers.add_parser("insights", help="Show usage insights.")
    insights_parser.add_argument("--json", action="store_true", dest="json_output", help="Output JSON.")
    insights_parser.add_argument("--days", type=int, help="Analyze the last N days.")

    export_parser = subparsers.add_parser("export", help="Export normalized local stats to JSON.")
    export_parser.add_argument("output", help="Output JSON file.")
    export_parser.add_argument("--since", help="Only export the last Nd of sessions, for example 30d.")

    import_parser = subparsers.add_parser("import", help="Read an exported stats JSON file.")
    import_parser.add_argument("input", nargs="+", help="One or more input JSON files.")
    import_parser.add_argument("--json", action="store_true", dest="json_output", help="Output JSON.")

    doctor_parser = subparsers.add_parser("doctor", help="Validate local Codex data sources.")
    doctor_parser.add_argument("--json", action="store_true", dest="json_output", help="Output JSON.")

    completions_parser = subparsers.add_parser("completions", help="Print shell completion script.")
    completions_parser.add_argument("shell", choices=["bash", "zsh", "fish"], help="Shell name.")

    init_parser = subparsers.add_parser("init", help="Create a default config file.")
    init_parser.add_argument("--force", action="store_true", help="Overwrite an existing config.")

    report_parser = subparsers.add_parser("report", help="Generate a shareable usage report.")
    report_parser.add_argument("period", choices=["weekly", "monthly"], help="Report period.")
    report_parser.add_argument("--format", choices=["text", "markdown", "json"], default="text", help="Output format.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    paths = Paths.discover()
    options = resolve_format_options(args.color)

    if args.command in (None, "today"):
        summary = summarize_last_days(paths, args.days) if args.days else summarize_today(paths)
        if args.json_output:
            print(as_json(summary.to_dict()))
        else:
            print(format_summary(summary, options))
        return 0

    if args.command == "week":
        summary = summarize_week(paths)
        if args.json_output:
            print(as_json(summary.to_dict()))
        else:
            print(format_summary(summary, options))
        return 0

    if args.command == "month":
        summary = summarize_month(paths)
        if args.json_output:
            print(as_json(summary.to_dict()))
        else:
            print(format_summary(summary, options))
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
            print(format_session(details, options))
        return 0

    if args.command == "models":
        entries = summarize_models(paths)
        if args.json_output:
            print(as_json({"models": [entry.to_dict() for entry in entries]}))
        else:
            print(format_breakdown("Model Usage", entries, options))
        return 0

    if args.command == "project":
        if args.name:
            summary = summarize_project_drilldown(paths, args.name, days=args.days)
            if args.json_output:
                print(as_json(summary.to_dict()))
            else:
                print(format_summary(summary, options))
        else:
            entries = summarize_projects(paths)
            if args.json_output:
                print(as_json({"projects": [entry.to_dict() for entry in entries]}))
            else:
                print(format_breakdown("Project Usage", entries, options))
        return 0

    if args.command == "daily":
        points = summarize_daily(paths, days=args.days)
        if args.json_output:
            print(as_json({"days": [point.to_dict() for point in points]}))
        else:
            print(format_daily(points, options))
        return 0

    if args.command == "compare":
        if args.current and args.previous:
            report = summarize_compare_named(paths, args.current, args.previous)
        else:
            report = summarize_compare(paths, days=args.days)
        if args.json_output:
            print(as_json(report.to_dict()))
        else:
            print(format_compare(report, options))
        return 0

    if args.command == "history":
        entries = summarize_history(paths, limit=args.limit)
        if args.json_output:
            print(as_json({"history": [entry.to_dict() for entry in entries]}))
        else:
            print(format_history(entries, options))
        return 0

    if args.command == "top":
        if args.project_name:
            pricing = load_pricing_config(paths)
            details = iter_session_details(paths)
            entries = summarize_top_sessions_from_details(
                details,
                pricing,
                limit=args.limit,
                project_name=args.project_name,
            )
        else:
            entries = summarize_top_sessions(paths, limit=args.limit)
        if args.json_output:
            print(as_json({"top": [entry.to_dict() for entry in entries]}))
        else:
            print(format_top(entries, options))
        return 0

    if args.command == "costs":
        if args.days:
            details = details_for_last_days(paths, args.days)
            summary = summarize_details_for_range(args.days, details)
            costs = summarize_costs_from_details(details, today=summary, week=summary, month=summary)
        else:
            costs = summarize_costs(paths)
        if args.json_output:
            print(as_json(costs.to_dict()))
        else:
            print(format_costs(costs, options))
        return 0

    if args.command == "insights":
        if args.days:
            details = details_for_last_days(paths, args.days)
            summary = summarize_details_for_range(args.days, details)
            insights = summarize_insights_from_details(details, month=summary)
        else:
            insights = summarize_insights(paths)
        if args.json_output:
            print(as_json(insights.to_dict()))
        else:
            print(format_insights(insights, options))
        return 0

    if args.command == "export":
        output_path = write_export(paths, Path(args.output).expanduser(), since=args.since)
        print(f"Exported stats to {output_path}")
        return 0

    if args.command == "import":
        pricing = load_pricing_config(paths)
        details = read_imports([Path(input_path).expanduser() for input_path in args.input])
        summary = summarize_imported_details(details, pricing=pricing)
        if args.json_output:
            print(
                as_json(
                    {
                        "summary": summary.to_dict(),
                        "models": [entry.to_dict() for entry in summarize_models_from_details(details, pricing)],
                        "projects": [entry.to_dict() for entry in summarize_projects_from_details(details, pricing)],
                        "history": [entry.to_dict() for entry in summarize_history_from_details(details, pricing)],
                        "top": [entry.to_dict() for entry in summarize_top_sessions_from_details(details, pricing)],
                        "costs": summarize_costs_from_details(details, pricing=pricing).to_dict(),
                        "insights": summarize_insights_from_details(details, pricing=pricing).to_dict(),
                    }
                )
            )
        else:
            print(format_summary(summary, options))
        return 0

    if args.command == "doctor":
        checks = run_doctor(paths)
        if args.json_output:
            print(as_json({"checks": [check.to_dict() for check in checks]}))
        else:
            print(format_doctor(checks, options))
        return 0

    if args.command == "init":
        config_path = init_config(paths, force=args.force)
        print(f"Initialized config at {config_path}")
        return 0

    if args.command == "completions":
        print(render_completion(args.shell), end="")
        return 0

    if args.command == "report":
        report = build_report(paths, period=args.period)
        if args.format == "json":
            print(as_json(report.to_dict()))
        elif args.format == "markdown":
            print(format_report_markdown(report))
        else:
            print(format_report(report, options))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())


def summarize_details_for_range(days: int, details):
    return summarize_imported_details(details, label=f"last {max(days, 1)} days")
