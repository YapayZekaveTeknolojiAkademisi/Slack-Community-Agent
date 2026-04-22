"""
Chunker — Mesaj listesini LLM token limitine göre parçalara ayırır.

Groq modelleri genellikle 8K-32K token destekler.
Türkçe için yaklaşık 3 karakter = 1 token oranı kullanılır.
Her chunk bağımsız olarak LLM'e gönderilip özetlenir,
sonra chunk özetleri birleştirilerek final özet üretilir (map-reduce).
"""
from __future__ import annotations

from .message_fetcher import ChannelMessage

# Türkçe metinler için yaklaşık karakter/token oranı
_CHARS_PER_TOKEN = 3

# System prompt + yanıt için ayrılan token payı
_RESERVED_TOKENS = 1500

# Varsayılan model context window (Groq llama modelleri)
DEFAULT_MAX_TOKENS = 8000


def _estimate_tokens(text: str) -> int:
    """Karakter sayısından yaklaşık token sayısı hesaplar."""
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _format_message(msg: ChannelMessage) -> str:
    """Tek bir mesajı LLM'e gönderilecek metin formatına çevirir."""
    line = f"[{msg.user_name}]: {msg.text}"
    if msg.thread_reply_count > 0:
        line += f" (💬 {msg.thread_reply_count} yanıt)"
    if msg.reactions:
        line += f" [:{':, :'.join(msg.reactions)}:]"
    return line


def chunk_messages(
    messages: list[ChannelMessage],
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> list[str]:
    """
    Mesajları token limitine göre chunk'lara ayırır.

    Args:
        messages: ChannelMessage listesi
        max_tokens: Model context window boyutu

    Returns:
        Her biri LLM'e gönderilebilecek boyutta metin chunk'ları
    """
    if not messages:
        return []

    budget = max_tokens - _RESERVED_TOKENS
    if budget <= 0:
        budget = max_tokens // 2

    chunks: list[str] = []
    current_lines: list[str] = []
    current_tokens = 0

    for msg in messages:
        line = _format_message(msg)
        line_tokens = _estimate_tokens(line)

        # Tek mesaj budget'ı aşıyorsa, mesajı kırp
        if line_tokens > budget:
            max_chars = budget * _CHARS_PER_TOKEN
            line = line[:max_chars] + "..."
            line_tokens = budget

        # Mevcut chunk'a sığmıyorsa yeni chunk başlat
        if current_tokens + line_tokens > budget and current_lines:
            chunks.append("\n".join(current_lines))
            current_lines = []
            current_tokens = 0

        current_lines.append(line)
        current_tokens += line_tokens

    # Son kalan mesajları da ekle
    if current_lines:
        chunks.append("\n".join(current_lines))

    return chunks