"""Registry üzerinden kullanıcı meşguliyeti — DB/settings import yok (test + manager)."""
from __future__ import annotations

from typing import Mapping, Protocol, runtime_checkable


@runtime_checkable
class _ChannelRecordLike(Protocol):
    members: list[str]
    jury: list[str]


def engaged_from_registry_channel_views(
    user_id: str,
    *,
    challenge_channels: Mapping[str, _ChannelRecordLike],
    evaluation_channels: Mapping[str, _ChannelRecordLike],
) -> tuple[bool, str]:
    """
    Kuyruk / pending dışındaki registry tabanlı meşguliyet.
    Challenge kayıtları önce, ardından değerlendirme (takım üyesi, sonra jüri).
    """
    for record in challenge_channels.values():
        if user_id in record.members:
            return True, "aktif bir challenge'dasınız"
    for record in evaluation_channels.values():
        if user_id in record.members:
            return True, "challenge'ınız değerlendirme aşamasında"
        if user_id in record.jury:
            return True, "aktif bir değerlendirmede jüri üyesisiniz"
    return False, ""
