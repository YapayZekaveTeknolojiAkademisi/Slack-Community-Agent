"""Google Calendar URL olusturucu — API gerektirmez, URL semasi kullanir."""
from __future__ import annotations

from datetime import date, time, datetime, timedelta
from urllib.parse import quote


def build_google_calendar_url(
    title: str,
    event_date: date,
    event_time: time,
    duration_minutes: int,
    description: str = "",
    location: str = "",
) -> str:
    """Google Calendar 'Add Event' URL'i olusturur.

    Tarih/saat bilgisi timezone-naive olarak gonderilir (Z suffix'i yok).
    Google Calendar kullanicinin yerel timezone'unu uygular.
    Hatirlatma: 30 dakika once + 1 gun once popup.
    """
    start_dt = datetime.combine(event_date, event_time)
    end_dt = start_dt + timedelta(minutes=duration_minutes)

    date_fmt = "%Y%m%dT%H%M%S"
    dates = f"{start_dt.strftime(date_fmt)}/{end_dt.strftime(date_fmt)}"

    params = {
        "action": "TEMPLATE",
        "text": title,
        "dates": dates,
        "details": description,
        "location": location,
        "crm": "POPUP,30,POPUP,1440",
    }
    query = "&".join(f"{k}={quote(str(v))}" for k, v in params.items() if v)
    return f"https://calendar.google.com/calendar/render?{query}"
