"""
Sinif Dikkat Olcer - goruntu isleme modulu (hackathon prototipi)

Kameradan gelen goruntuyu CIHAZ UZERINDE isler ve yalnizca sinif geneline ait
anonim bir "dikkat skoru" (0-100) uretir.

Gizlilik tasarimi (KVKK):
  - Hicbir kare diske yazilmaz, aga gonderilmez; her kare islendikten sonra atilir.
  - Yuz tanima / kimlik eslestirme YOKTUR. Kareler arasi kisi takibi de yapilmaz.
  - Diske yazilan tek sey: zaman damgasi + sinif geneli oranlar.
  - Onizleme penceresi varsayilan olarak yuzleri bulaniklastirir.

Ozellikler:
  - Sinif skoru + 30 sn'lik yumusatilmis skor
  - Skorun nedeni: yana bakan / basi egik / gozu kapali / esneyen oranlari
  - Not alma toleransi: basi egik ama gozu acik olan tam ceza almaz
  - Dikkat dususu olaylari (skor uzun sure dusuk kalirsa) + canli uyari
  - Kor nokta: gorulen yuz sayisi aniden duserse o aralik "guvenilmez" sayilir
  - Ders etiketi: her ders ayri dosyalara yazilir
  - Kapanista saate gore ozet tablo, olay listesi, grafik ve JSON ozet

Kurulum:
    pip install mediapipe opencv-python numpy matplotlib

Calistirma:
    python dikkat_olcer.py --ders "Matematik 9-A" --kalibrasyon 5
    python dikkat_olcer.py --onizleme-yok        # penceresiz (Raspberry Pi vb.)
    python dikkat_olcer.py --olay-sure 10        # demo icin: 10 sn dusukluk olay sayilsin

Cikis: onizleme penceresinde 'q' ya da terminalde Ctrl+C.

Onizlemede her yuzun ustundeki harfler: Y=yana bakiyor, E=basi egik,
K=gozu kapali, A=agzi acik (esneme). Ilk calistirmada basinizi one egin:
"E" cikmiyorsa --pitch-ters ile calistirin.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import sys
import time
import urllib.request
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)
MODEL_DOSYA = Path(__file__).with_name("face_landmarker.task")

NEDEN_ADLARI = {"yana": "yana bakma", "egik": "bas egik", "kapali": "goz kapali / yorgunluk"}

# Ders kaydi entegrasyonu (ders_kaydi.py tarafindan doldurulur; tek basina calisirken None kalir)
#   BASLANGIC_KANCASI(monotonic_saat): olcum saati sifirlandigi an cagrilir -> mikrofon ayni anda baslar
#   DURDUR_DOSYASI: bu dosya olusunca dongu 'q'ya basilmis gibi duzgunce biter
#   CSV_KANCASI(csv_yolu): olcum dosyasinin yolu belli olunca cagrilir
BASLANGIC_KANCASI = None
DURDUR_DOSYASI: Path | None = None
CSV_KANCASI = None


# --------------------------------------------------------------------------
# Tek yuz: aci ve skor hesabi (saf fonksiyonlar)
# --------------------------------------------------------------------------

@dataclass
class Esikler:
    yaw_tam: float = 20.0      # bu aciya kadar (derece) "tahtaya bakiyor" sayilir
    yaw_sifir: float = 50.0    # bu acidan sonra bas yonu puani 0
    pitch_tam: float = 15.0
    pitch_sifir: float = 40.0
    goz_kapali_bas: float = 0.45   # eyeBlink bu degerden sonra ceza baslar
    goz_kapali_tam: float = 0.80   # bu degerde goz tamamen kapali sayilir
    dikkatsiz_esik: float = 50.0   # kisi skoru bunun altindaysa "dikkati dagilmis"
    # neden siniflari
    yana_esik: float = 30.0    # |yaw| bunu asarsa "yana bakiyor"
    egik_esik: float = 20.0    # asagi dogru pitch bunu asarsa "basi egik"
    kapali_esik: float = 0.70  # eyeBlink bunu asarsa "gozu kapali"
    esneme_esik: float = 0.60  # jawOpen bunu asarsa "esniyor"
    not_tabani: float = 0.60   # basi egik + gozu acik olan en az bu kadar puan alir


@dataclass
class YuzOlcum:
    skor: float
    yana: bool
    egik: bool
    kapali: bool
    esniyor: bool

    @property
    def harfler(self) -> str:
        return "".join(h for h, v in (("Y", self.yana), ("E", self.egik),
                                      ("K", self.kapali), ("A", self.esniyor)) if v)


def _rampa(deger: float, tam: float, sifir: float) -> float:
    """deger<=tam -> 1.0, deger>=sifir -> 0.0, arasi dogrusal."""
    if deger <= tam:
        return 1.0
    if deger >= sifir:
        return 0.0
    return 1.0 - (deger - tam) / (sifir - tam)


def bas_acilari(matris: np.ndarray) -> tuple[float, float]:
    """4x4 yuz donusum matrisinden (yaw, pitch) derece cinsinden.

    yaw: saga/sola donme. pitch: pozitif = bas ONE/ASAGI egik.
    0,0 = kameraya dogru bakis.
    """
    r = np.asarray(matris, dtype=float)[:3, :3]
    r = r / np.linalg.norm(r, axis=0, keepdims=True)  # olcek icerebilir
    ileri = r[:, 2]  # yuzun baktigi yon (kamera koordinatlarinda, y yukari)
    yaw = math.degrees(math.atan2(ileri[0], ileri[2]))
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, -ileri[1]))))
    return yaw, pitch


def kisi_skoru(yaw: float, pitch: float, goz_kapalilik: float, e: Esikler) -> float:
    """Bas yonu (tahtaya donuk mu) x goz acikligi carpimi, 0-100."""
    bas = _rampa(abs(yaw), e.yaw_tam, e.yaw_sifir) * _rampa(abs(pitch), e.pitch_tam, e.pitch_sifir)
    goz = _rampa(goz_kapalilik, e.goz_kapali_bas, e.goz_kapali_tam)
    return 100.0 * bas * goz


def yuz_olc(yaw: float, pitch: float, goz: float, cene: float, e: Esikler,
            not_toleransi: bool = True) -> YuzOlcum:
    """Tek yuz icin skor + neden siniflari."""
    skor = kisi_skoru(yaw, pitch, goz, e)
    yana = abs(yaw) > e.yana_esik
    egik = pitch > e.egik_esik
    kapali = goz >= e.kapali_esik
    esniyor = cene >= e.esneme_esik
    # Not alma toleransi: basi one egik ama gozu acik -> muhtemelen deftere bakiyor.
    # (Sira altindaki telefondan ayirt edilemez; bu yuzden tam puan degil, taban puan.)
    if not_toleransi and pitch > e.pitch_tam and not kapali:
        taban = 100.0 * e.not_tabani * _rampa(abs(yaw), e.yaw_tam, e.yaw_sifir)
        skor = max(skor, taban)
    return YuzOlcum(skor, yana, egik, kapali, esniyor)


# --------------------------------------------------------------------------
# Donem (ornegin 5 sn) toplama - kisi bazli hicbir sey saklanmaz
# --------------------------------------------------------------------------

class DonemToplayici:
    def __init__(self, esikler: Esikler):
        self.e = esikler
        self.sifirla()

    def sifirla(self) -> None:
        self._kare = 0
        self._yuz = 0
        self._skor = 0.0
        self._say = {"dikkatsiz": 0, "yana": 0, "egik": 0, "kapali": 0, "esneme": 0}

    def ekle(self, yuzler: list[YuzOlcum]) -> None:
        self._kare += 1
        self._yuz += len(yuzler)
        for y in yuzler:
            self._skor += y.skor
            self._say["dikkatsiz"] += y.skor < self.e.dikkatsiz_esik
            self._say["yana"] += y.yana
            self._say["egik"] += y.egik
            self._say["kapali"] += y.kapali
            self._say["esneme"] += y.esniyor

    def ozet(self) -> dict | None:
        """Donem ozeti. Hic kare yoksa None; yuz yoksa skor None."""
        if self._kare == 0:
            return None
        ozet = {"ortalama_yuz": round(self._yuz / self._kare, 1)}
        if self._yuz == 0:
            ozet.update(skor=None, dikkatsiz=None, yana=None, egik=None, kapali=None, esneme=None)
        else:
            ozet["skor"] = round(self._skor / self._yuz, 1)
            for ad, n in self._say.items():
                ozet[ad] = round(n / self._yuz, 2)
        return ozet


# --------------------------------------------------------------------------
# Oturum mantigi: yumusatma, kor nokta, dusus olaylari
# --------------------------------------------------------------------------

class Yumusatici:
    """Son n degerin kayan ortalamasi."""

    def __init__(self, n: int):
        self._d: deque[float] = deque(maxlen=max(1, n))

    def ekle(self, deger: float) -> float:
        self._d.append(deger)
        return round(sum(self._d) / len(self._d), 1)


class KorNokta:
    """Gorulen yuz sayisi aniden duserse olcumu guvenilmez sayar.

    Referans: son guvenilir donemlerin yuz sayisi medyani. Dusukluk uzun surerse
    (ornegin sinif gercekten bosaldi) yeni seviye normal kabul edilir.
    """

    def __init__(self, oran: float = 0.6, pencere: int = 12, kabul_donem: int = 12):
        self.oran = oran
        self.kabul = max(1, kabul_donem)
        self._gecmis: deque[float] = deque(maxlen=pencere)
        self._kotu_seri = 0

    def guvenilir(self, yuz: float) -> bool:
        ref = statistics.median(self._gecmis) if len(self._gecmis) >= 3 else None
        kotu = yuz <= 0 or (ref is not None and ref >= 1 and yuz < self.oran * ref)
        if not kotu:
            self._kotu_seri = 0
            self._gecmis.append(yuz)
            return True
        self._kotu_seri += 1
        if yuz > 0 and self._kotu_seri >= self.kabul:
            self._gecmis.clear()
            self._gecmis.append(yuz)
            self._kotu_seri = 0
            return True
        return False


@dataclass
class Olay:
    baslangic: datetime
    bitis: datetime
    sure_sn: int
    ortalama_skor: float
    en_dusuk_skor: float
    neden: str


class OlayDedektoru:
    """Skor esigin altinda en az min_sure saniye kalirsa bir 'dikkat dususu' olayi.

    Tek donemlik toparlanma (tolerans) olayi bolmez.
    """

    def __init__(self, esik: float, min_sure: float, tolerans: int = 1):
        self.esik, self.min_sure, self.tolerans = esik, min_sure, tolerans
        self._sifirla()

    def _sifirla(self) -> None:
        self._bas: datetime | None = None
        self._son: datetime | None = None
        self._skorlar: list[float] = []
        self._neden = {"yana": 0.0, "egik": 0.0, "kapali": 0.0}
        self._ust = 0

    def aktif_sure(self) -> float:
        if self._bas is None:
            return 0.0
        return (self._son - self._bas).total_seconds()

    def besle(self, bas: datetime, bit: datetime, skor: float | None, ozet: dict | None) -> Olay | None:
        """Bir donemi isler; kapanan bir olay varsa onu doner."""
        if skor is not None and skor < self.esik:
            if self._bas is None:
                self._bas = bas
            self._son = bit
            self._ust = 0
            self._skorlar.append(skor)
            for k in self._neden:
                self._neden[k] += (ozet or {}).get(k) or 0.0
            return None
        if self._bas is None:
            return None
        self._ust += 1
        if self._ust > self.tolerans:
            return self.kapat()
        return None

    def kapat(self) -> Olay | None:
        """Acik olayi sonlandirir; yeterince uzun surduyse Olay doner."""
        olay = None
        if self._bas is not None and self.aktif_sure() >= self.min_sure:
            n = len(self._skorlar)
            ad, deger = max(self._neden.items(), key=lambda kv: kv[1])
            neden = NEDEN_ADLARI[ad] if deger / n >= 0.15 else "belirsiz"
            olay = Olay(self._bas, self._son, round(self.aktif_sure()),
                        round(sum(self._skorlar) / n, 1), min(self._skorlar), neden)
        self._sifirla()
        return olay


@dataclass
class Kayit:
    """Bir donemin sinif geneli sonucu (CSV'nin bir satiri)."""
    baslangic: datetime
    bitis: datetime
    skor: float | None
    yumusak: float | None
    ortalama_yuz: float
    dikkatsiz: float | None
    yana: float | None
    egik: float | None
    kapali: float | None
    esneme: float | None
    guvenilir: bool


class Oturum:
    """Donem ozetlerini alir; yumusatma, kor nokta ve olay tespitini yurutur."""

    def __init__(self, aralik: float, olay_esik: float = 50.0, olay_sure: float = 30.0,
                 yumusatma_sn: float = 30.0):
        self.kayitlar: list[Kayit] = []
        self.olaylar: list[Olay] = []
        self._yumusatici = Yumusatici(round(yumusatma_sn / aralik))
        self._kor = KorNokta(kabul_donem=round(60 / aralik))
        self._dedektor = OlayDedektoru(olay_esik, olay_sure)
        self._olay_sure = olay_sure

    @property
    def uyari_suresi(self) -> float:
        """Su an suren dusukluk uyari esigini astiysa suresi (sn), yoksa 0."""
        s = self._dedektor.aktif_sure()
        return s if s >= self._olay_sure else 0.0

    def donem_ekle(self, bas: datetime, bit: datetime, ozet: dict) -> tuple[Kayit, Olay | None]:
        guvenilir = self._kor.guvenilir(ozet["ortalama_yuz"]) and ozet["skor"] is not None
        yumusak = self._yumusatici.ekle(ozet["skor"]) if guvenilir else None
        kayit = Kayit(bas, bit, ozet["skor"], yumusak, ozet["ortalama_yuz"], ozet["dikkatsiz"],
                      ozet["yana"], ozet["egik"], ozet["kapali"], ozet["esneme"], guvenilir)
        self.kayitlar.append(kayit)
        olay = self._dedektor.besle(bas, bit, ozet["skor"] if guvenilir else None, ozet)
        if olay:
            self.olaylar.append(olay)
        return kayit, olay

    def bitir(self) -> Olay | None:
        olay = self._dedektor.kapat()
        if olay:
            self.olaylar.append(olay)
        return olay


# --------------------------------------------------------------------------
# Kapanis ozeti: tablo, olaylar, JSON, grafik
# --------------------------------------------------------------------------

def saatlik_ozet(kayitlar: list[tuple[datetime, float]]) -> list[tuple[str, float]]:
    """(zaman, skor) listesini saat etiketine gore gruplayip ortalamasini alir.

    3 dakikadan uzun oturumlarda dakika dakika (SS:DD), kisa oturumlarda
    her olcum araligi ayri satir (SS:DD:SN).
    """
    if not kayitlar:
        return []
    sure = (kayitlar[-1][0] - kayitlar[0][0]).total_seconds()
    bicim = "%H:%M" if sure >= 180 else "%H:%M:%S"
    gruplar: dict[str, list[float]] = {}
    for zaman, skor in kayitlar:
        gruplar.setdefault(zaman.strftime(bicim), []).append(skor)
    return [(etiket, round(sum(v) / len(v), 1)) for etiket, v in gruplar.items()]


def oturum_ozeti(oturum: Oturum, ders: str) -> dict:
    """Panelin / ses modulunun okuyacagi sayisal ozet."""
    iyi = [k for k in oturum.kayitlar if k.guvenilir]
    ozet: dict = {
        "ders": ders,
        "donem_sayisi": len(oturum.kayitlar),
        "guvenilmez_donem": len(oturum.kayitlar) - len(iyi),
        "olaylar": [
            {**asdict(o), "baslangic": o.baslangic.isoformat(timespec="seconds"),
             "bitis": o.bitis.isoformat(timespec="seconds")} for o in oturum.olaylar
        ],
    }
    if not iyi:
        return ozet

    def ort(alan: str) -> float:
        return round(sum(getattr(k, alan) for k in iyi) / len(iyi), 2)

    satirlar = saatlik_ozet([(k.bitis, k.skor) for k in iyi])
    esneme_tepe = max(iyi, key=lambda k: k.esneme)
    ozet.update(
        baslangic=oturum.kayitlar[0].baslangic.isoformat(timespec="seconds"),
        bitis=oturum.kayitlar[-1].bitis.isoformat(timespec="seconds"),
        genel_ortalama=round(sum(k.skor for k in iyi) / len(iyi), 1),
        saate_gore=[{"saat": s, "skor": v} for s, v in satirlar],
        en_dusuk=dict(zip(("saat", "skor"), min(satirlar, key=lambda x: x[1]))),
        en_yuksek=dict(zip(("saat", "skor"), max(satirlar, key=lambda x: x[1]))),
        neden_oranlari={"yana": ort("yana"), "egik": ort("egik"), "kapali": ort("kapali")},
        esneme={"ortalama": ort("esneme"), "tepe_saat": f"{esneme_tepe.bitis:%H:%M:%S}",
                "tepe_oran": esneme_tepe.esneme},
    )
    return ozet


def ozet_yazdir(ozet: dict) -> None:
    c = "=" * 58
    print(f"\n{c}\n OTURUM OZETI" + (f" - {ozet['ders']}" if ozet["ders"] else "") + f"\n{c}")
    if "genel_ortalama" not in ozet:
        print(" Bu oturumda guvenilir olcum yok (yuz gorulmedi ya da cok kisa surdu).")
        return
    print(" Saate gore dikkat ortalamasi:")
    for s in ozet["saate_gore"]:
        print(f"   {s['saat']:<8} {s['skor']:5.1f}  {'#' * round(s['skor'] / 5)}")
    print("-" * 58)
    print(f" Baslangic - bitis : {ozet['baslangic'][11:]} - {ozet['bitis'][11:]}")
    print(f" Genel ortalama    : {ozet['genel_ortalama']}")
    print(f" En dusuk          : {ozet['en_dusuk']['saat']}  ({ozet['en_dusuk']['skor']})")
    print(f" En yuksek         : {ozet['en_yuksek']['saat']}  ({ozet['en_yuksek']['skor']})")
    n = ozet["neden_oranlari"]
    print(f" Ortalama oranlar  : yana bakan %{n['yana'] * 100:.0f} | basi egik %{n['egik'] * 100:.0f}"
          f" | gozu kapali %{n['kapali'] * 100:.0f}")
    e = ozet["esneme"]
    print(f" Esneme            : ortalama %{e['ortalama'] * 100:.0f}"
          + (f", en yogun {e['tepe_saat']} (%{e['tepe_oran'] * 100:.0f})" if e["tepe_oran"] > 0 else ""))
    if ozet["guvenilmez_donem"]:
        print(f" Guvenilmez donem  : {ozet['guvenilmez_donem']} / {ozet['donem_sayisi']}"
              " (yuz sayisi dustu; ortalamalara katilmadi)")
    print("-" * 58)
    if ozet["olaylar"]:
        print(f" Dikkat dususu olaylari ({len(ozet['olaylar'])}):")
        for o in ozet["olaylar"]:
            print(f"   {o['baslangic'][11:]} - {o['bitis'][11:]}  {o['sure_sn']:>4} sn  "
                  f"ort {o['ortalama_skor']:.0f}, en dusuk {o['en_dusuk_skor']:.0f}  -> {o['neden']}")
    else:
        print(" Dikkat dususu olayi yok.")
    print(c)


def grafik_ciz(oturum: Oturum, ozet: dict, dosya: Path) -> None:
    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from matplotlib.patches import Patch
    except ImportError:
        print(" (Grafik icin: pip install matplotlib)")
        return
    if "genel_ortalama" not in ozet:
        return
    murekkep, soluk, zemin = "#0b0b0b", "#898781", "#fcfcfb"
    nan = float("nan")
    x = [k.bitis for k in oturum.kayitlar]
    ham = [k.skor if k.guvenilir else nan for k in oturum.kayitlar]
    yumusak = [k.yumusak if k.guvenilir else nan for k in oturum.kayitlar]

    fig, ax = plt.subplots(figsize=(10, 4.2), facecolor=zemin)
    ax.set_facecolor(zemin)
    # guvenilmez araliklar (gri) ve dusus olaylari (kirmizi) arka planda
    for k in oturum.kayitlar:
        if not k.guvenilir:
            ax.axvspan(k.baslangic, k.bitis, color=soluk, alpha=0.25, linewidth=0)
    for o in oturum.olaylar:
        ax.axvspan(o.baslangic, o.bitis, color="#d03b3b", alpha=0.14, linewidth=0)
        ax.text(o.baslangic + (o.bitis - o.baslangic) / 2, 97, "dusus", ha="center", va="top",
                fontsize=8, color=murekkep)
    ax.plot(x, ham, linewidth=1, color="#9ec5f4", label="Ham skor")
    ax.plot(x, yumusak, linewidth=2, color="#2a78d6", label="Yumusatilmis skor")
    genel = ozet["genel_ortalama"]
    ax.axhline(genel, linestyle="--", linewidth=1, color=soluk)
    ax.annotate(f"ort. {genel:.0f}", xy=(1, genel), xycoords=("axes fraction", "data"),
                xytext=(-4, 3), textcoords="offset points", ha="right", fontsize=9, color="#52514e")

    ax.set_ylim(0, 100)
    ax.set_ylabel("Sinif dikkat skoru", color="#52514e")
    ax.set_title("Ders boyunca sinif dikkat skoru" + (f" - {ozet['ders']}" if ozet["ders"] else ""),
                 color=murekkep, loc="left")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.grid(axis="y", color=soluk, alpha=0.25, linewidth=0.6)
    ax.tick_params(colors=soluk, labelcolor="#52514e")
    for kenar in ("top", "right", "left"):
        ax.spines[kenar].set_visible(False)
    ax.spines["bottom"].set_color(soluk)
    tutamaclar, _ = ax.get_legend_handles_labels()
    if oturum.olaylar:
        tutamaclar.append(Patch(color="#d03b3b", alpha=0.14, label="Dikkat dususu"))
    if ozet["guvenilmez_donem"]:
        tutamaclar.append(Patch(color=soluk, alpha=0.25, label="Guvenilmez olcum"))
    ax.legend(handles=tutamaclar, loc="lower left", frameon=False, fontsize=9, ncol=4,
              labelcolor="#52514e")
    fig.tight_layout()
    fig.savefig(dosya, dpi=150)
    print(f" Grafik kaydedildi : {dosya}")
    try:
        plt.show()
    except Exception:
        pass


# --------------------------------------------------------------------------
# Dosyalar
# --------------------------------------------------------------------------

def ders_slug(ders: str) -> str:
    cevir = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    return re.sub(r"[^a-z0-9]+", "-", ders.translate(cevir).lower()).strip("-")


def dosya_koku(klasor: str, ders: str, an: datetime) -> Path:
    """Bu oturumun dosyalarinin ortak on eki: kayitlar/dikkat_<ders>_<tarih_saat>"""
    k = Path(klasor)
    k.mkdir(parents=True, exist_ok=True)
    parcalar = ["dikkat"] + ([ders_slug(ders)] if ders_slug(ders) else []) + [an.strftime("%Y%m%d_%H%M%S")]
    return k / "_".join(parcalar)


CSV_BASLIK = ["zaman", "ders_saniye", "sinif_skoru", "yumusak_skor", "ortalama_yuz",
              "dikkatsiz_orani", "yana_bakan_orani", "basi_egik_orani", "gozu_kapali_orani",
              "esneme_orani", "guvenilir"]
OLAY_BASLIK = ["baslangic", "bitis", "sure_sn", "ortalama_skor", "en_dusuk_skor", "neden"]


def _bos(v):
    return "" if v is None else v


# --------------------------------------------------------------------------
# Kamera + MediaPipe
# --------------------------------------------------------------------------

def model_hazirla() -> Path:
    if not MODEL_DOSYA.exists():
        print("Yuz modeli indiriliyor (tek seferlik, ~4 MB)...")
        urllib.request.urlretrieve(MODEL_URL, MODEL_DOSYA)
    return MODEL_DOSYA


def blendshape_degerleri(blendshapes) -> tuple[float, float]:
    """(goz kapalilik, cene acikligi) - ikisi de 0..1"""
    d = {b.category_name: b.score for b in blendshapes}
    goz = (d.get("eyeBlinkLeft", 0.0) + d.get("eyeBlinkRight", 0.0)) / 2.0
    return goz, d.get("jawOpen", 0.0)


def calistir(args: argparse.Namespace) -> None:
    import cv2
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    esikler = Esikler()
    secenekler = vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(model_hazirla())),
        running_mode=vision.RunningMode.VIDEO,
        num_faces=args.max_yuz,
        output_face_blendshapes=True,
        output_facial_transformation_matrixes=True,
    )

    kamera = cv2.VideoCapture(args.kamera)
    if not kamera.isOpened():
        sys.exit(f"Kamera acilamadi (indeks {args.kamera}). --kamera 1 deneyin.")

    kok = dosya_koku(args.klasor, args.ders, datetime.now())
    csv_yol, olay_yol = Path(f"{kok}.csv"), Path(f"{kok}_olaylar.csv")
    csv_dosya = open(csv_yol, "w", newline="", encoding="utf-8")
    olay_dosya = open(olay_yol, "w", newline="", encoding="utf-8")
    yazici, olay_yazici = csv.writer(csv_dosya), csv.writer(olay_dosya)
    yazici.writerow(CSV_BASLIK)
    olay_yazici.writerow(OLAY_BASLIK)
    olay_dosya.flush()
    if CSV_KANCASI:
        CSV_KANCASI(csv_yol)

    toplayici = DonemToplayici(esikler)
    oturum = Oturum(args.aralik, args.olay_esik, args.olay_sure, args.yumusatma)
    baslangic = time.monotonic()
    if BASLANGIC_KANCASI:
        BASLANGIC_KANCASI(baslangic)
    donem_basi, donem_basi_zaman = baslangic, datetime.now()
    yaw0 = pitch0 = 0.0
    kalib_ornek: list[tuple[float, float]] = []
    kalibrasyon_bitti = args.kalibrasyon <= 0
    son: Kayit | None = None
    uyari_verildi = False

    def olay_yaz(olay: Olay | None) -> None:
        if not olay:
            return
        olay_yazici.writerow([olay.baslangic.isoformat(timespec="seconds"),
                              olay.bitis.isoformat(timespec="seconds"), olay.sure_sn,
                              olay.ortalama_skor, olay.en_dusuk_skor, olay.neden])
        olay_dosya.flush()
        print(f"   OLAY: {olay.baslangic:%H:%M:%S}-{olay.bitis:%H:%M:%S} dikkat dususu "
              f"({olay.sure_sn} sn, ort {olay.ortalama_skor:.0f}) -> {olay.neden}")

    def donem_yaz(an: float) -> None:
        """Biriken donemi isler, CSV'ye yazar."""
        nonlocal son, uyari_verildi, donem_basi, donem_basi_zaman
        ozet = toplayici.ozet()
        toplayici.sifirla()
        bas, bit = donem_basi_zaman, datetime.now()
        donem_basi, donem_basi_zaman = an, bit
        if not ozet:
            return
        son, olay = oturum.donem_ekle(bas, bit, ozet)
        yazici.writerow([bit.isoformat(timespec="seconds"), round(an - baslangic),
                         _bos(son.skor), _bos(son.yumusak), son.ortalama_yuz, _bos(son.dikkatsiz),
                         _bos(son.yana), _bos(son.egik), _bos(son.kapali), _bos(son.esneme),
                         int(son.guvenilir)])
        csv_dosya.flush()
        if son.skor is None:
            print(f"[{bit:%H:%M:%S}] yuz gorulmuyor")
        else:
            print(f"[{bit:%H:%M:%S}] skor={son.skor:5.1f} ort={_bos(son.yumusak)!s:>5} "
                  f"yuz={son.ortalama_yuz} yana={son.yana} egik={son.egik} "
                  f"kapali={son.kapali} esneme={son.esneme}"
                  + ("" if son.guvenilir else "  [GUVENILMEZ: yuz sayisi dustu]"))
        olay_yaz(olay)
        if oturum.uyari_suresi and not uyari_verildi:
            print(f"   UYARI: dikkat {oturum.uyari_suresi:.0f} sn'dir dusuk - soru sormak ya da "
                  "kisa bir mola iyi gelebilir.")
            uyari_verildi = True
        elif not oturum.uyari_suresi:
            uyari_verildi = False

    print(f"Calisiyor. Kayit: {csv_yol}")
    if not kalibrasyon_bitti:
        print(f"Kalibrasyon: {args.kalibrasyon:.0f} sn boyunca herkes tahtaya baksin...")

    try:
        with vision.FaceLandmarker.create_from_options(secenekler) as dedektor:
            while True:
                if DURDUR_DOSYASI is not None and DURDUR_DOSYASI.exists():
                    break
                tamam, kare = kamera.read()
                if not tamam:
                    print("Kameradan kare alinamadi, cikiliyor.")
                    break

                simdi = time.monotonic()
                rgb = cv2.cvtColor(kare, cv2.COLOR_BGR2RGB)
                goruntu = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                sonuc = dedektor.detect_for_video(goruntu, int((simdi - baslangic) * 1000))

                ham = []  # (yaw, pitch, goz, cene, landmarklar)
                for i, matris in enumerate(sonuc.facial_transformation_matrixes or []):
                    yaw, pitch = bas_acilari(matris)
                    if args.pitch_ters:
                        pitch = -pitch
                    goz, cene = (blendshape_degerleri(sonuc.face_blendshapes[i])
                                 if sonuc.face_blendshapes else (0.0, 0.0))
                    ham.append((yaw, pitch, goz, cene, sonuc.face_landmarks[i]))

                yuzler: list[YuzOlcum] = []
                if not kalibrasyon_bitti:
                    kalib_ornek.extend((h[0], h[1]) for h in ham)
                    if simdi - baslangic >= args.kalibrasyon:
                        if kalib_ornek:
                            yaw0 = float(np.median([k[0] for k in kalib_ornek]))
                            pitch0 = float(np.median([k[1] for k in kalib_ornek]))
                        print(f"Kalibrasyon tamam: yaw0={yaw0:.1f}, pitch0={pitch0:.1f}")
                        kalibrasyon_bitti = True
                        donem_basi, donem_basi_zaman = simdi, datetime.now()
                else:
                    yuzler = [yuz_olc(y - yaw0, p - pitch0, g, c, esikler,
                                      not_toleransi=not args.not_toleransi_yok)
                              for y, p, g, c, _ in ham]
                    toplayici.ekle(yuzler)
                    if simdi - donem_basi >= args.aralik:
                        donem_yaz(simdi)

                if not args.onizleme_yok:
                    onizleme_ciz(cv2, kare, [h[4] for h in ham], yuzler, son, esikler,
                                 bulanik=not args.yuz_goster, kalibrasyon=not kalibrasyon_bitti,
                                 uyari_sn=oturum.uyari_suresi)
                    cv2.imshow("Sinif Dikkat Olcer (q: cikis)", kare)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
                del kare, rgb, goruntu  # kare hicbir yerde saklanmaz
    except KeyboardInterrupt:
        pass
    finally:
        kamera.release()
        an = time.monotonic()
        if kalibrasyon_bitti and an - donem_basi >= args.aralik / 2:
            donem_yaz(an)  # yarim kalan son donemi de kaydet (cok kisaysa atla)
        olay_yaz(oturum.bitir())         # hala suren dusus varsa kapat
        csv_dosya.close()
        olay_dosya.close()
        if not args.onizleme_yok:
            cv2.destroyAllWindows()

        ozet = oturum_ozeti(oturum, args.ders)
        ozet["dosyalar"] = {"olcumler": csv_yol.name, "olaylar": olay_yol.name}
        ozet_yol = Path(f"{kok}_ozet.json")
        ozet_yol.write_text(json.dumps(ozet, ensure_ascii=False, indent=2), encoding="utf-8")
        ozet_yazdir(ozet)
        print(f" Olcumler          : {csv_yol}")
        print(f" Olaylar           : {olay_yol}")
        print(f" Ozet (JSON)       : {ozet_yol}")
        if not args.grafik_yok:
            grafik_ciz(oturum, ozet, Path(f"{kok}_grafik.png"))


