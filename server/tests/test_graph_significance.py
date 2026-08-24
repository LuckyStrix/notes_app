import uuid

from app.services.graph_significance import (
    build_cooccurrence,
    merge_edges,
    normalize,
    score_edges,
    score_nodes,
)

A, B, C = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
AB = (A, B) if A < B else (B, A)
BC = (B, C) if B < C else (C, B)
AC = (A, C) if A < C else (C, A)


def test_normalize_empty():
    assert normalize({}) == {}


def test_normalize_scales_to_unit_range():
    result = normalize({"a": 0.0, "b": 5.0, "c": 10.0})
    assert result == {"a": 0.0, "b": 0.5, "c": 1.0}


def test_normalize_all_equal_values_map_to_one():
    assert normalize({"a": 3.0, "b": 3.0}) == {"a": 1.0, "b": 1.0}


def test_build_cooccurrence_counts_pairs_across_notes():
    note_to_keywords = {
        uuid.uuid4(): {A, B},
        uuid.uuid4(): {A, B, C},
    }
    cooc = build_cooccurrence(note_to_keywords)
    assert cooc[AB] == 2
    assert cooc[AC] == 1
    assert cooc[BC] == 1


def test_merge_edges_combines_cooccurrence_and_similarity():
    cooc = {AB: 3}
    sims = [(A, B, 0.9), (B, C, 0.5)]
    edges = merge_edges(cooc, sims)
    assert edges[AB] == {"cooccurrence_count": 3, "embedding_similarity": 0.9}
    assert edges[BC] == {"cooccurrence_count": 0, "embedding_similarity": 0.5}


def test_score_edges_normalizes_combined_score():
    edges = {
        AB: {"cooccurrence_count": 5, "embedding_similarity": 0.9},
        BC: {"cooccurrence_count": 0, "embedding_similarity": 0.1},
    }
    scores = score_edges(edges)
    assert scores[AB] == 1.0
    assert scores[BC] == 0.0


def test_score_nodes_rewards_frequency_and_degree():
    edges = {AB: {}, AC: {}}
    scores = score_nodes([A, B, C], {A: 10, B: 1, C: 1}, edges)
    assert scores[A] == 1.0  # highest frequency and highest degree (2)
    assert scores[B] == scores[C]  # same frequency, same degree (1)
