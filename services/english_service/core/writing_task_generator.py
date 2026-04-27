import random

from services.english_service.llm.client import BaseLLMClient, GroqLLMClient
from services.english_service.core.level_config import (
    MAX_REGENERATION_ATTEMPTS,
    SIMILARITY_THRESHOLD,
    get_random_topic_task,
    get_random_translation_task,
    get_topic_tasks,
    get_translation_tasks,
)
from services.english_service.core.metrics import Metrics
from services.english_service.core.semantic_similarity import (
    filter_semantically_distinct_items,
)


class WritingTaskGenerator:
    def __init__(self, llm_client: BaseLLMClient | None = None):
        self.llm = llm_client or GroqLLMClient(
            temperature=0.7,
            system_message="You generate creative but level-appropriate English writing tasks.",
        )

    def generate_topic_task(
        self,
        level: str,
        last_topic: str | None = None,
        recent_topics: list[str] | None = None,
    ) -> dict:
        """
        Select topic tasks from a Python-controlled pool.

        Lightweight semantic similarity filtering prevents topics that are not
        exactly the same, but still too similar in meaning.
        """
        topic_history = self._merge_history(last_topic, recent_topics)

        task = self._select_semantically_distinct_task(
            history=topic_history,
            item_key="topic",
            candidates=get_topic_tasks(level),
        )

        if task:
            return task

        return get_random_topic_task(level, topic_history)

    def generate_translation_task(
        self,
        level: str,
        last_source_text: str | None = None,
        recent_source_texts: list[str] | None = None,
    ) -> dict:
        """
        Select translation tasks from a Python-controlled pool.

        Lightweight semantic similarity filtering is also applied to source texts.
        """
        source_history = self._merge_history(last_source_text, recent_source_texts)

        task = self._select_semantically_distinct_task(
            history=source_history,
            item_key="source_text",
            candidates=get_translation_tasks(level),
        )

        if task:
            return task

        return get_random_translation_task(level, source_history)

    def _select_semantically_distinct_task(
        self,
        history: list[str],
        item_key: str,
        candidates: list[dict],
    ) -> dict | None:
        if not candidates:
            return None

        distinct_candidates = filter_semantically_distinct_items(
            items=candidates,
            key=item_key,
            recent_values=history,
            threshold=SIMILARITY_THRESHOLD,
        )

        if distinct_candidates:
            return random.choice(distinct_candidates).copy()

        for _ in range(MAX_REGENERATION_ATTEMPTS):
            Metrics.inc("regeneration_attempts")

            candidate = random.choice(candidates).copy()
            candidate_value = candidate.get(item_key, "")

            if candidate_value and candidate_value not in history:
                return candidate

        return None

    def _merge_history(
        self,
        last_value: str | None,
        recent_values: list[str] | None,
    ) -> list[str]:
        history: list[str] = []

        if isinstance(recent_values, list):
            history.extend(value for value in recent_values if isinstance(value, str))

        if isinstance(last_value, str) and last_value.strip():
            history.append(last_value)

        return history

    def _fallback_topic_task(self, level: str, last_topic: str | None = None) -> dict:
        return self.generate_topic_task(level, last_topic=last_topic)

    def _fallback_translation_task(
        self,
        level: str,
        last_source_text: str | None = None,
    ) -> dict:
        return self.generate_translation_task(level, last_source_text=last_source_text)
