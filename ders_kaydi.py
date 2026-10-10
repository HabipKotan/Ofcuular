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
Günlük (kayit_gunlugu.txt): bu sürecin tüm çıktısı; hata olursa panel son satırları gösterir.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import traceback
import wave
from datetime import datetime
from pathlib import Path

PROJE = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJE))

from core.dosya import guvenli_yaz  # noqa: E402

try:
    from dotenv import load_dotenv

    load_dotenv(PROJE / ".env", override=True)  # .env değişince arayüzü kapatmadan yeni anahtar geçerli olsun
except ImportError:
    pass

VERI = Path(os.getenv("GERCEK_VERI_KLASORU") or PROJE)
DURUM = VERI / "kayit_durumu.json"
DURDUR = VERI / "kayit_durdur.flag"
SES = VERI / "ders.wav"
GUNLUK = VERI / "kayit_gunlugu.txt"   # bu sürecin tüm çıktısı (terminal penceresi kapanınca da okunabilsin)
ORNEKLEME = 16000


class _Cift:
    """Yazılanı hem terminale hem günlük dosyasına gönderir."""

    def __init__(self, asil, dosya):
        self._asil, self._dosya = asil, dosya

    def write(self, metin):
        for hedef in (self._asil, self._dosya):
            try:
                hedef.write(metin)
                hedef.flush()
            except Exception:
                pass
        return len(metin)

    def flush(self):
        for hedef in (self._asil, self._dosya):
            try:
                hedef.flush()
            except Exception:
                pass

    def __getattr__(self, ad):
        return getattr(self._asil, ad)


def gunluk_baslat() -> None:
    """Elle (terminalden) çalıştırıldığında çıktıyı günlüğe de yazar. Panelden başlatıldığında çıktı zaten
    günlük dosyasına yönlendirilmiştir (ui/ders_kontrol.py); o durumda ikinci kez yazılmaz."""
    try:
        if not (sys.stdout and sys.stdout.isatty()):
            return
        dosya = open(GUNLUK, "w", encoding="utf-8", errors="replace")
        dosya.write(f"=== Ders kaydı günlüğü · {datetime.now():%d.%m.%Y %H:%M:%S} ===\n")
        sys.stdout = _Cift(sys.stdout, dosya)
        sys.stderr = _Cift(sys.stderr, dosya)
    except Exception:
        pass  # günlük yazılamıyorsa kayıt yine de çalışsın

_durum_kilidi = threading.Lock()
_durum: dict = {}


# ---------------------------------------------------------------------------
# Durum dosyası (arayüz bunu okur)
# ---------------------------------------------------------------------------
def durum_yaz(**alanlar) -> None:
    with _durum_kilidi:
        _durum.update(alanlar)
        _durum["guncelleme"] = time.time()
        try:  # Windows'ta dosya o an başka programda açıksa birkaç kez yeniden dener
            guvenli_yaz(DURUM, json.dumps(_durum, ensure_ascii=False))
        except OSError as e:  # durum yazılamadı diye kayıt durmasın; bir sonraki yazımda güncellenir
            print(f"(durum dosyası şu an yazılamadı: {e})")


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
    """Alt adımı çalıştırır; çıktısını satır satır terminale + günlüğe aktarır.
    Başarısız olursa hata mesajına alt adımın son satırını (asıl nedeni) ekler."""
    print(f"\n=== {ad} ===")
    surec = subprocess.Popen(komut, cwd=VERI, env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"},
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             encoding="utf-8", errors="replace")
    son_satirlar: list[str] = []
    for satir in surec.stdout:
        print(satir, end="")
        if satir.strip():
            son_satirlar = (son_satirlar + [satir.strip()])[-5:]
    kod = surec.wait()
    if kod != 0:
        neden = son_satirlar[-1] if son_satirlar else f"kod {kod}"
        raise RuntimeError(f"{ad} adımı başarısız oldu: {neden[:300]}")


def en_yeni_odak_csv() -> Path | None:
    adaylar = [d for d in (VERI / "kayitlar").glob("dikkat_*.csv") if not d.name.endswith("_olaylar.csv")]
    return max(adaylar, key=lambda d: d.stat().st_mtime) if adaylar else None


