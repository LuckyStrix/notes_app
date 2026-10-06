"""CLI entry point: serve | run [--dry-run] | auth-google | healthcheck."""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from .config import Env, NOTE_INSTRUCTIONS, NOTE_SETTINGS, NOTE_STATUS, parse_settings
from .control import ensure_control_notes, update_if_changed
from .notes_api import NotesApi
from .panel import Router
from .pipeline import run_brief, status_text
from .scheduler import POLL_SECONDS, Scheduler


def _build(env: Env):
    return NotesApi(env.notes_api_url), Router(env.router_url, env.router_api_key)


def cmd_run(env: Env, dry_run: bool) -> int:
    api, router = _build(env)
    api.ensure_brief_project()
    notes = ensure_control_notes(api)
    settings, warnings = parse_settings(api.note(notes[NOTE_SETTINGS]["id"])["body"] or "")
    result = run_brief(env, settings, warnings, api, router, api.note(notes[NOTE_INSTRUCTIONS]["id"])["body"] or "",
                       dry_run=dry_run)
    if dry_run:
        print(result.body)
    else:
        update_if_changed(api, notes[NOTE_STATUS], status_text(result, datetime.now(), settings, warnings))
    for line in [*result.panel.notes, *result.source_errors, *warnings]:
        print(f"- {line}", file=sys.stderr)
    return 0


def cmd_healthcheck(env: Env) -> int:
    """For the container HEALTHCHECK: the serve loop touches a heartbeat file every poll."""
    try:
        age = time.time() - float((env.data_dir / "heartbeat").read_text())
    except (OSError, ValueError):
        return 1
    return 0 if age < POLL_SECONDS * 5 else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="daily_brief")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", help="the scheduler loop (what the container runs)")
    run = sub.add_parser("run", help="make a brief now")
    run.add_argument("--dry-run", action="store_true", help="print it, save nothing")
    auth = sub.add_parser("auth-google", help="one-time Google consent; run where a browser is available")
    auth.add_argument("--client-secret", type=Path, required=True, help="OAuth client JSON from Google Cloud Console")
    auth.add_argument("--token-out", type=Path, default=Path("data/google_token.json"),
                      help="where to write the token (default: data/google_token.json, which is the folder "
                           "the container mounts when you run this from daily_brief/)")
    sub.add_parser("healthcheck")
    args = ap.parse_args(argv)
    env = Env.from_environ()

    if args.cmd == "serve":
        api, router = _build(env)
        Scheduler(env, api, router).serve()
    elif args.cmd == "run":
        return cmd_run(env, args.dry_run)
    elif args.cmd == "auth-google":
        from .google import authorize
        authorize(args.client_secret, args.token_out)
        print(f"Token saved to {args.token_out}. Copy it to daily_brief/data/google_token.json on the host that runs the container.")
    elif args.cmd == "healthcheck":
        return cmd_healthcheck(env)
    return 0


if __name__ == "__main__":
    sys.exit(main())
