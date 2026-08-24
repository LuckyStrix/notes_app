import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base import LLMProvider, Message
from app.llm.embeddings import embed_texts
from app.models.embedding import EmbeddingChunk
from app.models.note import Note

TOP_K = 8

# Query-to-passage cosine similarity floor for nomic-embed-text. This is a
# starting point, not a tuned value -- it's a different distribution than the
# keyword-to-keyword SIMILARITY_FLOOR=0.75 in graph_significance.py (short
# phrase vs. short phrase runs much higher than a question vs. a paragraph).
# Chosen to filter obviously-irrelevant chunks without starving context on
# oblique queries; revisit against real query/chunk pairs if answers seem to
# be missing context that should have matched, or noisy chunks keep leaking in.
SIMILARITY_FLOOR = 0.35

SYSTEM_PROMPT = (
    "You are a research assistant answering questions about the user's own notes. "
    "Answer ONLY using the numbered context blocks below -- do not use outside knowledge. "
    "Cite sources inline using [n] matching the context block numbers. Only cite a block when it "
    "directly supports the specific claim being made -- if you're not sure a block actually "
    "supports what you're about to say, omit the citation marker rather than guessing one. "
    "It's fine for a sentence to have no citation if none of the context blocks support it. "
    "If the answer isn't in the context, say so plainly instead of guessing."
)

# Deliberately more permissive than SYSTEM_PROMPT above: graph-view summaries
# are meant to help the user understand a topic, not just answer strictly from
# their notes -- general knowledge is welcome to fill gaps, as long as it's
# clearly distinguished from what the notes actually say.
SUMMARY_SYSTEM_PROMPT = (
    "You are helping the user understand a topic or connection that came up in their own notes. "
    "You're given excerpts from their notes as numbered context blocks below. Ground your summary "
    "in these notes first, citing them inline as [n] for anything drawn from them. You may also add "
    "helpful general knowledge or context the notes don't cover -- when you do, make that clear "
    "(e.g. \"More generally, ...\" or \"For context, ...\") rather than presenting it as something "
    "from the notes. If the notes say nothing relevant at all, say so, then give a brief general "
    "explanation instead. Keep it concise: 3-6 sentences."
)

SUMMARIZE_RESET_PROMPT = (
    "Summarize the conversation below into a concise brief that preserves the key facts, decisions, "
    "and any specific note/topic references discussed, so a new conversation can continue from it "
    "without re-reading the full history. Write it as a short paragraph, not a transcript. Do not use "
    "[n] citation markers -- this summary has no numbered context blocks."
)

CITATION_RE = re.compile(r"\[(\d+)\]")


async def retrieve_chunks(
    db: AsyncSession, query: str, *, project_id: uuid.UUID | None, group_id: uuid.UUID | None, embedding_model: str
) -> list[tuple[EmbeddingChunk, Note, float]]:
    vectors = await embed_texts([query], embedding_model)
    query_vector = vectors[0]

    distance_expr = EmbeddingChunk.embedding.cosine_distance(query_vector)
    similarity_expr = 1 - distance_expr
    stmt = (
        select(EmbeddingChunk, Note, similarity_expr.label("similarity"))
        .join(Note, EmbeddingChunk.note_id == Note.id)
        .where(similarity_expr >= SIMILARITY_FLOOR)
        .order_by(distance_expr)
        .limit(TOP_K)
    )
    if project_id:
        stmt = stmt.where(Note.project_id == project_id)
    if group_id:
        stmt = stmt.where(Note.group_id == group_id)

    result = await db.execute(stmt)
    return [(row[0], row[1], row[2]) for row in result.all()]


def format_timestamp(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}:{s:02d}"


def build_context_block(rows: list[tuple[EmbeddingChunk, Note, float]]) -> str:
    parts = []
    for i, (chunk, note, _similarity) in enumerate(rows, start=1):
        label = f"[{i}] {note.title}"
        if chunk.start_time is not None:
            label += f" @ {format_timestamp(chunk.start_time)}"
        elif chunk.page_start is not None:
            label += f" (p. {chunk.page_start})" if chunk.page_start == chunk.page_end else f" (p. {chunk.page_start}-{chunk.page_end})"
        parts.append(f"{label}\n{chunk.content}")
    return "\n\n".join(parts) if parts else "(no matching notes found)"


def build_system_prompt(context_block: str) -> str:
    return f"{SYSTEM_PROMPT}\n\nContext:\n{context_block}"


def build_summary_system_prompt(context_block: str) -> str:
    return f"{SUMMARY_SYSTEM_PROMPT}\n\nContext from your notes:\n{context_block}"


def extract_cited_ordinals(text: str) -> set[int]:
    return {int(m) for m in CITATION_RE.findall(text)}


def confidence_bucket(similarity: float) -> str:
    """A qualitative hint, not a metric worth showing to two decimal places --
    bucketed against the same query-to-passage similarity scale as
    SIMILARITY_FLOOR, and equally a starting point for tuning."""
    if similarity >= 0.55:
        return "high"
    if similarity >= 0.45:
        return "medium"
    return "low"


def build_citations_payload(full_text: str, rows: list[tuple[EmbeddingChunk, Note, float]]) -> list[dict]:
    """Maps [n] markers actually used in `full_text` back to the retrieved
    (chunk, note, similarity) rows they refer to, producing citation dicts
    ready to persist as Citation rows and/or return to the client."""
    cited = extract_cited_ordinals(full_text)
    citations = []
    for i, (chunk, note, similarity) in enumerate(rows, start=1):
        if i not in cited:
            continue
        citations.append(
            {
                "ordinal": i,
                "note_id": str(note.id),
                "note_title": note.title,
                "chunk_id": str(chunk.id),
                "start_time": chunk.start_time,
                "end_time": chunk.end_time,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "confidence": confidence_bucket(similarity),
                "quote": chunk.content[:280],
            }
        )
    return citations


async def generate_llm_text(provider: LLMProvider, messages: list[Message], *, system: str) -> str:
    """Consumes a provider's streaming chat() fully and returns the joined
    text -- for callers that want a single one-shot answer rather than a
    live stream (e.g. a click-to-summarize panel)."""
    parts = [chunk async for chunk in provider.chat(messages, system=system)]
    return "".join(parts)
