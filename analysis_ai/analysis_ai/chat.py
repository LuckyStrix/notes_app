"""NotebookLM-style chat over the compiled notes.

Every turn's context is: the class overview + glossary + exam/logistics list
(the "compiled" knowledge, always present, so broad questions work without
retrieval having to guess) plus the top retrieved raw passages, numbered so the
model can cite them. Citations are then resolved to note + timestamp/page.
"""
import re
import sys

from . import index, ollama, rollup, store

SYSTEM = """You are a study assistant working from a student's own course material: their typed notes, transcripts of recorded classes, and course documents (scope: {scope}).

Rules:
- Ground every answer in the material provided. Cite passages inline as [n], matching the numbered PASSAGES. Only cite a passage that directly supports the specific claim; if you are unsure, leave the citation off rather than guess one.
- COURSE OVERVIEW, GLOSSARY and EXAMS sections are compiled background. Use them, but do not contradict the PASSAGES, and do not cite them with [n].
- If the material does not cover the question, say so plainly instead of filling the gap. {outside}
- Recordings are auto-transcribed and can contain misheard words; use context to interpret them.
- Be concrete and concise. Use the lecturer's terminology. Use Markdown where it helps (lists, equations in plain text)."""

OUTSIDE = {
    "strict": "Do not use outside knowledge.",
    "open": "You may add brief outside knowledge to clarify, but label it clearly as '(outside your notes)'.",
}

TASKS = {
    "quiz": "Write a {n}-question practice quiz on {topic}. Mix conceptual and applied questions in the style the material suggests (e.g. essay or graphical if the exam is). Put an answer key with brief explanations and passage citations at the end.",
    "flashcards": "Write {n} flashcards on {topic} as 'Q: ... / A: ...' pairs, covering the key terms, rules and examples in the material.",
    "guide": "Write a structured study guide for {topic}: key concepts with definitions, how they connect, worked examples from the material, and anything flagged as important or testable.",
}
DEFAULT_TOPIC = "the material covered so far, prioritising anything flagged as exam-relevant"


def resolve_scope(names: list[str] | None) -> list[str] | None:
    """Project names matching the given substrings, or None for everything."""
    if not names:
        return None
    all_names = [p["name"] for p in store.read_json(store.SNAPSHOT / "tree.json")["projects"]]
    picked = [n for n in all_names if any(q.lower() in n.lower() for q in names)]
    if not picked:
        raise SystemExit(f"No class matches {names}. Available: {', '.join(all_names)}")
    return picked


def _compiled_context(projects: list[str]) -> str:
    parts = []
    single = len(projects) == 1
    for name in projects:
        pid = next((p["id"] for p in store.read_json(store.SNAPSHOT / "tree.json")["projects"] if p["name"] == name), None)
        data = store.read_json(rollup.ROLLUPS / f"{pid}.json") if pid else None
        if not data:
            continue
        block = [f"## {name}", data["overview"]]
        block += [f"Theme -- {t['name']}: {t['description']}" for t in data["themes"]]
        block += [f"### {k}\n{v}" for k, v in data["groups"].items()]
        parts.append("COURSE OVERVIEW\n" + "\n".join(block)[: 6000 if single else 2500])
        if single:
            gl = "\n".join(f"- {g['term']}: {g['definition']}" for g in data["glossary"])
            parts.append("GLOSSARY\n" + gl[:8000])
        ex = [f"- {l['text']}" for l in data["logistics"]] + [f"- (flagged) {e['text']}" for e in data["emphasis"]]
        if ex:
            parts.append(f"EXAMS, DEADLINES, INSTRUCTOR EMPHASIS ({name})\n" + "\n".join(ex)[:3000])
    return "\n\n".join(parts)


def source_label(p: dict) -> str:
    where = f" @ {p['label']}" if p["label"] else ""
    return f"{p['project']} > {p['folder'] or '(top)'} > {p['title']}{where}"


def build_user_message(cfg: dict, projects: list[str], query: str, request: str, k: int | None = None):
    passages = index.search(cfg, query, projects=projects, k=k)
    plist = "\n\n".join(f"[{i}] ({source_label(p)})\n{p['text']}" for i, p in enumerate(passages, 1))
    msg = f"{_compiled_context(projects)}\n\nPASSAGES\n{plist or '(none retrieved)'}\n\nREQUEST: {request}"
    return msg, passages


def answer(cfg: dict, projects: list[str], history: list[dict], request: str, *, query: str | None = None,
           mode: str = "strict", k: int | None = None):
    """Yields text chunks, then returns (via StopIteration.value) the passages used."""
    msg, passages = build_user_message(cfg, projects, query or request, request, k)
    system = SYSTEM.format(scope=", ".join(projects), outside=OUTSIDE[mode])
    messages = [{"role": "system", "content": system}, *history, {"role": "user", "content": msg}]
    text = []
    for piece in ollama.chat_stream(cfg, "chat", messages):
        text.append(piece)
        yield piece
    return "".join(text), passages


def cited_sources(text: str, passages: list[dict]) -> list[str]:
    nums = sorted({int(n) for n in re.findall(r"\[(\d+)\]", text) if 1 <= int(n) <= len(passages)})
    return [f"[{n}] {source_label(passages[n - 1])}" for n in nums]


def run_turn(cfg, projects, history, request, *, query=None, mode="strict", k=None, out=sys.stdout) -> str:
    gen = answer(cfg, projects, history, request, query=query, mode=mode, k=k)
    full, passages = "", []
    try:
        while True:
            piece = next(gen)
            out.write(piece)
            out.flush()
    except StopIteration as stop:
        full, passages = stop.value
    srcs = cited_sources(full, passages)
    if srcs:
        out.write("\n\nSources:\n" + "\n".join(f"  {s}" for s in srcs))
    out.write("\n")
    return full


def repl(cfg: dict, projects: list[str]) -> None:
    print(f"Scope: {', '.join(projects)}  |  model: {cfg['models']['chat']}")
    print("Ask anything. Commands: /quiz [n] [topic]  /flashcards [n] [topic]  /guide [topic]  /open  /strict  /new  /quit\n")
    history: list[dict] = []
    mode = "strict"
    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line in ("/quit", "/exit"):
            return
        if line == "/new":
            history = []
            print("(new conversation)")
            continue
        if line in ("/open", "/strict"):
            mode = line[1:]
            print(f"(mode: {mode})")
            continue
        query = None
        k = None
        request = line
        m = re.match(r"/(quiz|flashcards|guide)\s*(.*)", line)
        if m:
            task, rest = m.groups()
            n = 8 if task != "flashcards" else 12
            num = re.match(r"(\d+)\s*(.*)", rest)
            if num:
                n, rest = int(num.group(1)), num.group(2)
            topic = rest.strip() or DEFAULT_TOPIC
            request = TASKS[task].format(n=n, topic=topic)
            query = rest.strip() or "key concepts, definitions, exam, important"
            k = 14
        elif len(line.split()) < 6 and history:  # short follow-up: keep the previous topic in the search
            query = f"{next((h['content'] for h in reversed(history) if h['role'] == 'user'), '')} {line}"[-400:]
        reply = run_turn(cfg, projects, history, request, query=query, mode=mode, k=k)
        history += [{"role": "user", "content": request}, {"role": "assistant", "content": reply}]
        history = history[-8:]