def notlari_uret(odak_yolu: Path | None, konu: str = "", ses: bool = True, odak: bool = True) -> None:
    """ses=False: yalnızca odak özeti (yapay zekâ çağrısı yok). odak=False: notlar odak verisi olmadan."""
    mesaj = "Notlar ve odak analizi hazırlanıyor (Gemini)…" if ses else "Sınıf odağı özeti hazırlanıyor…"
    durum_yaz(durum="isleniyor", mesaj=mesaj, adim=3)
    komut = [sys.executable, str(PROJE / "ses_hatti" / "notlar.py")]
    if konu:
        komut += ["--konu", konu]
    if not ses:
        komut.append("--ses-yok")
    if odak and odak_yolu and odak_yolu.exists():
        komut += ["--odak", str(odak_yolu)]
    else:
        komut.append("--odak-yok")  # önceki derslerin ölçümleri bu derse karışmasın
    calistir_adim("Notlar", komut)
    durum_yaz(durum="bitti", mesaj="Ders işlendi", adim=4, bitis=time.time())
    print("\nBitti. Arayüz yeni dersi gösterecek.")


def sadece_notlar() -> None:
    """Kayıt ve transkript var ama not adımı yarıda kaldıysa: yalnızca notları yeniden üretir.
    Son kaydın seçenekleri (konu, ses / odak açık mı) durum dosyasından okunur."""
    gunluk_baslat()
    DURDUR.unlink(missing_ok=True)
    try:
        onceki = json.loads(DURUM.read_text(encoding="utf-8"))
    except Exception:
        onceki = {}
    konu, odak = onceki.get("konu") or "", onceki.get("odak", True)
    durum_yaz(durum="isleniyor", mesaj="Notlar yeniden hazırlanıyor…", adim=3, pid=os.getpid(),
              konu=konu, ses=True, odak=odak)
    threading.Thread(target=nabiz, daemon=True).start()
    try:
        if not (VERI / "transkript.json").exists():
            raise RuntimeError("transkript.json bulunamadı; dersi yeniden kaydedin.")
        odak_yolu = Path(onceki["odak_csv"]) if onceki.get("odak_csv") else en_yeni_odak_csv()
        notlari_uret(odak_yolu if odak else None, konu, ses=True, odak=odak)
    except (Exception, SystemExit) as e:
        durum_yaz(durum="hata", mesaj=str(e) or e.__class__.__name__)
        print(f"HATA: {e}")
        sys.exit(1)


def durdurulana_kadar_bekle() -> None:
    """Kamera kullanılmayan derslerde: 'Dersi Bitir' (durdurma bayrağı) gelene kadar bekler."""
    print("Kayıt sürüyor (kamera kapalı). Bitirmek için paneldeki 'Dersi Bitir' butonuna basın.")
    while not DURDUR.exists():
        time.sleep(0.3)


