"""Servis bazlı üç harflik Slack metin önekleri (köşeli ayraç ile)."""

from __future__ import annotations

PREFIX_CHALLENGE = "CHG"
PREFIX_SUMMARY = "SUM"


def fmt(prefix: str, msg: str) -> str:
    return f"[{prefix}] {msg}"
