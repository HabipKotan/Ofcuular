"""
Windows'ta güvenli dosya yazımı.

Windows'ta bir dosya o anda başka bir program tarafından açıksa (arayüzün o anki okuması, OneDrive eşitlemesi,
antivirüs taraması) üzerine yazmak/yerini değiştirmek "Erişim engellendi" (WinError 5 / 32) hatası verir.
Bu yardımcı önce yarım okunmasın diye geçici dosya + yer değiştirme dener; olmazsa kısa aralıklarla tekrar dener;
yine olmazsa doğrudan yazar.
"""

from __future__ import annotations

import os
import time
from pathlib import Path


def guvenli_yaz(yol: Path, metin: str, deneme: int = 25, bekleme: float = 0.08) -> None:
    yol = Path(yol)
    gecici = yol.with_suffix(yol.suffix + ".tmp")
    son_hata = None
    for i in range(deneme):
        try:
            gecici.write_text(metin, encoding="utf-8")
            os.replace(gecici, yol)
            return
        except PermissionError as e:   # dosya başka bir programda açık: biraz bekle
            son_hata = e
            time.sleep(bekleme * (1 + i // 5))
    for i in range(deneme):           # son çare: doğrudan yaz
        try:
            yol.write_text(metin, encoding="utf-8")
            try:
                gecici.unlink(missing_ok=True)
            except OSError:
                pass
            return
        except PermissionError as e:
            son_hata = e
            time.sleep(bekleme)
    raise son_hata
