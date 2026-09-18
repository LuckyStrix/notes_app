import argparse
import sys

from . import config, store
from .notes_api import NotesAPI


def _projects() -> list[dict]:
    return store.read_json(store.SNAPSHOT / "tree.json")["projects"]


def main() -> int:
    cfg = config.load()
    parser = argparse.ArgumentParser(prog="analysis_ai", description="Optional local study analysis for notes_app")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("sync", help="mirror notes/folders from the notes app (GET-only)")

    p = sub.add_parser("transcribe", help="Whisper-transcribe audio/video notes lacking a transcript (manual, GPU)")
    p.add_argument("--only", help="note id prefix")

    p = sub.add_parser("extract", help="build per-note study cards (chunked; cached, so re-runs only redo changes)")
    p.add_argument("--only", help="note id prefix")
    p.add_argument("--project", help="class name substring")
    p.add_argument("--model", help="override the extract model for this run")
    p.add_argument("--force", action="store_true", help="redo even if cached")

    p = sub.add_parser("rollup", help="per-folder summaries, class overview, glossary; writes the markdown vault")
    p.add_argument("--only", help="class name substring")
    p.add_argument("--model", help="override the model for this run")
    p.add_argument("--force", action="store_true")

    sub.add_parser("index", help="build/refresh the retrieval index (embeddings + full-text)")

    p = sub.add_parser("build", help="sync + extract + rollup + index (does NOT transcribe)")
    p.add_argument("--model", help="override the extract model for this run")

    for name, help_ in (("chat", "interactive chat over your notes"), ("ask", "one-shot question")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--project", "-p", action="append", help="class name substring (repeatable); default: all")
        p.add_argument("--model", help="override the chat model for this run")
        p.add_argument("--open", action="store_true", help="allow labelled outside knowledge")
        if name == "ask":
            p.add_argument("question")

    sub.add_parser("status", help="show pipeline progress")
    args = parser.parse_args()

    if getattr(args, "model", None):
        stage = {"chat": "chat", "ask": "chat"}.get(args.cmd, "extract")
        cfg["models"][stage] = args.model

    if args.cmd == "sync":
        from . import sync
        print(sync.sync(NotesAPI(cfg["notes_api_url"])))
    elif args.cmd == "transcribe":
        from . import sync, transcribe
        transcribe.transcribe_pending(cfg, sync.load_notes(), args.only)
    elif args.cmd == "extract":
        from . import extract, sync
        extract.extract_all(cfg, sync.load_notes(), only=args.only, project=args.project, force=args.force)
    elif args.cmd == "rollup":
        from . import rollup, sync
        rollup.rollup_all(cfg, sync.load_notes(), _projects(), only=args.only, force=args.force)
    elif args.cmd == "index":
        from . import index, sync
        index.build(cfg, sync.load_notes())
    elif args.cmd == "build":
        from . import extract, index, rollup, sync
        print(sync.sync(NotesAPI(cfg["notes_api_url"])))
        notes = sync.load_notes()
        extract.extract_all(cfg, notes)
        rollup.rollup_all(cfg, notes, _projects())
        index.build(cfg, notes)
    elif args.cmd in ("chat", "ask"):
        from . import chat
        scope = chat.resolve_scope(args.project) or [p["name"] for p in _projects()]
        mode = "open" if args.open else "strict"
        if args.cmd == "ask":
            chat.run_turn(cfg, scope, [], args.question, mode=mode)
        else:
            chat.repl(cfg, scope)
    elif args.cmd == "status":
        from . import sync
        notes = sync.load_notes()
        media = [n for n in notes if n["type"] in ("audio", "video")]
        done = sum((store.TRANSCRIPTS / f"{n['id']}.json").exists() for n in media)
        cards = len(list(store.CARDS.glob("*.json")))
        print(f"notes mirrored: {len(notes)}; media transcribed: {done}/{len(media)}; study cards: {cards}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
