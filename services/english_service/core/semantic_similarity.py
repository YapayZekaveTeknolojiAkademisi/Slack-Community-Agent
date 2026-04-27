import math
import re
from collections import Counter
from difflib import SequenceMatcher

from services.english_service.core.metrics import Metrics


_WORD_PATTERN = re.compile(r"[a-zA-Z']+")


def normalize_text(text: str) -> str:
    if not isinstance(text, str):
        return ""

    return " ".join(text.lower().strip().split())


def tokenize(text: str) -> list[str]:
    normalized = normalize_text(text)
    return _WORD_PATTERN.findall(normalized)


def cosine_similarity(text_a: str, text_b: str) -> float:
    tokens_a = tokenize(text_a)
    tokens_b = tokenize(text_b)

    if not tokens_a or not tokens_b:
        return 0.0

    vector_a = Counter(tokens_a)
    vector_b = Counter(tokens_b)

    common_tokens = set(vector_a) & set(vector_b)
    dot_product = sum(vector_a[token] * vector_b[token] for token in common_tokens)

    norm_a = math.sqrt(sum(value * value for value in vector_a.values()))
    norm_b = math.sqrt(sum(value * value for value in vector_b.values()))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot_product / (norm_a * norm_b)


def sequence_similarity(text_a: str, text_b: str) -> float:
    normalized_a = normalize_text(text_a)
    normalized_b = normalize_text(text_b)

    if not normalized_a or not normalized_b:
        return 0.0

    return SequenceMatcher(None, normalized_a, normalized_b).ratio()


def semantic_similarity(text_a: str, text_b: str) -> float:
    """
    Lightweight semantic-like similarity score.

    This intentionally avoids external embedding dependencies for now.
    It combines token cosine similarity with character-sequence similarity.
    Later, this function can be replaced by a real embedding model without
    changing quiz/topic generation code.
    """
    cosine_score = cosine_similarity(text_a, text_b)
    sequence_score = sequence_similarity(text_a, text_b)

    return (0.65 * cosine_score) + (0.35 * sequence_score)


def max_similarity(text: str, candidates: list[str] | None) -> float:
    if not isinstance(text, str) or not text.strip():
        return 0.0

    if not candidates:
        return 0.0

    scores = [
        semantic_similarity(text, candidate)
        for candidate in candidates
        if isinstance(candidate, str) and candidate.strip()
    ]

    return max(scores, default=0.0)


def is_semantically_repeated(
    text: str,
    candidates: list[str] | None,
    threshold: float,
) -> bool:
    repeated = max_similarity(text, candidates) >= threshold
    if repeated:
        Metrics.inc("semantic_rejections")
    return repeated


def filter_semantically_distinct_items(
    items: list[dict],
    key: str,
    recent_values: list[str] | None,
    threshold: float,
) -> list[dict]:
    if not recent_values:
        return items

    distinct_items = []

    for item in items:
        value = item.get(key, "")
        if not isinstance(value, str) or not value.strip():
            continue

        if not is_semantically_repeated(value, recent_values, threshold):
            distinct_items.append(item)

    return distinct_items
