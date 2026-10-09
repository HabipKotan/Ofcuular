"""
Ders Kaydı: kamera + mikrofon aynı anda, bitince otomatik işleme
===============================================================
Arayüzdeki "🔴 Dersi Başlat" butonu bu betiği arka planda çalıştırır;
"⏹ Dersi Bitir" butonu DURDUR dosyasını oluşturur. Elle de çalıştırılabilir:

    python ders_kaydi.py --konu "Matematik: kesirler"
    (durdurmak için kamera penceresinde 'q' ya da arayüzden "Dersi Bitir")

Akış:
  1) Kamera (sensing/focus/classroom_focus.py) başlar; ölçüm saati sıfırlandığı AN mikrofon da başlar
     -> ses ve odak aynı 0. saniyeyi paylaşır.
  2) Durdurulunca: ders.wav kaydedilir, kamera ölçümleri kayitlar/ altına yazılmış olur.
  3) ses_hatti/transkript.py  -> transkript.json  (ses dosyası başarıyla çevrilince silinir)
  4) ses_hatti/notlar.py      -> notlar.json      (Gemini + odak eşleştirmesi)
  5) Durum dosyası "bitti" olur; arayüz yeni dersi otomatik gösterir.

Durum dosyası (kayit_durumu.json): {"durum": "baslatiliyor|kayit|isleniyor|bitti|hata", "mesaj", ...}
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import wave
from datetime import datetime
from pathlib import Path

PROJE = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJE))

try:
    from dotenv import load_dotenv

    load_dotenv(PROJE / ".env")
except ImportError:
    pass

VERI = Path(os.getenv("GERCEK_VERI_KLASORU") or PROJE)
DURUM = VERI / "kayit_durumu.json"
DURDUR = VERI / "kayit_durdur.flag"
SES = VERI / "ders.wav"
ORNEKLEME = 16000

_durum_kilidi = threading.Lock()
_durum: dict = {}


# ---------------------------------------------------------------------------
# Durum dosyası (arayüz bunu okur)
# ---------------------------------------------------------------------------
def durum_yaz(**alanlar) -> None:
    with _durum_kilidi:
        _durum.update(alanlar)
        _durum["guncelleme"] = time.time()
        gecici = DURUM.with_suffix(".tmp")
        gecici.write_text(json.dumps(_durum, ensure_ascii=False), encoding="utf-8")
        os.replace(gecici, DURUM)  # yarım okunmasın diye atomik yazım


def nabiz() -> None:
    """Süreç yaşadığı sürece birkaç saniyede bir 'hâlâ çalışıyorum' der (ve mikrofon seviyesini bildirir)."""
    while True:
        time.sleep(2)
        try:
            ek = {}
            if _mikrofon is not None and _mikrofon.calisiyor:
                ek = {"ses_seviyesi": round(_mikrofon.seviye_al(), 4), "mikrofon": _mikrofon.cihaz_adi}
            durum_yaz(**ek)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Mikrofon
# ---------------------------------------------------------------------------
class Mikrofon:
    """Varsayılan mikrofonu KENDİ doğal örnekleme hızında kaydeder (zorla 16 kHz istemek bazı
    Windows sürücülerinde sesi bozabiliyor). Whisper tarafı kaydı 16 kHz'e kendisi çevirir."""

    def __init__(self):
        self._parcalar: list[bytes] = []
        self._kilit = threading.Lock()
        self._akis = None
        self.oran = ORNEKLEME
        self.cihaz_adi = "?"
        self.calisiyor = False
        self._tepe = 0.0

    def baslat(self) -> None:
        import numpy as np
        import sounddevice as sd

        # .env içinde MIKROFON=<numara> verilmişse o cihaz (numaralar: python mikrofon_testi.py)
        secim = (os.getenv("MIKROFON") or "").strip()
        self.cihaz_no = int(secim) if secim.isdigit() else None
        try:
            cihaz = sd.query_devices(self.cihaz_no) if self.cihaz_no is not None else sd.query_devices(kind="input")
            self.cihaz_adi = str(cihaz.get("name", "?"))
            self.oran = int(cihaz.get("default_samplerate") or ORNEKLEME)
        except Exception as e:
            raise RuntimeError(f"Mikrofon bulunamadı ({secim or 'varsayılan'}): {e}")
        print(f"Mikrofon: {self.cihaz_adi} ({self.oran} Hz)")

        def geri_cagri(veri, kare_sayisi, zaman, durum):
            b = bytes(veri)
            with self._kilit:
                self._parcalar.append(b)
            a = np.frombuffer(b, dtype=np.int16).astype(np.float32)
            if a.size:  # ses seviyesi (RMS, 0-1)
                self._tepe = max(self._tepe, float(np.sqrt(np.mean(a * a))) / 32768.0)

        self._akis = sd.RawInputStream(samplerate=self.oran, channels=1, dtype="int16", callback=geri_cagri,
                                       device=self.cihaz_no)
        self._akis.start()
        self.calisiyor = True

    def seviye_al(self) -> float:
        """Son okumadan bu yana en yüksek ses seviyesi."""
        t, self._tepe = self._tepe, 0.0
        return t

    def veri_var(self) -> bool:
        return bool(self._parcalar)

    def durdur_ve_kaydet(self, yol: Path) -> float:
        if self._akis is not None and self.calisiyor:
            self._akis.stop()
            self._akis.close()
        self.calisiyor = False
        with self._kilit:
            veri = b"".join(self._parcalar)
        with wave.open(str(yol), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.oran)
            w.writeframes(veri)
        return len(veri) / 2 / self.oran  # saniye


