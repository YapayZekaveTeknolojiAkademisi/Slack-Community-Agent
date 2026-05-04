from services.english_service.core.semantic_similarity import (
    semantic_similarity,
    is_semantically_repeated,
)

def test_high_similarity_detected():
    a = "Describe your daily routine"
    b = "Write about your everyday routine"

    assert semantic_similarity(a,b) > 0.50


def test_low_similarity_detected():
    a = "Describe your daily routine"
    b = "Explain digital privacy"

    assert semantic_similarity(a,b) < 0.50


def test_semantic_repeat_rejected():
    history = [
        "Describe your daily routine",
        "Write about your favorite meal"
    ]

    assert is_semantically_repeated(
        "Write about your everyday routine",
        history,
        0.60
    ) is True