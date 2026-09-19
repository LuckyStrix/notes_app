"""Per-note / per-class pipeline status, for the Pipeline and Library screens."""
from . import chunking, extract, index, rollup, store, sync, transcribe


def overview(cfg: dict) -> dict:
    notes = sync.load_notes()
    tree = sync.load_tree()
    idx = index.index_state(cfg, notes)
    projects = []
    for proj in tree["projects"]:
        rows = []
        for n in sorted((n for n in notes if n["project_id"] == proj["id"]),
                        key=lambda n: ("/".join(n["group_path"]), n["created_at"])):
            is_media = n["type"] in ("audio", "video")
            transcript = transcribe.load(n["id"]) if is_media else None
            text = chunking.source_text(n)
            rows.append({
                "id": n["id"], "title": n["title"], "type": n["type"], "folder": "/".join(n["group_path"]),
                "created_at": n["created_at"], "updated_at": n["updated_at"], "chars": len(text or ""),
                "duration": (n.get("media") or {}).get("duration_seconds"),
                "estimate_seconds": transcribe.estimate_seconds(n) if is_media else None,
                "transcript": (None if not is_media else {
                    "model": transcript.get("model"), "language": transcript.get("language"),
                    "segments": len(transcript.get("segments", [])),
                } if transcript else False),
                "card": extract.card_state(cfg, n),
                "index": idx.get(n["id"], "none"),
            })
        projects.append({"id": proj["id"], "name": proj["name"], "description": proj.get("description"),
                         "notes": rows, "rollup": rollup.rollup_state(cfg, proj, notes)})
    return {"projects": projects, "synced_at": tree["synced_at"]}


def library(project_id: str) -> dict | None:
    """The compiled material for one class, or None if nothing has been built yet."""
    return store.read_json(rollup.ROLLUPS / f"{project_id}.json")
