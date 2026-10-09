"""
Rızalı öğrenci kaydı ve kişisel odak veritabanı (SQLite, tek dosya: ogrenciler.db)
================================================================================
Yalnızca AÇIK RIZA veren ve öğretmenin kaydettiği öğrenciler için kişisel odak tutulur.
Kayıtlı olmayan herkes (ör. sınıftaki diğer kişiler) yalnızca anonim sınıf ortalamasına katılır.

Saklananlar:
  ogrenciler   : ad, şifrenin geri çevrilemez özeti, yüz izi (sayı vektörü), rıza zamanı
                 -> FOTOĞRAF SAKLANMAZ; yüz izinden yüz görüntüsü geri üretilemez.
  kisisel_odak : (kayıt, öğrenci, ders saniyesi, odak skoru)

Şifreler: her öğrenciye öğretmen panelinde FARKLI bir şifre üretilir (ör. 7KQ-M3P).
Veritabanında şifrenin kendisi değil, gizli bir anahtarla alınmış özeti (HMAC-SHA256) tutulur.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import numpy as np

from core.kalici import klasor

PROJE = Path(__file__).resolve().parents[1]
VERI = Path(os.getenv("GERCEK_VERI_KLASORU") or PROJE)
ESKI_DB_YOLU = VERI / "ogrenciler.db"           # eski sürümlerde proje klasöründeydi
DB_YOLU = klasor() / "ogrenciler.db"             # artık kalıcı klasörde: yeni sürüm kurulunca kaybolmaz

if not DB_YOLU.exists() and ESKI_DB_YOLU.exists():  # eski kayıtları bir kez taşı
    import shutil

    shutil.copy2(ESKI_DB_YOLU, DB_YOLU)

SIFRE_HARFLERI = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # karışan karakterler (0/O, 1/I/L) yok


def _baglan() -> sqlite3.Connection:
    db = sqlite3.connect(DB_YOLU, timeout=10)
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE IF NOT EXISTS ayar (ad TEXT PRIMARY KEY, deger TEXT);
        CREATE TABLE IF NOT EXISTS ogrenciler (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ad TEXT NOT NULL,
            sifre_ozeti TEXT NOT NULL UNIQUE,
            yuz_izleri BLOB,
            iz_sayisi INTEGER DEFAULT 0,
            riza_zamani TEXT NOT NULL,
            olusturma TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS kisisel_odak (
            kayit TEXT NOT NULL,
            ogrenci_id INTEGER NOT NULL,
            saniye REAL NOT NULL,
            skor REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS kisisel_odak_ix ON kisisel_odak (kayit, ogrenci_id);
        CREATE TABLE IF NOT EXISTS beklenenler (   -- ders başında yüz kaydı olan (kamerada aranan) öğrenciler
            kayit TEXT NOT NULL,
            ogrenci_id INTEGER NOT NULL,
            PRIMARY KEY (kayit, ogrenci_id)
        );
    """)
    return db


def _gizli_anahtar(db: sqlite3.Connection) -> bytes:
    r = db.execute("SELECT deger FROM ayar WHERE ad='anahtar'").fetchone()
    if r:
        return bytes.fromhex(r["deger"])
    anahtar = secrets.token_bytes(32)
    db.execute("INSERT INTO ayar (ad, deger) VALUES ('anahtar', ?)", (anahtar.hex(),))
    db.commit()
    return anahtar


def _normal(sifre: str) -> str:
    return "".join(c for c in (sifre or "").upper() if c.isalnum())


def _ozet(db: sqlite3.Connection, sifre: str) -> str:
    return hmac.new(_gizli_anahtar(db), _normal(sifre).encode(), hashlib.sha256).hexdigest()


def _yeni_sifre(db: sqlite3.Connection) -> str:
    """Başka hiçbir öğrencininkiyle çakışmayan yeni şifre (ör. 7KQ-M3P)."""
    while True:
        s = "".join(secrets.choice(SIFRE_HARFLERI) for _ in range(6))
        s = f"{s[:3]}-{s[3:]}"
        if not db.execute("SELECT 1 FROM ogrenciler WHERE sifre_ozeti=?", (_ozet(db, s),)).fetchone():
            return s


