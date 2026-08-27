"""
Mismatch guard tests (§6: "Automated tests cover ... mismatch rejection").

These prove the guard's core promise deterministically, without needing
a live database, Ollama, or the API running — evaluate_guard() is a
pure function, which is exactly why it's testable this cleanly.
"""
from app.services.guard import evaluate_guard, extract_known_subject


class TestExtractKnownSubject:
    def test_finds_fox(self):
        assert extract_known_subject("The behavior of red foxes") == "fox"

    def test_finds_wolf(self):
        assert extract_known_subject("Living with wolves in the wild") == "wolf"

    def test_case_insensitive(self):
        assert extract_known_subject("RED FOXES ARE GREAT") == "fox"

    def test_returns_none_when_no_known_subject(self):
        assert extract_known_subject("A guide to houseplants") is None


class TestEvaluateGuard:
    def test_the_fox_wolf_scenario_is_rejected(self):
        """
        The brief's own example (§4): a fox post, a wolf candidate image
        with decent-but-not-perfect confidence — must be rejected with a
        category mismatch reason, not silently passed through.
        """
        passed, reason = evaluate_guard(
            post_title="The behavior of red foxes",
            post_body="Vulpes vulpes is a cunning, adaptable animal.",
            image_subject="wolf",
            image_attributes=["wildlife", "forest", "predator"],
            image_confidence=0.85,
            image_is_flagged=False,
            similarity=0.65,  # deliberately high, to prove category check catches it
        )
        assert passed is False
        assert "category mismatch" in reason.lower()
        assert "fox" in reason.lower()
        assert "wolf" in reason.lower()

    def test_matching_subject_passes(self):
        passed, reason = evaluate_guard(
            post_title="The behavior of red foxes",
            post_body="Vulpes vulpes is a cunning, adaptable animal.",
            image_subject="red fox",
            image_attributes=["wildlife", "forest"],
            image_confidence=0.9,
            image_is_flagged=False,
            similarity=0.65,
        )
        assert passed is True
        assert reason is None

    def test_flagged_image_is_rejected_regardless_of_similarity(self):
        passed, reason = evaluate_guard(
            post_title="The behavior of red foxes",
            post_body="Foxes are wild canines.",
            image_subject="red fox",
            image_attributes=["wildlife"],
            image_confidence=0.9,
            image_is_flagged=True,  # flagged, even though confidence looks fine
            similarity=0.9,
        )
        assert passed is False
        assert "flagged" in reason.lower() or "low-confidence" in reason.lower()

    def test_low_confidence_image_is_rejected(self):
        passed, reason = evaluate_guard(
            post_title="The behavior of red foxes",
            post_body="Foxes are wild canines.",
            image_subject="red fox",
            image_attributes=["wildlife"],
            image_confidence=0.3,  # below LOW_CONFIDENCE_THRESHOLD
            image_is_flagged=False,
            similarity=0.9,
        )
        assert passed is False
        assert "confidence" in reason.lower()

    def test_low_similarity_is_rejected_when_categories_dont_conflict(self):
        """A post with no known subject at all can still fail on pure
        similarity — the "no confident match" path (houseplants case)."""
        passed, reason = evaluate_guard(
            post_title="A guide to houseplants",
            post_body="Watering schedules and light requirements.",
            image_subject="red fox",
            image_attributes=["wildlife"],
            image_confidence=0.9,
            image_is_flagged=False,
            similarity=0.2,  # genuinely unrelated content
        )
        assert passed is False
        assert "similarity" in reason.lower()

    def test_post_with_no_known_subject_skips_category_check(self):
        """If the post doesn't mention any of the five known categories,
        the guard can't reason about subject match — it should fall
        through to the similarity check rather than rejecting outright."""
        passed, reason = evaluate_guard(
            post_title="A guide to houseplants",
            post_body="Watering schedules and light requirements.",
            image_subject="red fox",
            image_attributes=["wildlife"],
            image_confidence=0.9,
            image_is_flagged=False,
            similarity=0.9,  # artificially high, to isolate the category-skip behavior
        )
        assert passed is True  # passes because similarity is high and no category conflict

    def test_same_category_different_wording_passes(self):
        """Guards against over-fitting to exact subject strings — 'wolf
        pack' should still match a post about 'wolves'."""
        passed, reason = evaluate_guard(
            post_title="Living with wolves in the wild",
            post_body="Gray wolves hunt in coordinated packs.",
            image_subject="wolf pack",
            image_attributes=["wildlife", "pack", "forest"],
            image_confidence=0.85,
            image_is_flagged=False,
            similarity=0.67,
        )
        assert passed is True