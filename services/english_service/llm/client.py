from abc import ABC, abstractmethod

from packages.settings import get_settings


class BaseLLMClient(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> str:
        pass


class FakeLLMClient(BaseLLMClient):
    def generate(self, prompt: str) -> str:
        return str([
            {
                "question": "She ___ to school every day.",
                "options": ["go", "goes", "going"],
                "answer": "goes",
                "explanation": "Use 'goes' for third person singular in present simple."
            },
            {
                "question": "They ___ football now.",
                "options": ["play", "are playing", "played"],
                "answer": "are playing",
                "explanation": "Use present continuous for actions happening now."
            }
        ])


class GroqLLMClient(BaseLLMClient):
    def __init__(
        self,
        model: str | None = None,
        temperature: float = 0.7,
        system_message: str = "You are a helpful English teacher."
    ):
        from groq import Groq

        settings = get_settings()
        api_key = settings.groq_api_key
        if not api_key:
            raise ValueError(
                "groq_api_key tanimli degil (.env icinde GROQ_API_KEY / ayarlar)."
            )

        self.client = Groq(api_key=api_key)
        self.model = model or settings.groq_model or "llama-3.3-70b-versatile"
        self.temperature = temperature
        self.system_message = system_message

    def generate(self, prompt: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": self.system_message
                },
                {
                    "role": "user",
                    "content": prompt
                },
            ],
            temperature=self.temperature,
        )

        return response.choices[0].message.content.strip()