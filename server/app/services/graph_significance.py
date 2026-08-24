import math
import uuid
from collections import defaultdict
from typing import TypeVar

K = TypeVar("K")

SIMILARITY_FLOOR = 0.75  # only create a similarity-based edge above this cosine similarity


def normalize(values: dict[K, float]) -> dict[K, float]:
    """Min-max normalize to 0-1 so the frontend's significance slider has a
    consistent range regardless of project size."""
    if not values:
        return {}
    lo, hi = min(values.values()), max(values.values())
    if hi == lo:
        return dict.fromkeys(values, 1.0)
    return {k: (v - lo) / (hi - lo) for k, v in values.items()}


def build_cooccurrence(note_to_keywords: dict[uuid.UUID, set[uuid.UUID]]) -> dict[tuple[uuid.UUID, uuid.UUID], int]:
    cooccurrence: dict[tuple[uuid.UUID, uuid.UUID], int] = defaultdict(int)
    for kw_ids in note_to_keywords.values():
        kw_list = sorted(kw_ids)
        for i in range(len(kw_list)):
            for j in range(i + 1, len(kw_list)):
                cooccurrence[(kw_list[i], kw_list[j])] += 1
    return cooccurrence


def merge_edges(
    cooccurrence: dict[tuple[uuid.UUID, uuid.UUID], int],
    similarities: list[tuple[uuid.UUID, uuid.UUID, float]],
) -> dict[tuple[uuid.UUID, uuid.UUID], dict]:
    edges: dict[tuple[uuid.UUID, uuid.UUID], dict] = {
        key: {"cooccurrence_count": count, "embedding_similarity": None} for key, count in cooccurrence.items()
    }
    for a, b, sim in similarities:
        key = (a, b) if a < b else (b, a)
        if key in edges:
            edges[key]["embedding_similarity"] = sim
        else:
            edges[key] = {"cooccurrence_count": 0, "embedding_similarity": sim}
    return edges


def score_edges(edges: dict[tuple[uuid.UUID, uuid.UUID], dict]) -> dict[tuple[uuid.UUID, uuid.UUID], float]:
    raw = {
        key: 0.5 * math.log1p(d["cooccurrence_count"]) + 0.5 * (d["embedding_similarity"] or 0.0)
        for key, d in edges.items()
    }
    return normalize(raw)


def score_nodes(
    keyword_ids: list[uuid.UUID],
    note_frequency: dict[uuid.UUID, int],
    edges: dict[tuple[uuid.UUID, uuid.UUID], dict],
) -> dict[uuid.UUID, float]:
    degree: dict[uuid.UUID, int] = defaultdict(int)
    for a, b in edges:
        degree[a] += 1
        degree[b] += 1

    raw = {
        kw_id: 0.6 * math.log1p(note_frequency.get(kw_id, 0)) + 0.4 * degree.get(kw_id, 0) for kw_id in keyword_ids
    }
    return normalize(raw)
