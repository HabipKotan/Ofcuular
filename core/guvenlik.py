"""
Güvenlik katmanı
================
1) Kaba kuvvet (şifre deneme) koruması: art arda yanlış şifrede giriş kilitlenir; kilit süresi her seferinde
   ikiye katlanır. Sayaç veritabanında tutulur (yeni sekme / yeni oturum açmak kilidi aşmaz).
2) Öğretmen şifresi ZORUNLU: .env'de OGRETMEN_SIFRESI yoksa ilk açılışta öğretmen bir şifre belirler;
   şifre PBKDF2-SHA256 (200.000 tur + rastgele tuz) ile özetlenerek saklanır, kendisi hiçbir yerde tutulmaz.
3) Biyometrik veriyi (yüz izi) diskte şifreleme: Windows'ta DPAPI (Windows'un kendi veri koruma servisi).
   Şifreli veri yalnızca BU bilgisayarda, BU Windows kullanıcısıyla açılır; ogrenciler.db dosyası çalınıp
   başka bir bilgisayara götürülse yüz izleri okunamaz.
4) Güvenlik günlüğü: giriş denemeleri, öğrenci kaydı/silme, şifre yenileme... (şifrelerin kendisi yazılmaz).
5) Oturum zaman aşımı: hareketsiz kalan öğretmen / öğrenci oturumu kendiliğinden kapanır.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from datetime import datetime
from typing import List, Optional, Tuple

_AD = {"ogretmen": "Öğretmen", "ogrenci": "Öğrenci"}
KILIT_ESIGI = 5            # bu kadar yanlış denemeden sonra kilit
ILK_KILIT_SN = 60          # ilk kilit süresi; her yeni kilitte 2 katı (en çok 15 dk)
EN_UZUN_KILIT_SN = 15 * 60
OTURUM_ZAMAN_ASIMI_SN = int(os.getenv("OTURUM_ZAMAN_ASIMI_DK") or 30) * 60
PBKDF2_TUR = 200_000


def _db() -> sqlite3.Connection:
    from core import ogrenci_db  # tablolar ogrenciler.db içinde (tek dosya)
    db = ogrenci_db._baglan()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS giris_kilidi (
            tur TEXT PRIMARY KEY, hata INTEGER NOT NULL DEFAULT 0,
            kilit_sayisi INTEGER NOT NULL DEFAULT 0, kilit_bitis REAL NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS guvenlik_gunlugu (
            id INTEGER PRIMARY KEY AUTOINCREMENT, zaman TEXT NOT NULL, olay TEXT NOT NULL, ayrinti TEXT);
    """)
    return db


# ---------------------------------------------------------------------------
# Güvenlik günlüğü
# ---------------------------------------------------------------------------
def gunluk(olay: str, ayrinti: str = "") -> None:
    try:
        with _db() as db:
            db.execute("INSERT INTO guvenlik_gunlugu (zaman, olay, ayrinti) VALUES (?, ?, ?)",
                       (datetime.now().isoformat(timespec="seconds"), olay, ayrinti[:200]))
            db.execute("DELETE FROM guvenlik_gunlugu WHERE id <= (SELECT MAX(id) - 2000 FROM guvenlik_gunlugu)")
    except Exception:
        pass  # günlük yazılamadı diye uygulama durmasın


def son_olaylar(n: int = 25) -> List[Tuple[str, str, str]]:
    try:
        with _db() as db:
            return [(r["zaman"], r["olay"], r["ayrinti"] or "") for r in db.execute(
                "SELECT zaman, olay, ayrinti FROM guvenlik_gunlugu ORDER BY id DESC LIMIT ?", (n,))]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Kaba kuvvet koruması
# ---------------------------------------------------------------------------
def kilit_kalan(tur: str) -> int:
    """Giriş kilitliyse kalan saniye, değilse 0. tur: 'ogretmen' | 'ogrenci'"""
    with _db() as db:
        r = db.execute("SELECT kilit_bitis FROM giris_kilidi WHERE tur=?", (tur,)).fetchone()
    return max(0, int((r["kilit_bitis"] if r else 0) - time.time() + 0.999))


def basarisiz(tur: str) -> int:
    """Yanlış denemeyi sayar. Kilit başladıysa kilit süresini döndürür, yoksa 0."""
    with _db() as db:
        r = db.execute("SELECT hata, kilit_sayisi FROM giris_kilidi WHERE tur=?", (tur,)).fetchone()
        hata, kilit_sayisi = ((r["hata"], r["kilit_sayisi"]) if r else (0, 0))
        hata += 1
        sure = 0
        if hata >= KILIT_ESIGI:
            sure = min(EN_UZUN_KILIT_SN, ILK_KILIT_SN * 2 ** kilit_sayisi)
            hata, kilit_sayisi = 0, kilit_sayisi + 1
        db.execute("INSERT INTO giris_kilidi (tur, hata, kilit_sayisi, kilit_bitis) VALUES (?, ?, ?, ?) "
                   "ON CONFLICT(tur) DO UPDATE SET hata=excluded.hata, kilit_sayisi=excluded.kilit_sayisi, "
                   "kilit_bitis=CASE WHEN ?>0 THEN excluded.kilit_bitis ELSE giris_kilidi.kilit_bitis END",
                   (tur, hata, kilit_sayisi, time.time() + sure, sure))
    gunluk(f"{_AD.get(tur, tur)} girişi: yanlış şifre", f"{sure} sn kilit" if sure else "")
    return sure


