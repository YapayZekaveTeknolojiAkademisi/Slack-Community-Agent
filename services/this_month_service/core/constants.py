from __future__ import annotations

SPREADSHEET_ID = "1KKMmLwHSkRlhhCh_PmqhLbooBCRiB2Xb43o7FcCZrM8"

MONTHLY_SHEET_GID = "894647740"
MONTHLY_CSV_URL = (
    f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}"
    f"/export?format=csv&gid={MONTHLY_SHEET_GID}"
)

MONTH_NAMES_TR: dict[int, str] = {
    1: "Ocak",
    2: "Şubat",
    3: "Mart",
    4: "Nisan",
    5: "Mayıs",
    6: "Haziran",
    7: "Temmuz",
    8: "Ağustos",
    9: "Eylül",
    10: "Ekim",
    11: "Kasım",
    12: "Aralık",
}

DEPARTMENT_ALIASES: dict[str, list[str]] = {
    "YZ": ["yapay zeka", "yapay zekâ", "yz", "ai", "artificial intelligence"],
    "VB": ["veri bilimi", "vb", "data science", "ds", "veri"],
    "NC/LC": [
        "no code/low code", "no code", "low code", "nc/lc", "nclc",
        "no-code", "low-code", "nocode", "lowcode", "no code / low code",
    ],
}

DEPT_DISPLAY_NAMES: dict[str, str] = {
    "YZ": "🤖 Yapay Zeka",
    "VB": "📊 Veri Bilimi",
    "NC/LC": "🚀 No Code / Low Code",
}
