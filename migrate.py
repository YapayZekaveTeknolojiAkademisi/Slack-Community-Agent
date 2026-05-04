#!/usr/bin/env python
"""
Alembic migration yönetim aracı.

Kullanım:
  python migrate.py upgrade          # head'e çıkar (en son migration)
  python migrate.py upgrade <rev>    # belirli bir revision'a çık
  python migrate.py downgrade        # bir adım geri al
  python migrate.py downgrade <rev>  # belirli bir revision'a in
  python migrate.py revision <mesaj> # yeni (boş) migration dosyası oluştur
  python migrate.py autogenerate <mesaj> # model farkından migration üret
  python migrate.py current          # mevcut DB revision'ı göster
  python migrate.py history          # tüm migration geçmişini listele
  python migrate.py heads            # en güncel revision(lar)ı göster
  python migrate.py stamp <rev>      # migration çalıştırmadan revision işaretle
  python migrate.py sql              # upgrade SQL'ini ekrana bas (offline)
"""

from __future__ import annotations

import sys
from alembic.config import Config
from alembic import command


def _cfg() -> Config:
    return Config("alembic.ini")


HELP = __doc__


def main() -> None:
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help", "help"):
        print(HELP)
        return

    cmd = args[0]
    cfg = _cfg()

    if cmd == "upgrade":
        rev = args[1] if len(args) > 1 else "head"
        print(f"⬆  Upgrading to: {rev}")
        command.upgrade(cfg, rev)
        print("✓  Done.")

    elif cmd == "downgrade":
        rev = args[1] if len(args) > 1 else "-1"
        print(f"⬇  Downgrading to: {rev}")
        command.downgrade(cfg, rev)
        print("✓  Done.")

    elif cmd == "revision":
        if len(args) < 2:
            print("Hata: mesaj gerekli.\n  python migrate.py revision 'kısa açıklama'")
            sys.exit(1)
        message = args[1]
        print(f"📝 Yeni migration: {message!r}")
        command.revision(cfg, message=message, autogenerate=False)

    elif cmd == "autogenerate":
        if len(args) < 2:
            print(
                "Hata: mesaj gerekli.\n  python migrate.py autogenerate 'kısa açıklama'"
            )
            sys.exit(1)
        message = args[1]
        print(f"🔍 Model farkından migration üretiliyor: {message!r}")
        command.revision(cfg, message=message, autogenerate=True)

    elif cmd == "current":
        command.current(cfg, verbose=True)

    elif cmd == "history":
        command.history(cfg, verbose=True)

    elif cmd == "heads":
        command.heads(cfg, verbose=True)

    elif cmd == "stamp":
        if len(args) < 2:
            print("Hata: revision gerekli.\n  python migrate.py stamp <rev>")
            sys.exit(1)
        rev = args[1]
        print(f"🔖 Stamping: {rev}")
        command.stamp(cfg, rev)
        print("✓  Done.")

    elif cmd == "sql":
        # Offline mod — SQL script üretir, DB'ye bağlanmaz
        rev = args[1] if len(args) > 1 else "head"
        print(f"📄 Upgrade SQL (offline, head={rev}):\n")
        command.upgrade(cfg, rev, sql=True)

    else:
        print(f"Bilinmeyen komut: {cmd!r}\n")
        print(HELP)
        sys.exit(1)


if __name__ == "__main__":
    main()
