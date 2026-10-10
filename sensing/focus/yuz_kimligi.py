"""
Rızalı kişisel odak: yalnızca KAYITLI öğrencileri tanır
======================================================
- Kayıt (öğretmen paneli): öğrencinin 3-4 fotoğrafından "yüz izi" (128 sayılık vektör) çıkarılır.
  Fotoğraflar kaydedilmez, yalnızca yüz izi veritabanına yazılır.
- Ders sırasında (kamera döngüsü): saniyede bir, karedeki yüzlerin izi kayıtlı izlerle karşılaştırılır.
    * Eşleşen yüz -> o öğrencinin odak skoru ayrıca kendi adına kaydedilir.
    * Eşleşmeyen yüz -> izi ANINDA atılır; kimlik yok, kayıt yok. Sadece anonim sınıf ortalamasına katılır.
- Yanlış eşleşmeye karşı: sıkı benzerlik eşiği + birkaç ardışık tanımada tutarlılık şartı +
  aynı öğrenci aynı anda yalnızca tek bir yüze atanabilir.

Modeller (OpenCV, ek kurulum gerekmez; sensing/focus/modeller/ altında):
    yuz_tespit_yunet.onnx   (YuNet, ~230 KB)
    yuz_izi_sface.onnx      (SFace, ~38 MB)
"""

from __future__ import annotations

import time
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from core import model_yukle

_PROJE_MODELLER = Path(__file__).resolve().parent / "modeller"
_URL = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
_KAYNAK = {
    "yuz_tespit_yunet.onnx": _URL + "face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "yuz_izi_sface.onnx": _URL + "face_recognition_sface/face_recognition_sface_2021dec.onnx",
}


def _model_yolu(ad: str) -> Path:
    """Önce proje klasörü, yoksa kalıcı klasör (yeni sürüm kurulunca tekrar indirilmesin)."""
    yerel = _PROJE_MODELLER / ad
    if yerel.exists() and yerel.stat().st_size > 1000:
        return yerel
    try:
        from core.kalici import klasor
        return klasor("modeller") / ad
    except Exception:
        return yerel


TESPIT_MODELI = _model_yolu("yuz_tespit_yunet.onnx")
IZ_MODELI = _model_yolu("yuz_izi_sface.onnx")
_INDIR = {TESPIT_MODELI: _KAYNAK[TESPIT_MODELI.name], IZ_MODELI: _KAYNAK[IZ_MODELI.name]}

ESIK = 0.42          # kosinüs benzerliği; SFace'in önerdiği "aynı kişi" sınırı 0.363, biz daha sıkıyız
OY_PENCERESI = 4     # son kaç tanıma denemesine bakılır
OY_GEREKEN = 2       # bir yüz, bu kadar denemede aynı öğrenciye eşleşirse o öğrenci sayılır
TANIMA_ARALIGI = 1.0 # sn: yüz izi bu sıklıkla çıkarılır (her karede değil; işlemciyi yormaz)


_EN_AZ_BOYUT = {"yuz_tespit_yunet.onnx": 100_000, "yuz_izi_sface.onnx": 10_000_000}


def modelleri_hazirla() -> None:
    # Yarım kalan indirme bozuk model bırakmasın: geçici dosyaya indirilip tamamlanınca yerine konur
    for yol, url in _INDIR.items():
        model_yukle.indir(url, yol, en_az_bayt=_EN_AZ_BOYUT.get(yol.name, 1000), ad="Yüz modeli")


