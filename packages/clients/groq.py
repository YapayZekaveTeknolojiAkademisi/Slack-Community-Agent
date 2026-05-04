"""
GroqClient — Akademi Topluluk Asistanı

AMAÇ
----
Groq Cloud API'si üzerinden LLM tamamlama (completion) çağrıları yapan,
bot genelinde tek örnek çalışan (Singleton) istemcisi.

KULLANIM
--------
    from packages.clients.groq import GroqClient

    client = GroqClient()
    result = await client.quick_ask("Sen bir asistansın.", "Merhaba!")

HATA YÖNETİMİ
--------------
• API anahtarı eksikse GroqClientError fırlatır.
• API çağrısı başarısız olursa GroqClientError fırlatır.
"""

import asyncio
import logging
from typing import Optional

from groq import AsyncGroq

from packages.settings import get_settings


class GroqClientError(Exception):
    """Groq istemcisi hata sınıfı."""
    pass


class _SingletonMeta(type):
    _instances: dict = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


class GroqClient(metaclass=_SingletonMeta):
    """
    Groq Cloud API tabanlı Singleton LLM istemcisi.

    `quick_ask()` yöntemi; bir system prompt ve user prompt alıp
    modelden tek bir string cevap döndürür.

    Varsayılan model: llama-3.3-70b-versatile
    """

    DEFAULT_MODEL = "llama-3.3-70b-versatile"
    DEFAULT_MAX_TOKENS = 1024
    DEFAULT_TEMPERATURE = 0.3

    def __init__(self) -> None:
        self._logger = logging.getLogger("groq_client")
        settings = get_settings()
        api_key = settings.groq_api_key
        if not api_key:
            raise GroqClientError(
                "GROQ_API_KEY ortam değişkeni tanımlı değil. "
                ".env dosyasına ekleyin."
            )
        self._client = AsyncGroq(api_key=api_key)
        self._logger.info("[GroqClient] Hazır. Model: %s", self.DEFAULT_MODEL)

    async def quick_ask(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        model: Optional[str] = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> str:
        """
        Tek turlu chat completion çağrısı.

        Args:
            system_prompt: Modelin rolünü ve davranışını tanımlayan sistem mesajı.
            user_prompt:   Kullanıcının sorusu veya talebi.
            model:         Groq model adı (None ise DEFAULT_MODEL kullanılır).
            max_tokens:    Maksimum çıktı token sayısı.
            temperature:   Yaratıcılık parametresi (0.0–1.0).

        Returns:
            Modelin ürettiği metin cevabı (str).

        Raises:
            GroqClientError: API çağrısı başarısız olursa.
        """
        _model = model or self.DEFAULT_MODEL
        try:
            response = await self._client.chat.completions.create(
                model=_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            content = response.choices[0].message.content
            self._logger.debug(
                "[GroqClient] quick_ask tamamlandı. "
                "Tokens: %s prompt + %s completion",
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
            )
            return content.strip() if content else ""
        except Exception as exc:
            self._logger.error("[GroqClient] API hatası: %s", exc, exc_info=True)
            raise GroqClientError(f"Groq API çağrısı başarısız: {exc}") from exc
