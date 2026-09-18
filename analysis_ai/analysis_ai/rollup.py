"""Roll per-note study cards up into per-folder summaries and a per-class overview,
and write everything out as a readable markdown vault (Obsidian-compatible).

Deterministic where possible: the glossary, logistics list and instructor-emphasis
list are assembled straight from the cards (with a pointer back to the source),
so nothing is lost to LLM summarisation. The model only writes prose: one summary
per folder, and one overview + cross-lecture connections per class.
"""
import hashlib
import re
from datetime import datetime, timezone

from . import ollama, store

ROLLUP_VERSION = "1"
ROLLUPS = store.D / "rollups"

_STR = {"type": "string"}
GROUP_SCHEMA = {"type": "object", "properties": {"summary": _STR}, "required": ["summary"]}
PROJECT_SCHEMA = {
    "type": "object",
    "properties": {
        "overview": {"type": "string", "description": "6-10 sentences: what the course covers so far and how it is structured"},
        "themes": {"type": "array", "items": {"type": "object", "properties": {"name": _STR, "description": _STR},
                                                 "required": ["name", "description"]}},
        "connections": {"type": "array", "items": _STR, "description": "how ideas in different weeks or notes build on or relate to each other"},
    },
    "required": ["overview", "themes", "connections"],
}