class YuzKimligi:
    """YuNet ile yüz bulur, SFace ile yüz izi çıkarır."""

    def __init__(self):
        import cv2

        modelleri_hazirla()
        self.cv2 = cv2
        # Modeller bellekten verilir: OpenCV, Windows'ta Türkçe karakterli yolları (ör. "Masaüstü") açamıyor
        self.tespit = model_yukle.opencv_yuz_tespit(TESPIT_MODELI, (320, 320), 0.8, 0.3, 5000)
        self.taniyici = model_yukle.opencv_yuz_tanima(IZ_MODELI)

    def yuzleri_bul(self, bgr: np.ndarray) -> np.ndarray:
        h, w = bgr.shape[:2]
        self.tespit.setInputSize((w, h))
        _, yuzler = self.tespit.detect(bgr)
        return yuzler if yuzler is not None else np.zeros((0, 15), np.float32)

    def iz(self, bgr: np.ndarray, yuz: np.ndarray) -> np.ndarray:
        hizali = self.taniyici.alignCrop(bgr, yuz)
        f = self.taniyici.feature(hizali).reshape(-1).astype(np.float32)
        return f / (np.linalg.norm(f) + 1e-9)

    def kayit_izleri(self, goruntuler: List[np.ndarray]) -> tuple[np.ndarray, List[str]]:
        """Kayıt fotoğraflarından yüz izleri. Her fotoğrafta EN BÜYÜK yüz alınır.
        Dönüş: (izler (k,128), uyarılar)"""
        izler, uyarilar = [], []
        for i, g in enumerate(goruntuler, 1):
            yuzler = self.yuzleri_bul(g)
            if len(yuzler) == 0:
                uyarilar.append(f"{i}. fotoğrafta yüz bulunamadı.")
                continue
            if len(yuzler) > 1:
                uyarilar.append(f"{i}. fotoğrafta birden fazla yüz var; en büyüğü alındı.")
            en_buyuk = max(yuzler, key=lambda y: y[2] * y[3])
            izler.append(self.iz(g, en_buyuk))
        return (np.stack(izler) if izler else np.zeros((0, 128), np.float32)), uyarilar


def _benzerlik(iz: np.ndarray, kayitli: np.ndarray) -> float:
    return float(np.max(kayitli @ iz)) if len(kayitli) else -1.0


