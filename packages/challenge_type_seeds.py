"""
challenge_types için `seeds/*.json` yükleme mantığı.

Challenge servisi başlarken çağrılır (`services.challenge_service`).
Kurallar: `id` `CHT-` ile başlamalı; veritabanında aynı `id` varsa atlanır, yoksa eklenir.
`points` JSON içinde elle verilmeli ve kategori bantlarında olmalıdır.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.models.challenge import ChallengeCategory, ChallengeType

_log = logging.getLogger(__name__)

VALID_CATEGORY = frozenset({"learn", "practice", "real_world", "no_code_low_code"})

# Seeds doğrulaması: kategori başına puan bantları (dahil); puanlar JSON'da elle yazılır.
CATEGORY_POINTS_BAND: dict[str, tuple[int, int]] = {
    "learn": (24, 34),
    "no_code_low_code": (34, 44),
    "practice": (46, 62),
    "real_world": (64, 92),
}

EXPECTED_FILENAME_CATEGORY: dict[str, str] = {
    "learn": "learn",
    "practice": "practice",
    "real_world": "real_world",
    "no_code_low_code": "no_code_low_code",
}


def seeds_directory_default() -> Path:
    """Depo kökündeki `seeds/` klasörü (`packages/` bir üst dizin)."""
    return Path(__file__).resolve().parents[1] / "seeds"


def _expected_category_for_file(stem: str) -> str | None:
    return EXPECTED_FILENAME_CATEGORY.get(stem)


def load_challenge_type_rows(seeds_dir: Path) -> list[tuple[Path, dict]]:
    """Tüm `*.json` dosyalarından `challenge_types` satırlarını okur."""
    out: list[tuple[Path, dict]] = []
    for path in sorted(seeds_dir.glob("*.json")):
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON parse: {path}: {e}") from e
        rows = blob.get("challenge_types")
        if rows is None:
            _log.warning("challenge_types seed: %s içinde 'challenge_types' yok, atlanıyor", path.name)
            continue
        if not isinstance(rows, list):
            raise ValueError(f"{path}: challenge_types liste olmalı")
        for item in rows:
            if isinstance(item, dict):
                out.append((path, item))
    return out


def validate_challenge_type_row(row: dict, src: Path) -> tuple[bool, str]:
    """Dönüş: (ok, hata_metni). Başarıda hata_metni boş."""
    cid = row.get("id")
    if not cid or not isinstance(cid, str):
        return False, "id zorunlu ve string olmalı"
    if not cid.startswith("CHT-"):
        return False, "id CHT- ile başlamalı (ChallengeType.__prefix__)"
    if len(cid) > 60:
        return False, "id 60 karakterden uzun olamaz"

    cat_raw = row.get("category")
    if not isinstance(cat_raw, str):
        return False, "category string olmalı"
    if cat_raw not in VALID_CATEGORY:
        return False, f"bilinmeyen category: {cat_raw}"

    expected = _expected_category_for_file(src.stem)
    if expected is not None and cat_raw != expected:
        return False, f"dosya adına göre beklenen kategori '{expected}' iken '{cat_raw}'"

    name = row.get("name")
    if not isinstance(name, str) or not name.strip():
        return False, "name zorunlu"

    dh = row.get("deadline_hours")
    if dh is not None:
        if isinstance(dh, bool) or not isinstance(dh, int):
            return False, "deadline_hours null veya tamsayı olmalı"

    pts = row.get("points")
    if pts is None:
        return False, "points JSON'da zorunlu ve elle verilmeli (tamsayı)"
    if isinstance(pts, bool) or not isinstance(pts, int):
        return False, "points pozitif tamsayı olmalı"
    if pts < 1 or pts > 500:
        return False, "points 1..500 aralığında olmalı"
    lo, hi = CATEGORY_POINTS_BAND.get(cat_raw, (1, 500))
    if pts < lo or pts > hi:
        return False, f"points bu kategori için beklenen bant [{lo},{hi}] dışında"

    chk = row.get("checklist")
    if chk is not None:
        if not isinstance(chk, list) or any(not isinstance(x, str) for x in chk):
            return False, "checklist null veya string listesi olmalı"

    meta = row.get("meta")
    if meta is not None and not isinstance(meta, (dict, list)):
        return False, "meta null, dict veya list olmalı"

    description = row.get("description")
    if description is not None and not isinstance(description, str):
        return False, "description null veya string olmalı"

    return True, ""


async def sync_challenge_types(
    session: AsyncSession,
    *,
    seeds_dir: Path | None = None,
) -> tuple[int, int]:
    """
    Eksik challenge_type satırlarını `seeds/` JSON'larından ekler.
    Önce tüm satırlar doğrulanır; hata varsa DB'ye yazım yapılmaz.

    Dönüş: (inserted, skipped_existing)
    """
    sd = seeds_dir or seeds_directory_default()
    if not sd.is_dir():
        _log.warning("challenge_types seed: klasör yok (%s) — atlanıyor", sd)
        return 0, 0

    rows = load_challenge_type_rows(sd)
    if not rows:
        _log.info("challenge_types seed: yüklenecek satır yok")
        return 0, 0

    errors: list[str] = []
    for src, row in rows:
        ok, errmsg = validate_challenge_type_row(row, src)
        if not ok:
            errors.append(f"{src.name} id={row.get('id', '?')}: {errmsg}")

    if errors:
        for line in errors:
            _log.error("challenge_types seed: %s", line)
        raise ValueError(f"challenge_types seed: {len(errors)} geçersiz satır (servis başlatılamadı)")

    inserted = 0
    skipped = 0
    for _src, row in rows:
        cid = row["id"]
        existing = await session.get(ChallengeType, cid)
        if existing:
            skipped += 1
            continue
        session.add(
            ChallengeType(
                id=cid,
                category=ChallengeCategory(row["category"]),
                name=(row["name"] or "").strip()[:255],
                description=row.get("description"),
                deadline_hours=row.get("deadline_hours"),
                points=row["points"],
                checklist=row.get("checklist"),
                meta=row.get("meta"),
            )
        )
        inserted += 1
        _log.info("challenge_types seed: yeni tip eklendi id=%s points=%s", cid, row["points"])

    _log.info(
        "challenge_types seed: tamamlandı (yeni=%s, mevcut_id_atlandı=%s, toplam_satır=%s)",
        inserted,
        skipped,
        len(rows),
    )
    return inserted, skipped