_mikrofon: Mikrofon | None = None


# ---------------------------------------------------------------------------
# İşleme adımları
# ---------------------------------------------------------------------------
def calistir_adim(ad: str, komut: list[str]) -> None:
    print(f"\n=== {ad} ===")
    sonuc = subprocess.run(komut, cwd=VERI, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    if sonuc.returncode != 0:
        raise RuntimeError(f"{ad} başarısız oldu (kod {sonuc.returncode}). Ayrıntı terminalde.")


def en_yeni_odak_csv() -> Path | None:
    adaylar = [d for d in (VERI / "kayitlar").glob("dikkat_*.csv") if not d.name.endswith("_olaylar.csv")]
    return max(adaylar, key=lambda d: d.stat().st_mtime) if adaylar else None


def notlari_uret(odak_yolu: Path | None) -> None:
    durum_yaz(durum="isleniyor", mesaj="Notlar ve odak analizi hazırlanıyor (Gemini)…", adim=3)
    komut = [sys.executable, str(PROJE / "ses_hatti" / "notlar.py")]
    if odak_yolu and odak_yolu.exists():
        komut += ["--odak", str(odak_yolu)]
    calistir_adim("Notlar", komut)
    durum_yaz(durum="bitti", mesaj="Ders işlendi", adim=4, bitis=time.time())
    print("\nBitti. Arayüz yeni dersi gösterecek.")


def sadece_notlar() -> None:
    """Kayıt ve transkript var ama not adımı yarıda kaldıysa: yalnızca notları yeniden üretir."""
    DURDUR.unlink(missing_ok=True)
    durum_yaz(durum="isleniyor", mesaj="Notlar yeniden hazırlanıyor…", adim=3, pid=os.getpid())
    threading.Thread(target=nabiz, daemon=True).start()
    try:
        if not (VERI / "transkript.json").exists():
            raise RuntimeError("transkript.json bulunamadı; dersi yeniden kaydedin.")
        notlari_uret(en_yeni_odak_csv())
    except (Exception, SystemExit) as e:
        durum_yaz(durum="hata", mesaj=str(e) or e.__class__.__name__)
        print(f"HATA: {e}")
        sys.exit(1)


def main() -> None:
    p = argparse.ArgumentParser(description="Kamera + mikrofon ile ders kaydı ve otomatik not üretimi")
    p.add_argument("--konu", default="", help="Ders konusu (Whisper ipucu ve kayıt etiketi)")
    p.add_argument("--kamera", type=int, default=0)
    p.add_argument("--yuz-goster", action="store_true", help="Önizlemede yüzleri bulanıklaştırma")
    p.add_argument("--sesi-sakla", action="store_true", help="İşlendikten sonra ders.wav'ı silme")
    p.add_argument("--sadece-notlar", action="store_true",
                   help="Kayıt yapmadan, mevcut transkript + odak verisinden notları yeniden üret")
    args = p.parse_args()
    if args.sadece_notlar:
        return sadece_notlar()

    DURDUR.unlink(missing_ok=True)
    durum_yaz(durum="baslatiliyor", mesaj="Kamera ve mikrofon hazırlanıyor…", konu=args.konu,
              pid=os.getpid(), baslangic=None)
    threading.Thread(target=nabiz, daemon=True).start()

    from sensing.focus import classroom_focus as kamera_modulu

    global _mikrofon
    mikrofon = _mikrofon = Mikrofon()
    odak_csv: dict = {}
    ses_kaydedildi = False

    def kamera_basladi(_saat):
        mikrofon.baslat()  # ölçüm saatiyle aynı anda
        durum_yaz(durum="kayit", mesaj="Ders kaydediliyor", baslangic=time.time(),
                  mikrofon=mikrofon.cihaz_adi, ses_seviyesi=0)

    kamera_modulu.BASLANGIC_KANCASI = kamera_basladi
    kamera_modulu.DURDUR_DOSYASI = DURDUR
    kamera_modulu.CSV_KANCASI = lambda yol: odak_csv.update(yol=Path(yol))

    try:
        # --- 1) Kayıt (kamera döngüsü burada döner; DURDUR dosyası ya da 'q' ile biter) ---
        kamera_argv = ["classroom_focus", "--klasor", str(VERI / "kayitlar"), "--kamera", str(args.kamera),
                       "--grafik-yok", "--olay-sure", "10"]
        if args.konu:
            kamera_argv += ["--ders", args.konu]
        if args.yuz_goster:
            kamera_argv.append("--yuz-goster")
        eski_argv = sys.argv
        sys.argv = kamera_argv
        try:
            kamera_modulu.main()
        finally:
            sys.argv = eski_argv

        # --- 2) Sesi kaydet ---
        durum_yaz(durum="isleniyor", mesaj="Ses kaydı kaydediliyor…", adim=1)
        sure = mikrofon.durdur_ve_kaydet(SES)
        ses_kaydedildi = True
        print(f"Ses kaydedildi: {SES} ({sure:.0f} sn)")
        if sure < 5:
            raise RuntimeError("Ders çok kısa ya da mikrofon ses almadı (5 saniyeden kısa kayıt).")

        # --- 3) Ses -> metin ---
        durum_yaz(mesaj="Ses metne çevriliyor (Whisper)…", adim=2)
        komut = [sys.executable, str(PROJE / "ses_hatti" / "transkript.py"), str(SES)]
        if args.konu:
            komut += ["--konu", args.konu]
        calistir_adim("Transkript", komut)
        transkript = json.loads((VERI / "transkript.json").read_text(encoding="utf-8"))
        if not transkript:
            raise RuntimeError("Kayıtta konuşma algılanamadı. Mikrofonu kontrol edip tekrar deneyin.")
        if not args.sesi_sakla:
            SES.unlink(missing_ok=True)  # KVKK: ses metne çevrildi, ham ses silinir

        # --- 4) Metin + odak -> notlar ---
        notlari_uret(odak_csv.get("yol"))
    except (Exception, SystemExit) as e:  # kamera açılamazsa classroom_focus sys.exit() çağırır
        if not ses_kaydedildi and mikrofon.veri_var():
            try:  # kayıt ortasında hata olduysa ses kaybolmasın; elle tekrar işlenebilir
                mikrofon.durdur_ve_kaydet(VERI / f"ders_yedek_{datetime.now():%H%M%S}.wav")
            except Exception:
                pass
        durum_yaz(durum="hata", mesaj=str(e) or e.__class__.__name__)
        print(f"HATA: {e}")
        sys.exit(1)
    finally:
        DURDUR.unlink(missing_ok=True)


def _guvenli_calistir() -> None:
    """Beklenmeyen her hatada (içe aktarma hatası, Ctrl+C, kapanan pencere…) durumu 'hata' yap ve
    ayrıntıyı günlüğe yaz; böylece panel "yanıt vermiyor"da kalmaz, sebebi gösterir."""
    import traceback

    try:
        main()
    except SystemExit:
        raise
    except BaseException as e:  # KeyboardInterrupt dahil
        traceback.print_exc()
        sys.stdout.flush()
        mesaj = "Kayıt elle durduruldu (Ctrl+C ya da pencere kapatıldı)." if isinstance(e, KeyboardInterrupt) \
            else f"{e.__class__.__name__}: {e}"
        try:
            if _durum.get("durum") not in ("hata", "bitti"):
                durum_yaz(durum="hata", mesaj=mesaj)
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    _guvenli_calistir()
