from __future__ import annotations

import csv
import io
from typing import Optional
from urllib.request import urlopen
from urllib.error import URLError

from .constants import MONTHLY_CSV_URL, DEPARTMENT_ALIASES
from ..logger import _logger


def detect_department(title: str) -> Optional[str]:
    if not title:
        return None
    title_lower = title.lower().strip()
    for code, aliases in DEPARTMENT_ALIASES.items():
        for alias in aliases:
            if alias in title_lower:
                return code
    return None


def fetch_monthly_trainings() -> list[dict]:
    try:
        with urlopen(MONTHLY_CSV_URL, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
    except (URLError, OSError) as exc:
        _logger.error("[this-month] Google Sheets CSV fetch failed: %s", exc)
        return []

    reader = csv.reader(io.StringIO(raw))
    rows = list(reader)

    if not rows:
        return []

    trainings: list[dict] = []
    current_month = ""

    for row in rows[1:]: 
        if len(row) < 4:
            continue

        month_cell = row[0].strip()
        training = row[1].strip()
        status = row[2].strip()
        departments_raw = row[3].strip()

        if month_cell:
            current_month = month_cell

        if not training:
            continue

        dept_list = [d.strip() for d in departments_raw.split(",") if d.strip()]

        trainings.append({
            "ay": current_month,
            "egitim": training,
            "durum": status,
            "bolumler": dept_list,
        })

    return trainings


def filter_trainings(
    trainings: list[dict],
    month_name: str,
    department_code: str,
) -> list[dict]:
    results = []
    for t in trainings:
        if t["ay"] != month_name:
            continue
        if department_code in t["bolumler"]:
            results.append(t)
    return results