class KisiselTakip:
    """Kamera döngüsüne takılan kanca (classroom_focus.KISI_KANCASI)."""

    def __init__(self, ogrenciler: List[tuple[int, str, np.ndarray]], aralik: float = 5.0,
                 kaydet=None, kimlik: Optional[YuzKimligi] = None):
        self.kimlik = kimlik or YuzKimligi()
        self.ogrenciler = [(oid, ad, iz / (np.linalg.norm(iz, axis=1, keepdims=True) + 1e-9))
                           for oid, ad, iz in ogrenciler]
        self.adlar = {oid: ad for oid, ad, _ in self.ogrenciler}
        self.aralik = aralik
        self.kaydet = kaydet          # kaydet(satirlar) -> veritabanına yazar
        self.kayit = ""               # ölçüm dosyasının adı (classroom_focus CSV_KANCASI ile gelir)
        self._izler: List[dict] = []  # ekrandaki yüzlerin kısa ömürlü takibi (kimlik değil, konum)
        self._son_tanima = -1e9
        self._donem_basi = 0.0
        self._birikim: Dict[int, List[float]] = {}
        self.tanilanlar: set = set()

    # -- yardımcılar --------------------------------------------------------
    @staticmethod
    def _merkez(k):
        return ((k[0] + k[2]) / 2, (k[1] + k[3]) / 2)

    def _eslestir(self, kutular, genislik) -> List[dict]:
        """Bu karedeki her yüzü önceki karelerdeki konum takibine bağlar."""
        simdi = time.monotonic()
        sonuc, kullanilan = [], set()
        for k in kutular:
            m = self._merkez(k)
            en_iyi, en_uzak = None, 0.12 * genislik
            for j, t in enumerate(self._izler):
                if j in kullanilan:
                    continue
                d = ((t["m"][0] - m[0]) ** 2 + (t["m"][1] - m[1]) ** 2) ** 0.5
                if d < en_uzak:
                    en_iyi, en_uzak = j, d
            if en_iyi is None:
                self._izler.append({"m": m, "oylar": deque(maxlen=OY_PENCERESI), "son": simdi})
                en_iyi = len(self._izler) - 1
            kullanilan.add(en_iyi)
            t = self._izler[en_iyi]
            t["m"], t["son"] = m, simdi
            sonuc.append(t)
        self._izler = [t for t in self._izler if simdi - t["son"] < 3.0]  # görünmeyen takibi bırak
        return sonuc

    @staticmethod
    def _kim(t) -> Optional[int]:
        sayim: Dict[int, int] = {}
        for o in t["oylar"]:
            if o is not None:
                sayim[o] = sayim.get(o, 0) + 1
        if not sayim:
            return None
        oid, n = max(sayim.items(), key=lambda kv: kv[1])
        return oid if n >= OY_GEREKEN else None

    def _tani(self, kare, kutular, takipler) -> None:
        bulunan = self.kimlik.yuzleri_bul(kare)
        for y in bulunan:
            yx, yy = y[0] + y[2] / 2, y[1] + y[3] / 2
            # bu tespiti en yakın MediaPipe yüzüne bağla
            en_iyi, en_uzak = None, max(y[2], y[3])
            for i, k in enumerate(kutular):
                m = self._merkez(k)
                d = ((m[0] - yx) ** 2 + (m[1] - yy) ** 2) ** 0.5
                if d < en_uzak:
                    en_iyi, en_uzak = i, d
            if en_iyi is None:
                continue
            iz = self.kimlik.iz(kare, y)
            aday, en_yuksek = None, ESIK
            for oid, _, kayitli in self.ogrenciler:
                b = _benzerlik(iz, kayitli)
                if b >= en_yuksek:
                    aday, en_yuksek = oid, b
            del iz  # tanınsın ya da tanınmasın yüz izi saklanmaz
            takipler[en_iyi]["oylar"].append(aday)

    # -- kamera döngüsünden çağrılanlar -----------------------------------------
    def kare_isle(self, kare, kutular, skorlar, ders_saniye: float) -> Dict[int, str]:
        """kutular: piksel [x1,y1,x2,y2] (MediaPipe yüz sırasıyla), skorlar: aynı sırayla kişi skorları.
        Dönüş: {yüz sırası: öğrenci adı} (yalnızca kesinleşmiş kayıtlı öğrenciler)."""
        if not self.ogrenciler:
            return {}
        takipler = self._eslestir(kutular, kare.shape[1])
        simdi = time.monotonic()
        if simdi - self._son_tanima >= TANIMA_ARALIGI and kutular:
            self._son_tanima = simdi
            self._tani(kare, kutular, takipler)

        etiketler, atanan = {}, {}
        for i, t in enumerate(takipler):
            oid = self._kim(t)
            if oid is None:
                continue
            # aynı öğrenci iki yüze atanmasın: daha çok oy alan kazanır
            oy = sum(1 for o in t["oylar"] if o == oid)
            if oid in atanan and atanan[oid][1] >= oy:
                continue
            atanan[oid] = (i, oy)
        for oid, (i, _) in atanan.items():
            etiketler[i] = self.adlar[oid]
            self._birikim.setdefault(oid, []).append(float(skorlar[i]))
            self.tanilanlar.add(oid)

        if ders_saniye - self._donem_basi >= self.aralik:
            self._bosalt(ders_saniye)
        return etiketler

    def _bosalt(self, ders_saniye: float) -> None:
        satirlar = [(oid, round(ders_saniye), round(sum(v) / len(v), 1)) for oid, v in self._birikim.items() if v]
        self._birikim, self._donem_basi = {}, ders_saniye
        if satirlar and self.kaydet:
            try:
                self.kaydet(self.kayit, satirlar)
            except Exception as e:  # kişisel kayıt yazılamasa da ders kaydı devam etsin
                print(f"Kişisel odak yazılamadı: {e}")

    def bitir(self, ders_saniye: float) -> None:
        self._bosalt(ders_saniye)
        if self.tanilanlar:
            print("Kişisel odak kaydedilen kayıtlı öğrenciler: "
                  + ", ".join(self.adlar[o] for o in sorted(self.tanilanlar)))
