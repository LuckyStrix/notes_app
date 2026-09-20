"""What each kind of job actually runs. Shared by the web service; the CLI calls
the stage functions directly."""
from . import config, extract, index, rollup, sync, transcribe
from .progress import Ctx

KINDS = ("transcribe", "extract", "rollup", "index", "update")


class _Staged(Ctx):
    """Prefixes progress with which step of a multi-step job we're on."""

    def __init__(self, inner: Ctx, step: str):
        super().__init__(log=inner.log)
        self._inner, self._step = inner, step

    def check(self) -> None:
        self._inner.check()

    def progress(self, done: int, total: int, current: str = "") -> None:
        self._inner.progress(done, total, f"{self._step}: {current}" if current else self._step)


def run(kind: str, params: dict, ctx: Ctx) -> None:
    cfg = config.load()
    notes = sync.load_notes()
    projects = sync.load_projects()
    ids = set(params["ids"]) if params.get("ids") else None
    project = next((p for p in projects if p["id"] == params.get("project_id")), None)

    if kind == "transcribe":
        transcribe.transcribe_pending(cfg, notes, ids=ids, force=bool(params.get("force")), ctx=ctx)
    elif kind == "extract":
        extract.extract_all(cfg, notes, ids=ids, project=project["name"] if project else None,
                            stale_only=bool(params.get("stale_only")), force=bool(params.get("force")), ctx=ctx)
    elif kind == "rollup":
        rollup.rollup_all(cfg, notes, [project] if project else projects, force=bool(params.get("force")), ctx=ctx)
    elif kind == "index":
        index.build(cfg, notes, ctx)
    elif kind == "update":
        # Bring one class fully up to date: stale cards -> class overview -> search index.
        if project is None:
            raise ValueError("update needs a project")
        ctx.log(f"Updating {project['name']}")
        extract.extract_all(cfg, notes, project=project["name"], stale_only=True, ctx=_Staged(ctx, "1/3 summary cards"))
        rollup.rollup_all(cfg, notes, [project], ctx=_Staged(ctx, "2/3 class overview"))
        index.build(cfg, notes, _Staged(ctx, "3/3 search index"))
    else:
        raise ValueError(f"unknown job kind {kind}")