def main() -> None:
    p = argparse.ArgumentParser(description="Kamera + mikrofon ile ders kaydı ve otomatik not üretimi")
    p.add_argument("--konu", default="", help="Ders adı / konusu (Whisper ipucu, not başlığı ve kayıt etiketi)")
    p.add_argument("--kamera", type=int, default=0)
    p.add_argument("--ses-yok", action="store_true",
                   help="Mikrofonu açma: ses dinlenmez, metne çevrilmez, not üretilmez (yalnızca sınıf odağı)")
    p.add_argument("--odak-yok", action="store_true",
                   help="Kamerayı açma: sınıf odağı izlenmez (yalnızca ses -> metin -> notlar)")
    p.add_argument("--yuz-goster", action="store_true", help="Önizlemede yüzleri bulanıklaştırma")
    p.add_argument("--sesi-sakla", action="store_true", help="İşlendikten sonra ders.wav'ı silme")
    p.add_argument("--sadece-notlar", action="store_true",
                   help="Kayıt yapmadan, mevcut transkript + odak verisinden notları yeniden üret")
    args = p.parse_args()
    if args.sadece_notlar:
        return sadece_notlar()
    ses_var, odak_var = not args.ses_yok, not args.odak_yok
    if not ses_var and not odak_var:
        p.error("Ses ve odak izlemenin ikisi birden kapatılamaz; en az biri açık olmalı.")

    gunluk_baslat()
    # Eski bir durdurma bayrağı kaldıysa temizle; son saniyelerde (bu süreç açılırken) basılmışsa koru
    try:
        if time.time() - DURDUR.stat().st_mtime > 15:
            DURDUR.unlink(missing_ok=True)
    except OSError:
        pass
    hazirlanan = " ve ".join(x for x, acik in (("Kamera", odak_var), ("mikrofon", ses_var)) if acik)
    durum_yaz(durum="baslatiliyor", mesaj=f"{hazirlanan} hazırlanıyor…", konu=args.konu, ses=ses_var, odak=odak_var,
              pid=os.getpid(), baslangic=None, uyari=None, odak_csv=None, mikrofon=None, ses_seviyesi=None)
    threading.Thread(target=nabiz, daemon=True).start()

    kamera_modulu = None
    try:  # eksik paket (opencv / mediapipe / sounddevice) burada ortaya çıkar: panele açık bir mesaj gitsin
        if odak_var:
            import cv2  # noqa: F401
            import mediapipe  # noqa: F401
            from sensing.focus import classroom_focus as kamera_modulu
        if ses_var:
            import sounddevice  # noqa: F401
    except Exception as e:
        durum_yaz(durum="hata", mesaj=f"Gerekli paket yüklenemedi ({e}). Proje klasöründe şunu çalıştırın: "
                                      "python -m pip install -r requirements.txt")
        print(f"HATA: {e}")
        sys.exit(1)

    global _mikrofon
    mikrofon = Mikrofon()
    if ses_var:
        _mikrofon = mikrofon  # nabız, mikrofon seviyesini panele bildirir
    odak_csv: dict = {}
    ses_kaydedildi = False

    def kayit_basladi(_saat=None):
        """Ölçüm saatinin sıfırlandığı an: ses de aynı anda başlar (ikisi aynı 0. saniyeyi paylaşır)."""
        if ses_var:
            mikrofon.baslat()
        durum_yaz(durum="kayit", mesaj="Ders kaydediliyor", baslangic=time.time(),
                  mikrofon=mikrofon.cihaz_adi if ses_var else None, ses_seviyesi=0 if ses_var else None)

    try:
        # --- 1) Kayıt ---
        if odak_var:
            # Kamera döngüsü burada döner; DURDUR dosyası ya da önizleme penceresinde 'q' ile biter
            kamera_modulu.BASLANGIC_KANCASI = kayit_basladi
            kamera_modulu.DURDUR_DOSYASI = DURDUR
            # Rızalı kişisel odak: yalnızca öğretmenin kaydettiği (rıza veren) öğrenciler tanınır
            takip = None
            kayitli = []
            from core import ogrenci_db
            try:
                kayitli = ogrenci_db.yuz_izleri()
                if kayitli:
                    from sensing.focus.yuz_kimligi import KisiselTakip
                    takip = KisiselTakip(kayitli, kaydet=ogrenci_db.odak_ekle)
                    kamera_modulu.KISI_KANCASI = takip
                    print(f"Rızalı kişisel odak açık: {len(kayitli)} kayıtlı öğrenci")
                    durum_yaz(kayitli_ogrenci=len(kayitli))
            except Exception as e:  # kişisel takip kurulamasa da sınıf ölçümü devam etsin
                print(f"Kişisel odak başlatılamadı (yalnızca sınıf ortalaması ölçülecek): {e}")

            def csv_geldi(yol):
                odak_csv.update(yol=Path(yol))
                durum_yaz(odak_csv=str(yol))
                if takip is not None:
                    takip.kayit = Path(yol).stem  # kişisel ölçümler bu dersin kaydına bağlanır
                    try:  # bu derste aranan kayıtlı öğrenciler: hiç görülmeyen "derste yok" (odak 0) sayılır
                        ogrenci_db.beklenenler_ekle(takip.kayit, [oid for oid, _, _ in kayitli])
                    except Exception as e:
                        print(f"Katılım listesi yazılamadı: {e}")

            kamera_modulu.CSV_KANCASI = csv_geldi
            kamera_argv = ["classroom_focus", "--klasor", str(VERI / "kayitlar"), "--kamera", str(args.kamera),
                           "--grafik-yok", "--olay-sure", "10",
                           "--max-yuz", os.getenv("KAMERA_MAX_YUZ") or "30"]  # öğrenci sayısı için geniş tut
            if args.konu:
                kamera_argv += ["--ders", args.konu]
            if args.yuz_goster:
                kamera_argv.append("--yuz-goster")
            # Önizleme penceresi: varsayılan küçük (tam ekran tahtayı kapatmasın). .env: KAMERA_ONIZLEME=kucuk|normal|kapali
            onizleme = (os.getenv("KAMERA_ONIZLEME") or "kucuk").strip().lower()
            if onizleme == "kapali":
                kamera_argv.append("--onizleme-yok")
            elif onizleme.isdigit():
                kamera_argv += ["--onizleme-genislik", onizleme]
            elif onizleme != "normal":
                kamera_argv += ["--onizleme-genislik", "360"]
            eski_argv = sys.argv
            sys.argv = kamera_argv
            try:
                kamera_modulu.main()
            except (Exception, SystemExit) as e:
                # Kamera açılamadı ya da görüntü modeli hata verdi. Ses açıksa ders KAYBOLMAZ: yalnızca sesle sürer.
                # (Önceden yalnızca "kamera açılamadı" durumu yakalanıyordu; model hatası bütün dersi çökertiyordu.)
                if not ses_var:
                    raise
                kayit_suruyordu = _durum.get("durum") == "kayit"
                print(f"UYARI: görüntü tarafı durdu ({e}). Ders yalnızca SESLE sürüyor.")
                if not isinstance(e, SystemExit):
                    traceback.print_exc()
                if kayit_suruyordu:  # ders ortasında çöktü: o ana kadarki odak ölçümü korunur
                    durum_yaz(uyari="Sınıf odağı ölçümü bir hata nedeniyle durdu. Ses kaydı sürüyor; "
                                    "notlar yine hazırlanacak.")
                else:
                    odak_var = False
                    neden = ("Kamera açılamadı (başka bir program kullanıyor olabilir)" if isinstance(e, SystemExit)
                             else f"Görüntü modeli başlatılamadı ({str(e)[:140]})")
                    durum_yaz(odak=False, uyari=f"{neden}. Ders yalnızca sesle kaydediliyor; notlar yine hazırlanacak.")
                    kayit_basladi()
                if not DURDUR.exists():
                    durdurulana_kadar_bekle()
            else:
                if kamera_modulu.KAMERA_KOPTU and ses_var and not DURDUR.exists():
                    durum_yaz(uyari="Kamera bağlantısı koptu. Ses kaydı sürüyor; odak ölçümü kopana kadarki "
                                    "kısımla sınırlı kalacak.")
                    durdurulana_kadar_bekle()
            finally:
                sys.argv = eski_argv
        else:
            kayit_basladi()
            durdurulana_kadar_bekle()

        if ses_var:
            # --- 2) Sesi kaydet ---
            durum_yaz(durum="isleniyor", mesaj="Ses kaydı kaydediliyor…", adim=1)
            sure = mikrofon.durdur_ve_kaydet(SES)
            ses_kaydedildi = True
            print(f"Ses kaydedildi: {SES} ({sure:.0f} sn)")
            if sure < 5:
                raise RuntimeError("Ders çok kısa ya da mikrofon ses almadı (5 saniyeden kısa kayıt).")

            # --- 3) Ses -> metin (öğretmenin sesi ayrılır, yalnızca o çevrilir) ---
            durum_yaz(mesaj="Öğretmenin sesi ayrılıyor ve metne çevriliyor (Whisper)…", adim=2)
            komut = [sys.executable, str(PROJE / "ses_hatti" / "transkript.py"), str(SES)]
            if args.konu:
                komut += ["--konu", args.konu]
            calistir_adim("Transkript", komut)
            transkript = json.loads((VERI / "transkript.json").read_text(encoding="utf-8"))
            if not transkript:
                raise RuntimeError("Kayıtta konuşma algılanamadı. Mikrofonu kontrol edip tekrar deneyin.")
            if not args.sesi_sakla:
                SES.unlink(missing_ok=True)  # KVKK: ses metne çevrildi, ham ses silinir
        elif not odak_csv.get("yol"):
            raise RuntimeError("Sınıf odağı ölçülemedi (kamera kaydı oluşmadı).")

        # --- 4) Notlar (ses varsa metin + odak; yoksa yalnızca odak özeti) ---
        notlari_uret(odak_csv.get("yol"), args.konu, ses=ses_var, odak=odak_var)
    except (Exception, SystemExit) as e:  # kamera açılamazsa classroom_focus sys.exit() çağırır
        if ses_var and not ses_kaydedildi and mikrofon.veri_var():
            try:  # kayıt ortasında hata olduysa ses kaybolmasın; elle tekrar işlenebilir
                mikrofon.durdur_ve_kaydet(VERI / f"ders_yedek_{datetime.now():%H%M%S}.wav")
            except Exception:
                pass
        durum_yaz(durum="hata", mesaj=str(e) or e.__class__.__name__)
        print(f"HATA: {e}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        DURDUR.unlink(missing_ok=True)


def _guvenli_calistir() -> None:
    """Beklenmeyen her hatada (içe aktarma hatası, Ctrl+C, kapanan pencere…) durumu 'hata' yap ve
    ayrıntıyı günlüğe yaz; böylece panel "yanıt vermiyor"da kalmaz, sebebi gösterir."""

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
