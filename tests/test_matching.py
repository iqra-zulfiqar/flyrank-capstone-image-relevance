"""
Matching accuracy tests (§6: "Automated tests cover ... matching
accuracy"). Pure math/logic — no network or DB needed.
"""
import math
import pytest

from app.services.embeddings import cosine_similarity
from app.services.matching import rank_candidates


class TestCosineSimilarity:
    def test_identical_vectors_give_similarity_one(self):
        v = [1.0, 2.0, 3.0]
        assert math.isclose(cosine_similarity(v, v), 1.0, rel_tol=1e-9)

    def test_orthogonal_vectors_give_similarity_zero(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert math.isclose(cosine_similarity(a, b), 0.0, abs_tol=1e-9)

    def test_opposite_vectors_give_similarity_negative_one(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert math.isclose(cosine_similarity(a, b), -1.0, rel_tol=1e-9)

    def test_zero_vector_returns_zero_not_a_crash(self):
        """Division by zero would otherwise crash on an all-zero
        embedding — must degrade gracefully instead."""
        a = [0.0, 0.0, 0.0]
        b = [1.0, 2.0, 3.0]
        assert cosine_similarity(a, b) == 0.0

    def test_mismatched_dimensions_raises(self):
        with pytest.raises(ValueError):
            cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0])

    def test_scale_invariance(self):
        """Cosine similarity should be identical regardless of vector
        magnitude — only direction matters."""
        a = [1.0, 2.0, 3.0]
        b_small = [2.0, 4.0, 6.0]
        b_large = [200.0, 400.0, 600.0]
        sim_small = cosine_similarity(a, b_small)
        sim_large = cosine_similarity(a, b_large)
        assert math.isclose(sim_small, sim_large, rel_tol=1e-9)


class TestRankCandidates:
    def _make_row(self, image_id, embedding, subject="test"):
        return {
            "image_id": image_id,
            "filename": f"{image_id}.jpg",
            "subject": subject,
            "attributes": [],
            "confidence": 0.9,
            "is_flagged": False,
            "embedding": embedding,
        }

    def test_most_similar_ranks_first(self):
        post_embedding = [1.0, 0.0, 0.0]
        rows = [
            self._make_row("far", [0.0, 1.0, 0.0]),      # orthogonal, sim=0
            self._make_row("close", [0.9, 0.1, 0.0]),    # nearly aligned, high sim
            self._make_row("medium", [0.5, 0.5, 0.0]),   # partial alignment
        ]
        ranked = rank_candidates(post_embedding, rows)

        assert ranked[0].image_id == "close"
        assert ranked[-1].image_id == "far"
        # strictly descending
        for i in range(len(ranked) - 1):
            assert ranked[i].similarity >= ranked[i + 1].similarity

    def test_empty_candidate_list_returns_empty(self):
        assert rank_candidates([1.0, 0.0], []) == []

    def test_preserves_all_metadata_fields(self):
        post_embedding = [1.0, 0.0]
        rows = [self._make_row("img1", [1.0, 0.0], subject="red fox")]
        ranked = rank_candidates(post_embedding, rows)
        assert ranked[0].subject == "red fox"
        assert ranked[0].confidence == 0.9
        assert ranked[0].is_flagged is False