"""
Schema validation tests (§6: "Automated tests cover schema validation").

These test the trust boundary directly — ImageMetadata is what stands
between a raw model response and anything the rest of the system is
allowed to believe. If these pass, we know bad input is actually
rejected, not just assumed to be.
"""
import pytest
from pydantic import ValidationError

from app.schemas.image_metadata import ImageMetadata


def test_valid_metadata_is_accepted():
    data = {
        "subject": "red fox",
        "category": "animal",
        "attributes": ["wildlife", "outdoors"],
        "caption": "A red fox standing in a forest.",
        "confidence": 0.92,
    }
    metadata = ImageMetadata.model_validate(data)
    assert metadata.subject == "red fox"
    assert metadata.confidence == 0.92


def test_missing_required_field_is_rejected():
    data = {
        "subject": "red fox",
        "category": "animal",
        "attributes": [],
        # caption missing
        "confidence": 0.9,
    }
    with pytest.raises(ValidationError):
        ImageMetadata.model_validate(data)


def test_invalid_category_enum_is_rejected():
    data = {
        "subject": "red fox",
        "category": "not_a_real_category",
        "attributes": [],
        "caption": "A red fox in a forest.",
        "confidence": 0.9,
    }
    with pytest.raises(ValidationError):
        ImageMetadata.model_validate(data)


def test_confidence_out_of_range_is_rejected():
    data = {
        "subject": "red fox",
        "category": "animal",
        "attributes": [],
        "caption": "A red fox in a forest.",
        "confidence": 1.5,  # out of [0, 1] range
    }
    with pytest.raises(ValidationError):
        ImageMetadata.model_validate(data)


def test_confidence_negative_is_rejected():
    data = {
        "subject": "red fox",
        "category": "animal",
        "attributes": [],
        "caption": "A red fox in a forest.",
        "confidence": -0.1,
    }
    with pytest.raises(ValidationError):
        ImageMetadata.model_validate(data)


def test_caption_too_short_is_rejected():
    data = {
        "subject": "red fox",
        "category": "animal",
        "attributes": [],
        "caption": "Hi",  # below min_length=5
        "confidence": 0.9,
    }
    with pytest.raises(ValidationError):
        ImageMetadata.model_validate(data)


def test_attributes_are_cleaned_of_empty_strings():
    data = {
        "subject": "red fox",
        "category": "animal",
        "attributes": ["wildlife", "", "  ", "outdoors"],
        "caption": "A red fox in a forest.",
        "confidence": 0.9,
    }
    metadata = ImageMetadata.model_validate(data)
    assert metadata.attributes == ["wildlife", "outdoors"]


def test_subject_and_caption_are_stripped():
    data = {
        "subject": "  red fox  ",
        "category": "animal",
        "attributes": [],
        "caption": "  A red fox in a forest.  ",
        "confidence": 0.9,
    }
    metadata = ImageMetadata.model_validate(data)
    assert metadata.subject == "red fox"
    assert metadata.caption == "A red fox in a forest."