class Metrics:
    """
    Lightweight in-memory metrics for English service quality tracking.

    This is intentionally simple for Phase 5. It helps us observe:
    - how often fallback flows are used
    - how often LLM output parsing fails
    - how often semantic similarity filtering rejects items
    - how often regeneration attempts are needed

    Later this can be replaced with a real monitoring/logging backend.
    """

    counters = {
        "semantic_rejections": 0,
        "regeneration_attempts": 0,
        "quiz_fallback_used": 0,
        "quiz_validation_failures": 0,
        "writing_fallback_used": 0,
        "json_parse_failures": 0,
    }

    @classmethod
    def inc(cls, key: str, amount: int = 1):
        if key not in cls.counters:
            cls.counters[key] = 0
        cls.counters[key] += amount

    @classmethod
    def snapshot(cls) -> dict:
        return dict(cls.counters)

    @classmethod
    def reset(cls):
        for key in cls.counters:
            cls.counters[key] = 0
