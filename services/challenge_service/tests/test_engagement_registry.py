"""Saf engagement yardımcısı — manager/settings import edilmez."""
from dataclasses import dataclass

from services.challenge_service.core.engagement import engaged_from_registry_channel_views


@dataclass
class _FakeRec:
    members: list[str]
    jury: list[str]


def test_evaluation_member_is_engaged():
    ok, reason = engaged_from_registry_channel_views(
        "U_TEAM",
        challenge_channels={},
        evaluation_channels={"CEVAL": _FakeRec(members=["U_TEAM"], jury=[])},
    )
    assert ok is True
    assert "değerlendirme" in reason.lower()


def test_jury_is_engaged():
    ok, reason = engaged_from_registry_channel_views(
        "U_JURY",
        challenge_channels={},
        evaluation_channels={"C": _FakeRec(members=["U_X"], jury=["U_JURY"])},
    )
    assert ok is True
    assert "jüri" in reason.lower()


def test_challenge_member_checked_before_eval_when_in_both():
    ok, reason = engaged_from_registry_channel_views(
        "U1",
        challenge_channels={"PCH": _FakeRec(members=["U1"], jury=[])},
        evaluation_channels={"E": _FakeRec(members=["U1"], jury=[])},
    )
    assert ok is True
    assert reason == "aktif bir challenge'dasınız"


def test_not_engaged_when_maps_empty():
    ok, reason = engaged_from_registry_channel_views(
        "U99",
        challenge_channels={},
        evaluation_channels={},
    )
    assert ok is False
    assert reason == ""