GROUP_PROMPT = """Course: {project}. Folder: {folder}.
Below are study cards for the notes in this folder. Write a 4-8 sentence summary of what this folder covers, specific to the actual content (name the theories, terms, examples and any exam/deadline details). Do not invent anything not in the cards.

{cards}
"""
PROJECT_PROMPT = """Course: {project}{description}.
Below are summaries of each folder (e.g. weeks) of a student's notes, recordings and documents for this course, in order.
Write an overview of the course so far, list its main themes, and note concrete connections between ideas in different folders. Use only what the summaries say.

{groups}
"""


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _safe(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .") or "untitled"


def _ref(card: dict, at: str | None) -> str:
    n = card["note"]
    return f"{n['title']} @ {at}" if at else n["title"]


def load_cards(notes: list[dict]) -> list[tuple[dict, dict]]:
    """(note, card) pairs. Short notes become verbatim pseudo-cards."""
    out = []
    for note in notes:
        card = store.read_json(store.CARDS / f"{note['id']}.json")
        if card:
            out.append((note, card))
    return out


def _card_digest(card: dict) -> str:
    return card["meta"]["source_hash"]


def collect(pairs: list[tuple[dict, dict]]) -> dict:
    glossary: dict[str, dict] = {}
    logistics: dict[str, dict] = {}
    emphasis: dict[str, dict] = {}
    for note, card in pairs:
        if card.get("short"):
            continue
        for t in card.get("key_terms", []):
            key = _norm(t["term"])
            entry = glossary.setdefault(key, {"term": t["term"], "definition": t["definition"], "sources": []})
            if len(t["definition"]) > len(entry["definition"]):
                entry["definition"] = t["definition"]
            entry["sources"].append(_ref(card, t.get("at")))
        for bucket, items in ((logistics, card.get("logistics", [])), (emphasis, card.get("instructor_emphasis", []))):
            for it in items:
                text, at = (it["text"], it.get("at")) if isinstance(it, dict) else (it, None)
                bucket.setdefault(_norm(text), {"text": text, "sources": []})["sources"].append(_ref(card, at))
    return {
        "glossary": sorted(glossary.values(), key=lambda e: e["term"].lower()),
        "logistics": list(logistics.values()),
        "emphasis": list(emphasis.values()),
    }


def _card_brief(note: dict, card: dict) -> str:
    if card.get("short"):
        return f"### {note['title']} (short note)\n{card['summary']}"
    topics = "; ".join(t["name"] for t in card.get("topics", []))
    emph = " | ".join(e["text"] if isinstance(e, dict) else e for e in card.get("instructor_emphasis", []))
    log_ = " | ".join(e["text"] if isinstance(e, dict) else e for e in card.get("logistics", []))
    return (f"### {note['title']} ({note['type']})\nSummary: {card['summary']}\nTopics: {topics}\n"
            f"Instructor emphasis: {emph or 'none'}\nLogistics: {log_ or 'none'}")


def rollup_project(cfg: dict, project: dict, notes: list[dict], *, force: bool = False, log=print) -> str:
    pairs = [(n, c) for n, c in load_cards(notes) if n["project_id"] == project["id"]]
    if not pairs:
        return "no-cards"
    model = cfg["models"]["extract"]
    digest = hashlib.sha256(
        (ROLLUP_VERSION + model + "".join(sorted(f"{n['id']}{_card_digest(c)}{n['title']}{'/'.join(n['group_path'])}" for n, c in pairs))).encode()
    ).hexdigest()
    path = ROLLUPS / f"{project['id']}.json"
    existing = store.read_json(path)
    if existing and existing["input_hash"] == digest and not force:
        write_vault(project, pairs, existing)
        return "cached"

    by_group: dict[tuple, list] = {}
    for n, c in pairs:
        by_group.setdefault(tuple(n["group_path"]), []).append((n, c))

    groups = {}
    for gpath in sorted(by_group):
        label = "/".join(gpath) or "(top level)"
        log(f"  folder {label}")
        cards_text = "\n\n".join(_card_brief(n, c) for n, c in sorted(by_group[gpath], key=lambda p: p[0]["created_at"]))
        res = ollama.generate_json(cfg, "extract", GROUP_PROMPT.format(project=project["name"], folder=label, cards=cards_text[:24000]), GROUP_SCHEMA)
        groups[label] = res["summary"]

    log("  course overview")
    desc = f" ({project['description']})" if project.get("description") else ""
    groups_text = "\n\n".join(f"## {k}\n{v}" for k, v in groups.items())
    head = ollama.generate_json(cfg, "extract", PROJECT_PROMPT.format(project=project["name"], description=desc, groups=groups_text), PROJECT_SCHEMA)

    data = {"input_hash": digest, "model": model, "generated_at": datetime.now(timezone.utc).isoformat(),
            "project": project["name"], "groups": groups, **head, **collect(pairs)}
    store.write_json(path, data)
    write_vault(project, pairs, data)
    return "done"


def _fmt_item(it) -> str:
    if isinstance(it, dict):
        return it.get("text") or it.get("statement") or it.get("description") or it.get("name") or ""
    return str(it)


def write_vault(project: dict, pairs: list[tuple[dict, dict]], data: dict) -> None:
    root = store.VAULT / _safe(project["name"])
    root.mkdir(parents=True, exist_ok=True)

    def sources(s):
        return ", ".join(dict.fromkeys(s))

    overview = [f"# {project['name']}", "", data["overview"], "", "## Themes"]
    overview += [f"- **{t['name']}** -- {t['description']}" for t in data["themes"]]
    overview += ["", "## Connections across notes"] + [f"- {c}" for c in data["connections"]]
    overview += ["", "## Folder summaries"] + [f"### {k}\n{v}\n" for k, v in data["groups"].items()]
    (root / "Overview.md").write_text("\n".join(overview) + "\n", encoding="utf-8")

    (root / "Glossary.md").write_text(
        f"# {project['name']} -- Glossary\n\n"
        + "\n".join(f"- **{g['term']}**: {g['definition']}  \n  _{sources(g['sources'])}_" for g in data["glossary"]) + "\n",
        encoding="utf-8")
    (root / "Exams, deadlines and instructor emphasis.md").write_text(
        f"# {project['name']} -- Exams, deadlines and instructor emphasis\n\n## Logistics\n"
        + "\n".join(f"- {l['text']}  \n  _{sources(l['sources'])}_" for l in data["logistics"])
        + "\n\n## Flagged as important\n"
        + "\n".join(f"- {e['text']}  \n  _{sources(e['sources'])}_" for e in data["emphasis"]) + "\n",
        encoding="utf-8")

    for note, card in pairs:
        folder = root.joinpath(*[_safe(p) for p in note["group_path"]])
        folder.mkdir(parents=True, exist_ok=True)
        lines = ["---", f"note_id: {note['id']}", f"course: {project['name']}", f"folder: {'/'.join(note['group_path'])}",
                 f"type: {note['type']}", f"model: {card['meta']['model']}", "---", ""]
        if card.get("short"):
            lines += [f"# {note['title']}", "", card["summary"]]
        else:
            lines += [f"# {card['title']}", f"_{note['title']} ({note['type']})_", "", card["summary"], "", "## Topics"]
            lines += [f"- **{t['name']}**{' [' + t['at'] + ']' if t.get('at') else ''} -- {t['explanation']}" for t in card["topics"]]
            for heading, key in (("Key terms", "key_terms"), ("Formulas and rules", "formulas_and_rules"),
                                 ("Examples", "examples"), ("Instructor emphasis", "instructor_emphasis"), ("Logistics", "logistics")):
                if card.get(key):
                    lines += ["", f"## {heading}"]
                    for it in card[key]:
                        if key == "key_terms":
                            lines.append(f"- **{it['term']}**: {it['definition']}")
                        elif key == "formulas_and_rules":
                            lines.append(f"- {it['statement']} ({it['context']})")
                        elif key == "examples":
                            lines.append(f"- {it['description']} -> {it['takeaway']}")
                        else:
                            lines.append(f"- {_fmt_item(it)}")
        (folder / f"{_safe(note['title'])} [{note['id'][:6]}].md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def rollup_all(cfg: dict, notes: list[dict], projects: list[dict], *, only: str | None = None, force: bool = False) -> None:
    store.ensure_dirs()
    for proj in projects:
        if only and only.lower() not in proj["name"].lower():
            continue
        print(f"{proj['name']}", flush=True)
        try:
            print("  ->", rollup_project(cfg, proj, notes, force=force, log=lambda m: print(m, flush=True)), flush=True)
        except Exception as exc:  # noqa: BLE001 -- keep going on the other classes
            print(f"  -> FAILED: {exc}", flush=True)
