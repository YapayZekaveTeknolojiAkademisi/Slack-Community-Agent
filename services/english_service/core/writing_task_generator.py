import json

from services.english_service.llm.client import BaseLLMClient, GroqLLMClient
from services.english_service.core.prompt_builder import (
    build_topic_task_prompt,
    build_translation_task_prompt,
)


class WritingTaskGenerator:
    def __init__(self, llm_client: BaseLLMClient | None = None):
        self.llm = llm_client or GroqLLMClient(
            temperature=0.9,
            system_message="You generate creative but level-appropriate English writing tasks."
        )

    def generate_topic_task(self, level: str, last_topic: str | None = None) -> dict:
        prompt = build_topic_task_prompt(level, last_topic=last_topic)
        raw_response = self.llm.generate(prompt)

        try:
            data = json.loads(raw_response)
        except json.JSONDecodeError:
            return self._fallback_topic_task(level, last_topic)

        if not isinstance(data, dict):
            return self._fallback_topic_task(level, last_topic)

        topic = data.get("topic")
        min_words = data.get("min_words")

        if not isinstance(topic, str) or not topic.strip():
            return self._fallback_topic_task(level, last_topic)

        if not isinstance(min_words, int):
            return self._fallback_topic_task(level, last_topic)

        cleaned_topic = topic.strip()
        if last_topic and cleaned_topic.lower() == last_topic.lower():
            return self._fallback_topic_task(level, last_topic)

        return {
            "topic": cleaned_topic,
            "min_words": min_words,
        }

    def generate_translation_task(self, level: str, last_source_text: str | None = None) -> dict:
        prompt = build_translation_task_prompt(level, last_source_text=last_source_text)
        raw_response = self.llm.generate(prompt)

        try:
            data = json.loads(raw_response)
        except json.JSONDecodeError:
            return self._fallback_translation_task(level, last_source_text)

        if not isinstance(data, dict):
            return self._fallback_translation_task(level, last_source_text)

        source_text = data.get("source_text")
        min_words = data.get("min_words")

        if not isinstance(source_text, str) or not source_text.strip():
            return self._fallback_translation_task(level, last_source_text)

        if not isinstance(min_words, int):
            return self._fallback_translation_task(level, last_source_text)

        cleaned_source_text = source_text.strip()
        if last_source_text and cleaned_source_text.lower() == last_source_text.lower():
            return self._fallback_translation_task(level, last_source_text)

        return {
            "source_text": cleaned_source_text,
            "min_words": min_words,
        }

    def _fallback_topic_task(self, level: str, last_topic: str | None = None) -> dict:
        fallback = {
            "beginner": [
                {"topic": "Describe your daily routine", "min_words": 30},
                {"topic": "Describe your favorite meal", "min_words": 30},
                {"topic": "Write about your favorite season", "min_words": 30},
                {"topic": "Describe a person you like", "min_words": 30},
            ],
            "intermediate": [
                {"topic": "Talk about your favorite holiday", "min_words": 60},
                {"topic": "Describe a memorable trip", "min_words": 60},
                {"topic": "Write about a challenge you overcame", "min_words": 60},
                {"topic": "Describe an important day in your life", "min_words": 60},
            ],
            "advanced": [
                {"topic": "Discuss the impact of technology on society", "min_words": 100},
                {"topic": "Explain how social media affects communication", "min_words": 100},
                {"topic": "Discuss advantages and disadvantages of remote work", "min_words": 100},
                {"topic": "Write about the role of education in personal development", "min_words": 100},
            ],
        }

        tasks = fallback.get(level, fallback["beginner"])

        if last_topic:
            filtered_tasks = [
                task for task in tasks
                if task["topic"].strip().lower() != last_topic.strip().lower()
            ]
            if filtered_tasks:
                return filtered_tasks[0]

        return tasks[0]

    def _fallback_translation_task(self, level: str, last_source_text: str | None = None) -> dict:
        fallback = {
            "beginner": [
                {
                    "source_text": "Ben her sabah erken kalkarım. Kahvaltı yaptıktan sonra işe giderim.",
                    "min_words": 20,
                },
                {
                    "source_text": "Bugün hava çok güzel. Parkta yürüyüş yapmak istiyorum.",
                    "min_words": 20,
                },
                {
                    "source_text": "En sevdiğim yemek makarnadır. Onu haftada iki kez yerim.",
                    "min_words": 20,
                },
            ],
            "intermediate": [
                {
                    "source_text": "Geçen yaz ailemle birlikte tatile gittik ve yeni yerler keşfettik.",
                    "min_words": 40,
                },
                {
                    "source_text": "Düzenli spor yapmak hem fiziksel hem de zihinsel sağlık için önemlidir.",
                    "min_words": 40,
                },
                {
                    "source_text": "Boş zamanlarımda kitap okumayı ve müzik dinlemeyi çok seviyorum.",
                    "min_words": 40,
                },
            ],
            "advanced": [
                {
                    "source_text": "Teknolojinin hızlı gelişimi hayatı kolaylaştırırken yüz yüze iletişimi azaltabiliyor.",
                    "min_words": 70,
                },
                {
                    "source_text": "Çevre sorunlarının çözümü için bireylerin ve kurumların birlikte hareket etmesi gerekir.",
                    "min_words": 70,
                },
                {
                    "source_text": "Başarılı bir kariyer için teknik bilgi kadar iletişim becerileri de önemlidir.",
                    "min_words": 70,
                },
            ],
        }

        tasks = fallback.get(level, fallback["beginner"])

        if last_source_text:
            filtered_tasks = [
                task for task in tasks
                if task["source_text"].strip().lower() != last_source_text.strip().lower()
            ]
            if filtered_tasks:
                return filtered_tasks[0]

        return tasks[0]