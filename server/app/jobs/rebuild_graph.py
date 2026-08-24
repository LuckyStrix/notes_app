import asyncio
import uuid
from collections import defaultdict

from sqlalchemy import delete, func, select
from sqlalchemy.orm import aliased

from app.db import async_session
from app.models.keyword import Keyword, KeywordEdge, NoteKeyword
from app.services.graph_significance import SIMILARITY_FLOOR, build_cooccurrence, merge_edges, score_edges, score_nodes


def rebuild_project_graph(project_id: str) -> None:
    asyncio.run(_rebuild_project_graph(project_id))


async def _rebuild_project_graph(project_id: str) -> None:
    pid = uuid.UUID(project_id)

    async with async_session() as db:
        keywords_result = await db.execute(select(Keyword).where(Keyword.project_id == pid))
        keywords = keywords_result.scalars().all()
        if not keywords:
            return
        keyword_ids = [k.id for k in keywords]

        nk_result = await db.execute(select(NoteKeyword.note_id, NoteKeyword.keyword_id).where(NoteKeyword.keyword_id.in_(keyword_ids)))
        note_to_keywords: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
        note_frequency: dict[uuid.UUID, int] = defaultdict(int)
        for note_id, keyword_id in nk_result.all():
            note_to_keywords[note_id].add(keyword_id)
            note_frequency[keyword_id] += 1

        cooccurrence = build_cooccurrence(note_to_keywords)

        KA, KB = aliased(Keyword), aliased(Keyword)
        similarity_expr = 1 - KA.embedding.cosine_distance(KB.embedding)
        sim_stmt = (
            select(KA.id, KB.id, similarity_expr)
            .where(KA.project_id == pid, KB.project_id == pid, KA.id < KB.id)
            .where(similarity_expr >= SIMILARITY_FLOOR)
        )
        sim_result = await db.execute(sim_stmt)
        similarities = list(sim_result.all())

        edges = merge_edges(cooccurrence, similarities)
        edge_significance = score_edges(edges)
        node_significance = score_nodes(keyword_ids, note_frequency, edges)

        await db.execute(delete(KeywordEdge).where(KeywordEdge.project_id == pid))
        await db.flush()

        for (a, b), data in edges.items():
            db.add(
                KeywordEdge(
                    project_id=pid,
                    source_keyword_id=a,
                    target_keyword_id=b,
                    cooccurrence_count=data["cooccurrence_count"],
                    embedding_similarity=data["embedding_similarity"],
                    significance=edge_significance[(a, b)],
                )
            )

        for kw in keywords:
            kw.significance = node_significance.get(kw.id, 0.0)

        await db.commit()


def rebuild_project_graph_incremental(
    project_id: str, note_id: str, old_keyword_ids: list[str], new_keyword_ids: list[str]
) -> None:
    asyncio.run(_rebuild_project_graph_incremental(project_id, note_id, old_keyword_ids, new_keyword_ids))


async def _rebuild_project_graph_incremental(
    project_id: str, note_id: str, old_keyword_ids: list[str], new_keyword_ids: list[str]
) -> None:
    """Scopes the expensive parts of a rebuild (co-occurrence, embedding
    similarity) to the keywords touched by one note's re-extraction, instead
    of recomputing them project-wide. Only the final significance
    renormalization is still project-wide -- but that's a cheap aggregate
    scan + bulk update over already-stored counts, not a re-derivation of
    similarity/co-occurrence. See rebuild_project_graph above for the
    non-incremental "fix drift" fallback this doesn't replace.
    """
    pid = uuid.UUID(project_id)
    affected = {uuid.UUID(k) for k in old_keyword_ids} | {uuid.UUID(k) for k in new_keyword_ids}
    if not affected:
        return

    async with async_session() as db:
        # (a) co-occurrence scoped to notes sharing an affected keyword, not the whole project.
        note_ids_subq = select(NoteKeyword.note_id).where(NoteKeyword.keyword_id.in_(affected)).distinct()
        nk_result = await db.execute(
            select(NoteKeyword.note_id, NoteKeyword.keyword_id).where(NoteKeyword.note_id.in_(note_ids_subq))
        )
        note_to_keywords: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
        for nid, kid in nk_result.all():
            note_to_keywords[nid].add(kid)
        cooccurrence = build_cooccurrence(note_to_keywords)

        # (b) embedding similarity: affected x ALL project keywords -- O(k*K), not O(K^2).
        KA, KB = aliased(Keyword), aliased(Keyword)
        similarity_expr = 1 - KA.embedding.cosine_distance(KB.embedding)
        sim_result = await db.execute(
            select(KA.id, KB.id, similarity_expr)
            .where(KA.project_id == pid, KB.project_id == pid, KA.id.in_(affected), KA.id != KB.id)
            .where(similarity_expr >= SIMILARITY_FLOOR)
        )
        similarities = {(min(a, b), max(a, b)): sim for a, b, sim in sim_result.all()}
        edges = merge_edges(cooccurrence, [(a, b, s) for (a, b), s in similarities.items()])

        # (c) upsert/delete only KeywordEdge rows touching `affected` -- not a full wipe.
        existing_result = await db.execute(
            select(KeywordEdge).where(
                KeywordEdge.project_id == pid,
                (KeywordEdge.source_keyword_id.in_(affected)) | (KeywordEdge.target_keyword_id.in_(affected)),
            )
        )
        existing_by_key = {(e.source_keyword_id, e.target_keyword_id): e for e in existing_result.scalars().all()}
        for key in set(existing_by_key) - set(edges.keys()):
            await db.delete(existing_by_key[key])
        for (a, b), data in edges.items():
            if (a, b) in existing_by_key:
                row = existing_by_key[(a, b)]
                row.cooccurrence_count = data["cooccurrence_count"]
                row.embedding_similarity = data["embedding_similarity"]
            else:
                db.add(
                    KeywordEdge(
                        project_id=pid,
                        source_keyword_id=a,
                        target_keyword_id=b,
                        cooccurrence_count=data["cooccurrence_count"],
                        embedding_similarity=data["embedding_similarity"],
                        significance=0,
                    )
                )
        await db.flush()

        # (d)+(e) cheap project-wide renormalization from CURRENT stored counts --
        # an aggregate scan + bulk update, not a re-derivation of similarity/co-occurrence.
        all_edges_result = await db.execute(select(KeywordEdge).where(KeywordEdge.project_id == pid))
        all_edges = all_edges_result.scalars().all()
        edge_data = {
            (e.source_keyword_id, e.target_keyword_id): {
                "cooccurrence_count": e.cooccurrence_count,
                "embedding_similarity": e.embedding_similarity,
            }
            for e in all_edges
        }
        edge_significance = score_edges(edge_data)
        for e in all_edges:
            e.significance = edge_significance[(e.source_keyword_id, e.target_keyword_id)]

        all_keywords_result = await db.execute(select(Keyword).where(Keyword.project_id == pid))
        all_keywords = all_keywords_result.scalars().all()
        freq_result = await db.execute(
            select(NoteKeyword.keyword_id, func.count(NoteKeyword.note_id))
            .where(NoteKeyword.keyword_id.in_([k.id for k in all_keywords]))
            .group_by(NoteKeyword.keyword_id)
        )
        note_frequency = dict(freq_result.all())
        node_significance = score_nodes([k.id for k in all_keywords], note_frequency, edge_data)
        for kw in all_keywords:
            kw.significance = node_significance.get(kw.id, 0.0)

        await db.commit()
