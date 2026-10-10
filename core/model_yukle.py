"""
Model dosyalarını her klasörde güvenle açmak için yardımcılar
=============================================================
Sorun: MediaPipe, OpenCV ve CTranslate2 (faster-whisper) gibi C++ kütüphaneleri Windows'ta dosya yolunu
"ANSI" kod sayfasıyla açar. Yolda Türkçe karakter (ör. C:\\Users\\acer\\OneDrive\\Masaüstü\\...) ya da
kullanıcı adında ğ/ş/ı/ö/ü varsa "Unable to open file" hatası verirler; dosya yerinde dursa bile.

Çözüm sırası:
  1) Mümkünse modeli Python ile okuyup kütüphaneye BELLEKTEN verilir (yol hiç kullanılmaz).
  2) Kütüphane bunu desteklemiyorsa model, yalnızca İngilizce karakter içeren bir önbellek klasörüne
     kopyalanır ve oradan açılır.
Ayrıca model indirmeleri yarım kalırsa bozuk dosya bırakmasın diye önce geçici dosyaya yazılır.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional

WINDOWS = os.name == "nt"


def ascii_mi(yol) -> bool:
    return str(yol).isascii()


def ascii_onbellek() -> Optional[Path]:
    """Yolunda yalnızca İngilizce karakter olan, yazılabilir bir önbellek klasörü (bulunamazsa None)."""
    adaylar = []
    if os.getenv("DERS_ASISTANI_ONBELLEK"):
        adaylar.append(Path(os.environ["DERS_ASISTANI_ONBELLEK"]))
    if WINDOWS:
        for degisken in ("PUBLIC", "ProgramData", "SystemDrive"):
            kok = os.getenv(degisken)
            if kok:
                kok = kok + "\\" if degisken == "SystemDrive" else kok
                adaylar.append(Path(kok) / "DersAsistani_onbellek")
    adaylar.append(Path(tempfile.gettempdir()) / "DersAsistani_onbellek")
    for aday in adaylar:
        if not ascii_mi(aday):
            continue
        try:
            aday.mkdir(parents=True, exist_ok=True)
            deneme = aday / ".yazma_denemesi"
            deneme.write_bytes(b"1")
            deneme.unlink()
            return aday
        except OSError:
            continue
    return None


def ascii_guvenli_yol(yol: Path) -> Path:
    """Windows'ta yol Türkçe karakter içeriyorsa dosyayı İngilizce karakterli bir klasöre kopyalar ve o yolu
    döndürür. Diğer durumlarda yolu aynen döndürür. Kopya, kaynak değişmediyse yeniden yapılmaz."""
    yol = Path(yol)
    if not WINDOWS or ascii_mi(yol.resolve()):
        return yol
    klasor = ascii_onbellek()
    if klasor is None:
        return yol  # yapacak bir şey yok; kütüphanenin kendi hatası görünsün
    hedef = klasor / "modeller" / yol.name
    try:
        if not hedef.exists() or hedef.stat().st_size != yol.stat().st_size:
            hedef.parent.mkdir(parents=True, exist_ok=True)
            gecici = hedef.with_name(hedef.name + ".kopyalaniyor")
            shutil.copyfile(yol, gecici)
            os.replace(gecici, hedef)
        return hedef
    except OSError:
        return yol


def indir(url: str, hedef: Path, en_az_bayt: int = 1000, ad: str = "model") -> Path:
    """Dosyayı indirir. Önce '.indiriliyor' uzantılı geçici dosyaya yazar, tamamlanınca yerine koyar; böylece
    yarım kalan bir indirme bir sonraki açılışta 'bozuk model' hatasına yol açmaz."""
    hedef = Path(hedef)
    if hedef.exists() and hedef.stat().st_size >= en_az_bayt:
        return hedef
    hedef.parent.mkdir(parents=True, exist_ok=True)
    gecici = hedef.with_name(hedef.name + ".indiriliyor")
    print(f"{ad} indiriliyor (tek seferlik): {hedef.name} ...")
    try:
        with urllib.request.urlopen(url, timeout=60) as yanit, open(gecici, "wb") as dosya:
            shutil.copyfileobj(yanit, dosya, length=1 << 16)
        if gecici.stat().st_size < en_az_bayt:
            raise OSError(f"indirilen dosya beklenenden küçük ({gecici.stat().st_size} bayt)")
        os.replace(gecici, hedef)
    except Exception:
        try:
            gecici.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return hedef


def bayt_oku(yol: Path) -> bytes:
    """Model dosyasını Python ile okur (Python her yolu doğru açar). OneDrive'da 'yalnızca çevrimiçi'
    duran dosyalar da bu okumayla indirilir."""
    veri = Path(yol).read_bytes()
    if not veri:
        raise OSError(f"Model dosyası boş: {yol}")
    return veri


# ---------------------------------------------------------------------------
# OpenCV yüz modelleri (YuNet, SFace)
# ---------------------------------------------------------------------------
def opencv_yuz_tespit(yol: Path, boyut=(320, 320), skor=0.8, nms=0.3, en_fazla=5000):
    import cv2
    import numpy as np

    try:  # OpenCV >= 4.8: modeli bellekten ver
        tampon = np.frombuffer(bayt_oku(yol), np.uint8)
        return cv2.FaceDetectorYN.create("onnx", tampon, np.zeros(0, np.uint8), boyut, skor, nms, en_fazla)
    except (cv2.error, TypeError, AttributeError):
        return cv2.FaceDetectorYN.create(str(ascii_guvenli_yol(yol)), "", boyut, skor, nms, en_fazla)


def opencv_yuz_tanima(yol: Path):
    import cv2
    import numpy as np

    try:  # yeni OpenCV sürümleri: modeli bellekten ver
        tampon = np.frombuffer(bayt_oku(yol), np.uint8)
        return cv2.FaceRecognizerSF.create("onnx", tampon, np.zeros(0, np.uint8))
    except (cv2.error, TypeError, AttributeError):
        return cv2.FaceRecognizerSF.create(str(ascii_guvenli_yol(yol)), "")


# ---------------------------------------------------------------------------
# faster-whisper (CTranslate2)
# ---------------------------------------------------------------------------
def whisper_indirme_klasoru() -> Optional[str]:
    """Whisper modelinin indirileceği klasör. Windows'ta kullanıcı klasörünün adında Türkçe karakter varsa
    (ör. C:\\Users\\Öğretmen) CTranslate2 modeli açamaz; o durumda İngilizce karakterli bir klasör seçilir.
    Kullanıcı HF_HOME / HF_HUB_CACHE ile kendi klasörünü verdiyse ya da sorun yoksa None (varsayılan)."""
    if not WINDOWS or os.getenv("HF_HUB_CACHE") or os.getenv("HUGGINGFACE_HUB_CACHE"):
        return None
    varsayilan = Path(os.getenv("HF_HOME") or (Path.home() / ".cache" / "huggingface"))
    if ascii_mi(varsayilan):
        return None
    klasor = ascii_onbellek()
    return str(klasor / "whisper") if klasor else None


def whisper_modeli(model_adi: str, **ayarlar):
    """WhisperModel'i Türkçe karakterli yollara karşı korumalı oluşturur."""
    from faster_whisper import WhisperModel

    if Path(model_adi).exists():  # yerel klasör verilmiş
        model_adi = str(_klasoru_ascii_yap(Path(model_adi)))
    else:
        klasor = whisper_indirme_klasoru()
        if klasor:
            ayarlar.setdefault("download_root", klasor)
    return WhisperModel(model_adi, **ayarlar)


def _klasoru_ascii_yap(klasor: Path) -> Path:
    if not WINDOWS or ascii_mi(klasor.resolve()):
        return klasor
    onbellek = ascii_onbellek()
    if onbellek is None:
        return klasor
    hedef = onbellek / "whisper_yerel" / (klasor.name if ascii_mi(klasor.name) else "model")
    if not hedef.exists():
        shutil.copytree(klasor, hedef)
    return hedef
