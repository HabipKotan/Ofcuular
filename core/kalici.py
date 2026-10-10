"""
Kalıcı veri klasörü: proje klasöründen BAĞIMSIZ.
Yeni bir sürümü başka bir klasöre kursanız da öğrenci kayıtları (yüz izleri, şifreler) ve yüz modeli kaybolmaz.

Varsayılan: <kullanıcı klasörü>/DersAsistani   (Windows: C:\\Users\\<ad>\\DersAsistani)
Değiştirmek için .env: DERS_ASISTANI_VERI=C:\\baska\\klasor
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)
except ImportError:
    pass

KALICI = Path(os.getenv("DERS_ASISTANI_VERI") or (Path.home() / "DersAsistani"))


def klasor(*parcalar: str) -> Path:
    yol = KALICI.joinpath(*parcalar)
    yol.mkdir(parents=True, exist_ok=True)
    return yol
