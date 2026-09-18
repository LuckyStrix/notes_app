"""Mirror the notes app's structure and note text into data/snapshot/ (GET-only).

The snapshot is what every later stage reads, so the rest of the pipeline never
needs the notes app to be up. Notes deleted upstream are kept and flagged
rather than removed -- this mirror should never be the reason something is lost.
"""
from datetime import datetime, timezone

from . import store
from .notes_api import NotesAPI


def sync(api: NotesAPI) -> dict:
    store.ensure_dirs()
    projects = api.get("/projects")
    tree = {"synced_at": datetime.now(timezone.utc).isoformat(), "projects": []}
    seen: set[str] = set()
    changed = 0

    for proj in projects:
        groups = api.get(f"/projects/{proj['id']}/groups")
        by_id = {g["id"]: g for g in groups}

        def group_path(gid):
            parts = []
            while gid:
                parts.append(by_id[gid]["name"])
                gid = by_id[gid]["parent_group_id"]
            return list(reversed(parts))

        tree["projects"].append(
            {
                "id": proj["id"],
                "name": proj["name"],
                "description": proj.get("description"),
                "groups": [
                    {"id": g["id"], "name": g["name"], "parent_group_id": g["parent_group_id"], "path": group_path(g["id"])}
                    for g in groups
                ],
            }
        )

        for note in api.get("/notes", project_id=proj["id"]):
            seen.add(note["id"])
            record = {
                "id": note["id"],
                "project_id": proj["id"],
                "project": proj["name"],
                "group_id": note["group_id"],
                "group_path": group_path(note["group_id"]),
                "type": note["type"],
                "title": note["title"],
                "body": note["body"] or "",
                "created_at": note["created_at"],
                "updated_at": note["updated_at"],
                "deleted_upstream": False,
            }
            if note["type"] in ("audio", "video"):
                media = api.get_or_none(f"/notes/{note['id']}/media")
                if media:
                    record["media"] = {
                        "original_filename": media["original_filename"],
                        "duration_seconds": media["duration_seconds"],
                        "size_bytes": media["size_bytes"],
                    }
            path = store.SNAPSHOT / "notes" / f"{note['id']}.json"
            if store.read_json(path) != record:
                store.write_json(path, record)
                changed += 1

    flagged = 0
    for path in (store.SNAPSHOT / "notes").glob("*.json"):
        if path.stem not in seen:
            record = store.read_json(path)
            if not record.get("deleted_upstream"):
                record["deleted_upstream"] = True
                store.write_json(path, record)
                flagged += 1

    store.write_json(store.SNAPSHOT / "tree.json", tree)
    return {"notes_seen": len(seen), "written_or_updated": changed, "flagged_deleted_upstream": flagged}


def load_notes(include_deleted: bool = False) -> list[dict]:
    notes = [store.read_json(p) for p in sorted((store.SNAPSHOT / "notes").glob("*.json"))]
    return [n for n in notes if include_deleted or not n.get("deleted_upstream")]