def onizleme_ciz(cv2, kare, landmarklar, yuzler, son, e, bulanik, kalibrasyon, uyari_sn):
    y_boy, x_boy = kare.shape[:2]
    for i, lm in enumerate(landmarklar):
        xs = [p.x for p in lm]
        ys = [p.y for p in lm]
        x1, x2 = max(0, int(min(xs) * x_boy)), min(x_boy, int(max(xs) * x_boy))
        y1, y2 = max(0, int(min(ys) * y_boy)), min(y_boy, int(max(ys) * y_boy))
        if x2 <= x1 or y2 <= y1:
            continue
        if bulanik:
            kare[y1:y2, x1:x2] = cv2.GaussianBlur(kare[y1:y2, x1:x2], (51, 51), 0)
        if i < len(yuzler):
            y = yuzler[i]
            renk = (0, 180, 0) if y.skor >= e.dikkatsiz_esik else (0, 0, 220)
            cv2.rectangle(kare, (x1, y1), (x2, y2), renk, 2)
            cv2.putText(kare, f"{y.skor:.0f} {y.harfler}", (x1, max(15, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, renk, 2)

    if kalibrasyon:
        yazi = "Kalibrasyon..."
    elif son is None:
        yazi = "Sinif skoru: -"
    elif not son.guvenilir:
        yazi = "OLCUM GUVENILMEZ (yuz sayisi dustu)"
    else:
        yazi = f"Sinif skoru: {son.yumusak:.0f}   yuz: {son.ortalama_yuz:.0f}"
    cv2.putText(kare, yazi, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 4)
    cv2.putText(kare, yazi, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)

    if uyari_sn:
        cv2.rectangle(kare, (0, y_boy - 44), (x_boy, y_boy), (40, 40, 200), -1)
        cv2.putText(kare, f"Dikkat {uyari_sn:.0f} sn'dir dusuk - soru / kisa mola?",
                    (10, y_boy - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)


def main() -> None:
    p = argparse.ArgumentParser(description="Anonim sinif dikkat skoru (cihaz ustunde).")
    p.add_argument("--ders", default="", help='Ders etiketi, orn. "Matematik 9-A"')
    p.add_argument("--klasor", default="kayitlar", help="Cikti klasoru (varsayilan: kayitlar)")
    p.add_argument("--kamera", type=int, default=0, help="Kamera indeksi (varsayilan 0)")
    p.add_argument("--max-yuz", type=int, default=10, help="Ayni anda izlenecek en fazla yuz")
    p.add_argument("--aralik", type=float, default=5.0, help="Olcum donemi (sn)")
    p.add_argument("--kalibrasyon", type=float, default=0.0,
                   help="Baslangicta 'tahtaya bakis' yonunu ogrenme suresi (sn)")
    p.add_argument("--olay-esik", type=float, default=50.0,
                   help="Sinif skoru bunun altina duserse 'dusuk' sayilir")
    p.add_argument("--olay-sure", type=float, default=30.0,
                   help="Dusukluk en az bu kadar surerse olay + uyari (sn)")
    p.add_argument("--yumusatma", type=float, default=30.0, help="Kayan ortalama penceresi (sn)")
    p.add_argument("--not-toleransi-yok", action="store_true",
                   help="Basi egik + gozu acik olanlara taban puan verme")
    p.add_argument("--pitch-ters", action="store_true",
                   help="Bas egme yonu ters algilaniyorsa (one egince 'E' cikmiyorsa)")
    p.add_argument("--grafik-yok", action="store_true", help="Kapanista grafik cizme")
    p.add_argument("--onizleme-yok", action="store_true", help="Pencere acma")
    p.add_argument("--yuz-goster", action="store_true",
                   help="Onizlemede yuzleri bulaniklastirma (sadece gelistirme icin)")
    args = p.parse_args()
    if args.aralik <= 0:
        p.error("--aralik pozitif olmali")
    calistir(args)


if __name__ == "__main__":
    main()
