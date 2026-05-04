"""
Tum handler modullerini Slack App'e kayit eder.
Bu dosya import edildiginde, commands ve events icindeki
@app.command / @app.view / @app.action dekoratorleri otomatik olarak aktive olur.
"""
from .commands import event as event_commands  # noqa: F401
from .events import event as event_events  # noqa: F401
