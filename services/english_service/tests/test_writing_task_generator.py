from services.english_service.core.writing_task_generator import (
    WritingTaskGenerator
)
from services.english_service.llm.client import FakeLLMClient

def test_recent_topics_not_repeated():
    generator = WritingTaskGenerator(
    llm_client=FakeLLMClient()
)

    recent = [
        "Describe your daily routine",
        "Write about your favorite meal"
    ]

    task = generator.generate_topic_task(
        "beginner",
        recent_topics=recent
    )

    assert task["topic"] not in recent


def test_topic_generation_has_required_fields():
    generator = WritingTaskGenerator(
    llm_client=FakeLLMClient()
)

    task = generator.generate_topic_task("beginner")

    assert "topic" in task
    assert "min_words" in task