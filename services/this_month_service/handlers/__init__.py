"""
Tum handler modullerini Slack App'e kayit eder.
Bu dosya import edildiginde, commands icindeki
@app.command dekoratorleri otomatik olarak aktive olur.
"""
from .commands import this_month as this_month_commands  # noqa: F401
