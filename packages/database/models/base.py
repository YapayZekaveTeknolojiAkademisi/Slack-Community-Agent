"""SQLAlchemy Base — tüm ORM modelleri metadata için yüklenir (create_all)."""

from __future__ import annotations

from packages.database.mixins import Base
from packages.database.models import challenge as _challenge  # noqa: F401
<<<<<<< feat/feature_request_service
from packages.database.models import slack as _slack  # noqa: F401
from packages.database.models import user as _user  # noqa: F401
from packages.database.models import feature_request as _feature_request  # noqa: F401
=======
from packages.database.models import event as _event  # noqa: F401
>>>>>>> dev

__all__ = ["Base"]