def basarili(tur: str, kim: str = "") -> None:
    with _db() as db:
        db.execute("DELETE FROM giris_kilidi WHERE tur=?", (tur,))
    gunluk(f"{_AD.get(tur, tur)} girişi: başarılı", kim)


# ---------------------------------------------------------------------------
# Öğretmen şifresi
# ---------------------------------------------------------------------------
def _pbkdf2(sifre: str, tuz: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", sifre.encode(), tuz, PBKDF2_TUR).hex()


def ogretmen_sifresi_var() -> bool:
    if (os.getenv("OGRETMEN_SIFRESI") or "").strip():
        return True
    with _db() as db:
        return db.execute("SELECT 1 FROM ayar WHERE ad='ogretmen_sifre'").fetchone() is not None


def ogretmen_sifresi_belirle(sifre: str) -> None:
    tuz = secrets.token_bytes(16)
    with _db() as db:
        db.execute("INSERT OR REPLACE INTO ayar (ad, deger) VALUES ('ogretmen_sifre', ?)",
                   (f"{tuz.hex()}${_pbkdf2(sifre, tuz)}",))
    gunluk("öğretmen şifresi belirlendi / değiştirildi")


def ogretmen_sifresi_dogru(girilen: str) -> bool:
    env = (os.getenv("OGRETMEN_SIFRESI") or "").strip()
    if env:
        return hmac.compare_digest(girilen.encode(), env.encode())  # sabit süreli karşılaştırma
    with _db() as db:
        r = db.execute("SELECT deger FROM ayar WHERE ad='ogretmen_sifre'").fetchone()
    if not r:
        return False
    tuz, ozet = r["deger"].split("$", 1)
    return hmac.compare_digest(_pbkdf2(girilen, bytes.fromhex(tuz)), ozet)


def sifre_zayif_mi(sifre: str) -> Optional[str]:
    if len(sifre) < 8:
        return "Şifre en az 8 karakter olmalı."
    if sifre.isdigit() or sifre.isalpha():
        return "Şifrede hem harf hem rakam (ya da işaret) bulunsun."
    if sifre.lower() in ("12345678", "password", "sifre123", "ogretmen1", "qwerty12"):
        return "Bu şifre çok yaygın."
    return None


# ---------------------------------------------------------------------------
# Biyometrik veriyi diskte şifreleme (Windows DPAPI)
# ---------------------------------------------------------------------------
ONEK = b"DPAPI1:"


def _dpapi(veri: bytes, coz: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    tampon = ctypes.create_string_buffer(veri, len(veri))
    giris = BLOB(len(veri), ctypes.cast(tampon, ctypes.POINTER(ctypes.c_char)))
    cikis = BLOB()
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    CRYPTPROTECT_UI_FORBIDDEN = 0x01
    if coz:
        ok = crypt32.CryptUnprotectData(ctypes.byref(giris), None, None, None, None,
                                        CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(cikis))
    else:
        ok = crypt32.CryptProtectData(ctypes.byref(giris), "DersAsistani yuz izi", None, None, None,
                                      CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(cikis))
    if not ok:
        raise OSError(f"DPAPI hatası ({ctypes.GetLastError()})")
    try:
        return ctypes.string_at(cikis.pbData, cikis.cbData)
    finally:
        kernel32.LocalFree(cikis.pbData)


def sifreleme_acik() -> bool:
    return os.name == "nt"


def sifrele(veri: bytes) -> bytes:
    """Windows'ta DPAPI ile şifreler (ve geri açılabildiğini doğrular). Olmazsa veriyi aynen döndürür."""
    if not veri or not sifreleme_acik():
        return veri
    try:
        kapali = _dpapi(veri, coz=False)
        if _dpapi(kapali, coz=True) == veri:  # geri açılamayan bir şey asla yazılmasın
            return ONEK + kapali
    except Exception as e:
        gunluk("yüz izi şifrelenemedi", str(e))
    return veri


def coz(veri: Optional[bytes]) -> Optional[bytes]:
    if veri and veri.startswith(ONEK):
        return _dpapi(veri[len(ONEK):], coz=True)
    return veri


def sifreli_mi(veri: Optional[bytes]) -> bool:
    return bool(veri) and veri.startswith(ONEK)


# ---------------------------------------------------------------------------
# Oturum zaman aşımı
# ---------------------------------------------------------------------------
def oturum_suresi_doldu(ss, anahtar: str) -> bool:
    """Her sayfa çiziminde çağrılır: son hareketten bu yana süre dolduysa True (ve sayaç sıfırlanır)."""
    simdi = time.time()
    son = ss.get(f"_son_hareket_{anahtar}")
    ss[f"_son_hareket_{anahtar}"] = simdi
    return son is not None and simdi - son > OTURUM_ZAMAN_ASIMI_SN
