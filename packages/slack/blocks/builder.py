from typing import List, Dict, Any, Optional, Union

class BlockBuilder:
    """
    Slack Block Kit (UI) elemanlarını kolayca oluşturan yardımcı sınıf.
    Dökümantasyon: https://api.slack.com/block-kit
    """

    @staticmethod
    def header(text: str) -> Dict[str, Any]:
        """Başlık bloğu oluşturur (plain_text üst sınırı 150 karakter)."""
        return {
            "type": "header",
            "text": {"type": "plain_text", "text": text, "emoji": True}
        }

    @staticmethod
    def divider() -> Dict[str, Any]:
        """Ayırıcı çizgi ekler."""
        return {"type": "divider"}

    @staticmethod
    def section(
        text: Optional[str] = None, 
        fields: Optional[List[str]] = None, 
        accessory: Optional[Dict[str, Any]] = None,
        block_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Metin, yan yana alanlar (fields) veya buton/görsel (accessory) içeren bir bölüm oluşturur.
        """
        block = {"type": "section"}
        if text:
            block["text"] = {"type": "mrkdwn", "text": text}
        
        if fields:
            block["fields"] = [{"type": "mrkdwn", "text": f} for f in fields]
        
        if accessory:
            block["accessory"] = accessory
            
        if block_id:
            block["block_id"] = block_id
            
        return block

    @staticmethod
    def actions(elements: List[Dict[str, Any]], block_id: Optional[str] = None) -> Dict[str, Any]:
        """Butonlar gibi interaktif öğeleri bir araya toplar (max 5 öğe)."""
        block = {"type": "actions", "elements": elements}
        if block_id:
            block["block_id"] = block_id
        return block

    @staticmethod
    def context(elements: List[Union[str, Dict[str, Any]]], block_id: Optional[str] = None) -> Dict[str, Any]:
        """Küçük yazı tipiyle ek bilgi veya imza alanı oluşturur."""
        context_elements = []
        for e in elements:
            if isinstance(e, str):
                context_elements.append({"type": "mrkdwn", "text": e})
            else:
                context_elements.append(e)
                
        block = {"type": "context", "elements": context_elements}
        if block_id:
            block["block_id"] = block_id
        return block

    @staticmethod
    def image(image_url: str, alt_text: str, title: Optional[str] = None) -> Dict[str, Any]:
        """Tam genişlikte bir görsel bloğu oluşturur."""
        block = {
            "type": "image",
            "image_url": image_url,
            "alt_text": alt_text
        }
        if title:
            block["title"] = {"type": "plain_text", "text": title, "emoji": True}
        return block

    # --- Elementler (Block içinde kullanılan alt parçalar) ---

    @staticmethod
    def button(
        text: str, 
        action_id: str, 
        value: Optional[str] = None, 
        style: Optional[str] = None, 
        url: Optional[str] = None,
        confirm: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Buton elementi oluşturur. Style: 'primary' (yeşil) veya 'danger' (kırmızı)."""
        element = {
            "type": "button",
            "text": {"type": "plain_text", "text": text, "emoji": True},
            "action_id": action_id
        }
        if value: element["value"] = value
        if style: element["style"] = style
        if url: element["url"] = url
        if confirm: element["confirm"] = confirm
        return element

    @staticmethod
    def static_select(
        placeholder: str, 
        action_id: str, 
        options: List[Dict[str, str]], 
        initial_option: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Açılır menü (dropdown) oluşturur."""
        element = {
            "type": "static_select",
            "placeholder": {"type": "plain_text", "text": placeholder, "emoji": True},
            "action_id": action_id,
            "options": [
                {
                    "text": {"type": "plain_text", "text": opt["label"], "emoji": True},
                    "value": opt["value"]
                } for opt in options
            ]
        }
        if initial_option:
            element["initial_option"] = {
                "text": {"type": "plain_text", "text": initial_option["label"], "emoji": True},
                "value": initial_option["value"]
            }
        return element


class Formatter:
    """
    Slack 'mrkdwn' formatını (bold, italic, link, mention) 
    kolayca oluşturan yardımcı sınıf.
    """
    
    @staticmethod
    def bold(text: str) -> str: return f"*{text}*"
    
    @staticmethod
    def italic(text: str) -> str: return f"_{text}_"
    
    @staticmethod
    def strike(text: str) -> str: return f"~{text}~"
    
    @staticmethod
    def code(text: str) -> str: return f"`{text}`"
    
    @staticmethod
    def block_quote(text: str) -> str: return f"> {text}"
    
    @staticmethod
    def user(user_id: str) -> str: return f"<@{user_id}>"
    
    @staticmethod
    def channel(channel_id: str) -> str: return f"<#{channel_id}>"
    
    @staticmethod
    def link(url: str, text: Optional[str] = None) -> str:
        return f"<{url}|{text}>" if text else f"<{url}>"

    @staticmethod
    def time(timestamp: int, format_str: str = "{date_num} {time}") -> str:
        """Kullanıcının yerel saat dilimine göre zamanı gösterir (fallback dahil)."""
        return f"<!date^{timestamp}^{format_str}|{timestamp}>"


class MessageBuilder:
    """
    Slack mesajlarını akıcı (fluent) bir şekilde oluşturmak için builder sınıfı.
    Kullanımı: 
    blocks = MessageBuilder().add_header("Hi").add_text("Welcome").build()
    """

    def __init__(self):
        self._blocks: List[Dict] = []

    def add_header(self, text: str) -> "MessageBuilder":
        # Slack header plain_text üst sınırı 150 karakter
        t = (text or "")[:150]
        self._blocks.append(BlockBuilder.header(t))
        return self

    def add_text(self, text: str, fields: Optional[List[str]] = None) -> "MessageBuilder":
        self._blocks.append(BlockBuilder.section(text=text, fields=fields))
        return self

    def add_plain_text(self, text: str) -> "MessageBuilder":
        """plain_text section(lar); LLM çıktısı için (mrkdwn limiti / özel karakter riskinden kaçınır)."""
        t = text or ""
        if not t.strip():
            return self
        max_c = 2999
        i = 0
        while i < len(t):
            chunk = t[i : i + max_c]
            self._blocks.append(
                {
                    "type": "section",
                    "text": {"type": "plain_text", "text": chunk, "emoji": True},
                }
            )
            i += max_c
        return self

    def add_divider(self) -> "MessageBuilder":
        self._blocks.append(BlockBuilder.divider())
        return self

    def add_button(
        self,
        text: str,
        action_id: str,
        style: Optional[str] = None,
        *,
        value: Optional[str] = None,
        url: Optional[str] = None,
        confirm: Optional[Dict[str, Any]] = None,
    ) -> "MessageBuilder":
        btn = BlockBuilder.button(
            text, action_id, value=value, style=style, url=url, confirm=confirm
        )
        # Son eklenen block bir 'actions' bloğu mu? (max 5 eleman kuralı)
        if self._blocks and self._blocks[-1]["type"] == "actions" and len(self._blocks[-1]["elements"]) < 5:
            self._blocks[-1]["elements"].append(btn)
        else:
            self._blocks.append(BlockBuilder.actions([btn]))
        return self

    def add_image(self, url: str, alt: str, title: str = None) -> "MessageBuilder":
        self._blocks.append(BlockBuilder.image(url, alt, title))
        return self

    def add_context(self, elements: List[str]) -> "MessageBuilder":
        self._blocks.append(BlockBuilder.context(elements))
        return self

    def build(self) -> List[Dict]:
        """Oluşturulan blok listesini döndürür."""
        return self._blocks