# ---------------------------------------------------------------------------
# Öğrenciler
# ---------------------------------------------------------------------------
def ogrenci_ekle(ad: str, yuz_izleri: Optional[np.ndarray] = None) -> tuple[int, str]:
    """Yeni öğrenci. yuz_izleri None ise yüz kaydı olmayan (yalnızca şifreli) öğrenci.
    Dönüş: (id, şifre). Şifre yalnızca burada düz metin olarak görünür."""
    izler = (np.asarray(yuz_izleri, dtype=np.float32).reshape(-1, 128) if yuz_izleri is not None
             else np.zeros((0, 128), np.float32))
    with _baglan() as db:
        sifre = _yeni_sifre(db)
        simdi = datetime.now().isoformat(timespec="seconds")
        cur = db.execute(
            "INSERT INTO ogrenciler (ad, sifre_ozeti, yuz_izleri, iz_sayisi, riza_zamani, olusturma) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ad.strip(), _ozet(db, sifre), izler.tobytes() if len(izler) else None, len(izler), simdi, simdi))
        return cur.lastrowid, sifre


def sifre_yenile(ogrenci_id: int) -> str:
    with _baglan() as db:
        sifre = _yeni_sifre(db)
        db.execute("UPDATE ogrenciler SET sifre_ozeti=? WHERE id=?", (_ozet(db, sifre), ogrenci_id))
        return sifre


def ogrenci_sil(ogrenci_id: int) -> None:
    """Öğrenciyi, yüz izini ve bütün kişisel odak verisini kalıcı olarak siler (unutulma hakkı)."""
    with _baglan() as db:
        db.execute("DELETE FROM kisisel_odak WHERE ogrenci_id=?", (ogrenci_id,))
        db.execute("DELETE FROM beklenenler WHERE ogrenci_id=?", (ogrenci_id,))
        db.execute("DELETE FROM beklenenler WHERE ogrenci_id=?", (ogrenci_id,))
        db.execute("DELETE FROM ogrenciler WHERE id=?", (ogrenci_id,))


def ogrenciler() -> List[dict]:
    if not DB_YOLU.exists():
        return []
    with _baglan() as db:
        return [dict(id=r["id"], ad=r["ad"], iz_sayisi=r["iz_sayisi"], riza_zamani=r["riza_zamani"])
                for r in db.execute("SELECT id, ad, iz_sayisi, riza_zamani FROM ogrenciler ORDER BY ad")]


def yuz_izleri() -> List[tuple[int, str, np.ndarray]]:
    """Kamera tarafı için: [(id, ad, izler (k,128))]."""
    if not DB_YOLU.exists():
        return []
    with _baglan() as db:
        return [(r["id"], r["ad"], np.frombuffer(r["yuz_izleri"], dtype=np.float32).reshape(-1, 128))
                for r in db.execute("SELECT id, ad, yuz_izleri FROM ogrenciler "
                                    "WHERE yuz_izleri IS NOT NULL AND iz_sayisi > 0")]


def giris(sifre: str) -> Optional[dict]:
    if not DB_YOLU.exists() or not _normal(sifre):
        return None
    with _baglan() as db:
        r = db.execute("SELECT id, ad FROM ogrenciler WHERE sifre_ozeti=?", (_ozet(db, sifre),)).fetchone()
        return dict(id=r["id"], ad=r["ad"]) if r else None


# ---------------------------------------------------------------------------
# Kişisel odak
# ---------------------------------------------------------------------------
def odak_ekle(kayit: str, satirlar: List[tuple[int, float, float]]) -> None:
    """satirlar: [(ogrenci_id, saniye, skor)]"""
    if not satirlar:
        return
    with _baglan() as db:
        db.executemany("INSERT INTO kisisel_odak (kayit, ogrenci_id, saniye, skor) VALUES (?, ?, ?, ?)",
                       [(kayit, int(o), float(s), float(k)) for o, s, k in satirlar])


def kisisel_odak(kayit: str, ogrenci_id: int) -> List[tuple[float, float]]:
    if not DB_YOLU.exists() or not kayit:
        return []
    with _baglan() as db:
        return [(r["saniye"], r["skor"]) for r in db.execute(
            "SELECT saniye, skor FROM kisisel_odak WHERE kayit=? AND ogrenci_id=? ORDER BY saniye",
            (kayit, ogrenci_id))]


def kayittaki_ogrenci_sayisi(kayit: str) -> int:
    if not DB_YOLU.exists() or not kayit:
        return 0
    with _baglan() as db:
        return db.execute("SELECT COUNT(DISTINCT ogrenci_id) FROM kisisel_odak WHERE kayit=?", (kayit,)).fetchone()[0]


# ---------------------------------------------------------------------------
# Katılım: ders başında kamerada aranan (yüz kaydı olan) öğrenciler
# ---------------------------------------------------------------------------
def beklenenler_ekle(kayit: str, ogrenci_idleri: List[int]) -> None:
    if not kayit or not ogrenci_idleri:
        return
    with _baglan() as db:
        db.executemany("INSERT OR IGNORE INTO beklenenler (kayit, ogrenci_id) VALUES (?, ?)",
                       [(kayit, int(o)) for o in ogrenci_idleri])


def beklenen_mi(kayit: str, ogrenci_id: int) -> bool:
    if not DB_YOLU.exists() or not kayit:
        return False
    with _baglan() as db:
        return db.execute("SELECT 1 FROM beklenenler WHERE kayit=? AND ogrenci_id=?",
                          (kayit, ogrenci_id)).fetchone() is not None


def katilim(kayit: str) -> tuple[int, int]:
    """(derste görülen, beklenen) kayıtlı öğrenci sayısı."""
    if not DB_YOLU.exists() or not kayit:
        return 0, 0
    with _baglan() as db:
        beklenen = db.execute("SELECT COUNT(*) FROM beklenenler WHERE kayit=?", (kayit,)).fetchone()[0]
        gorulen = db.execute("SELECT COUNT(DISTINCT k.ogrenci_id) FROM kisisel_odak k JOIN beklenenler b "
                             "ON b.kayit=k.kayit AND b.ogrenci_id=k.ogrenci_id WHERE k.kayit=?", (kayit,)).fetchone()[0]
        return gorulen, beklenen
