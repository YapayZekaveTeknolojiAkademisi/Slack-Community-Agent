"""
Summarizer — LLM ile kanal mesajlarından Türkçe özet üretir.

Özellikler:
- Kısa (brief) ve Detaylı (detailed) mod
- Kişiselleştirilmiş özet ("Seni ilgilendiren konular")
- Map-Reduce yaklaşımı (chunk'lar → ara özetler → final özet)
"""
from __future__ import annotations

from groq import Groq

from packages.settings import get_settings
from ..logger import _logger

settings = get_settings()

_groq: Groq | None = None


def _get_groq_client() -> Groq:
    global _groq
    if _groq is None:
        if not settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY tanımlı değil.")
        _groq = Groq(api_key=settings.groq_api_key)
    return _groq


# ── Prompt şablonları ────────────────────────────────────────────

_BRIEF_SYSTEM = """\
Sen bir Slack kanal asistanısın. Mesajları çok kısa ve öz Türkçe özetle.

Kurallar:
- Her konu için en fazla 1-2 cümle
- Sadece en önemli kararları ve tartışmaları yaz
- Maksimum 5-6 madde olsun
- Markdown bullet list kullan
"""

_DETAILED_SYSTEM = """\
Sen bir Slack kanal asistanısın. Mesajları kapsamlı şekilde Türkçe özetle.

Kurallar:
- Önemli konuları, kararları ve tartışmaları detaylı vurgula
- Kimin ne söylediğini belirt (kullanıcı adlarını kullan)
- Thread'lerdeki önemli tartışmaları ayrı belirt
- Reaksiyon alan (popüler) mesajları vurgula
- Gereksiz selamlaşma ve emoji spam'i atla
- Konuları başlıklar altında grupla
- Markdown formatı kullan
"""

_CHUNK_USER = """\
Aşağıdaki Slack mesajlarını özetle:

{messages}
"""

_REDUCE_SYSTEM = """\
Sen bir Slack kanal asistanısın. Birden fazla özet parçasını tek tutarlı Türkçe özet haline getir.

Kurallar:
- Tekrar eden bilgileri birleştir
- Kronolojik sırayı koru
- Ana konuları başlıklar altında grupla
- Markdown formatı kullan
"""

_REDUCE_USER = """\
Aşağıdaki özet parçalarını birleştir:

{summaries}
"""

_PERSONAL_SYSTEM = """\
Sen bir Slack asistanısın. Aşağıdaki mesajlar bir kullanıcıyı doğrudan ilgilendiren mesajlardır
(mention edildiği, thread'lerine yanıt gelen mesajlar).

Bu mesajları kısa ve öz şekilde Türkçe özetle:
- Kimin ne sorduğunu veya ne istediğini belirt
- Acil veya önemli görünen mesajları vurgula
- Markdown formatı kullan
"""

_PERSONAL_USER = """\
Bu mesajlar seni doğrudan ilgilendiriyor:

{messages}
"""

# ── Model ayarları ───────────────────────────────────────────────

_MODEL = "llama-3.1-8b-instant"
_TEMPERATURE = 0.3


def _call_llm(system_prompt: str, user_prompt: str, max_tokens: int = 1024) -> str:
    client = _get_groq_client()
    try:
        resp = client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=_TEMPERATURE,
        )
        return resp.choices[0].message.content.strip()
    except Exception as exc:
        _logger.error("Groq API call failed: %s", exc)
        raise


def summarize_chunks(chunks: list[str], mode: str = "detailed") -> str:
    """
    Map-Reduce ile özet üretir.

    Args:
        chunks: chunk_messages() çıktısı
        mode: "brief" (kısa) veya "detailed" (detaylı)

    Returns:
        Türkçe özet metni
    """
    if not chunks:
        return "Bu zaman diliminde kanala mesaj atılmamış."

    system = _BRIEF_SYSTEM if mode == "brief" else _DETAILED_SYSTEM
    max_tokens = 512 if mode == "brief" else 1024

    # MAP
    _logger.info("Summarizing %d chunk(s) in '%s' mode...", len(chunks), mode)
    chunk_summaries: list[str] = []

    for i, chunk in enumerate(chunks, 1):
        _logger.info("  → Chunk %d/%d (%d chars)", i, len(chunks), len(chunk))
        summary = _call_llm(
            system,
            _CHUNK_USER.format(messages=chunk),
            max_tokens=max_tokens,
        )
        chunk_summaries.append(summary)

    if len(chunk_summaries) == 1:
        return chunk_summaries[0]

    # REDUCE
    _logger.info("Reducing %d chunk summaries...", len(chunk_summaries))
    numbered = "\n\n".join(
        f"--- Parça {i} ---\n{s}"
        for i, s in enumerate(chunk_summaries, 1)
    )
    return _call_llm(
        _REDUCE_SYSTEM,
        _REDUCE_USER.format(summaries=numbered),
        max_tokens=max_tokens,
    )


def summarize_personal(personal_chunks: list[str]) -> str:
    """
    Kullanıcıyı ilgilendiren mesajlardan kişisel özet üretir.

    Args:
        personal_chunks: Kişisel mesajların chunk'lanmış halleri

    Returns:
        "Seni ilgilendiren konular" özet metni
    """
    if not personal_chunks:
        return ""

    _logger.info("Summarizing %d personal chunk(s)...", len(personal_chunks))

    if len(personal_chunks) == 1:
        return _call_llm(
            _PERSONAL_SYSTEM,
            _PERSONAL_USER.format(messages=personal_chunks[0]),
            max_tokens=512,
        )

    # Birden fazla chunk varsa her birini özetle, sonra birleştir
    summaries = []
    for chunk in personal_chunks:
        s = _call_llm(
            _PERSONAL_SYSTEM,
            _PERSONAL_USER.format(messages=chunk),
            max_tokens=512,
        )
        summaries.append(s)

    combined = "\n\n".join(summaries)
    return _call_llm(
        _PERSONAL_SYSTEM,
        f"Aşağıdaki özetleri birleştir:\n\n{combined}",
        max_tokens=512,
    )