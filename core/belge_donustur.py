"""
Sunum ve belge dosyalarını PDF'e çevirir (tahtaya sürükle-bırak için)
====================================================================
Tarayıcı PowerPoint / Word dosyalarını kendisi çizemez; bu yüzden tahtaya bırakılan .pptx, .docx gibi dosyalar
önce bu bilgisayarda PDF'e çevrilir, sonra tahtada sayfa sayfa açılır. Kullanılan program, sırayla:

    Windows: Microsoft PowerPoint / Word (yüklüyse)  ->  LibreOffice
    macOS / Linux: LibreOffice

Hiçbiri yoksa öğretmene dosyayı PDF olarak kaydetmesi söylenir (PDF ve resimler tarayıcıda doğrudan açılır).
Dosya geçici bir klasörde, İngilizce karakterli bir adla işlenir ve işlem bitince silinir; internete gönderilmez.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple

SUNUM = {".ppt", ".pptx", ".pps", ".ppsx", ".pot", ".potx", ".odp", ".key"}
METIN = {".doc", ".docx", ".odt", ".rtf"}
OFFICE_SUNUM = SUNUM - {".key"}       # PowerPoint .odp açabilir, Keynote dosyasını açamaz
OFFICE_METIN = METIN
DESTEKLENEN = SUNUM | METIN
EN_BUYUK = 30 * 1024 * 1024          # bayt: tarayıcı ile arayüz arasındaki mesaj sınırının altında kalsın
EN_BUYUK_PDF = 34 * 1024 * 1024
ZAMAN_ASIMI = 180                    # sn
_PENCERESIZ = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

PDF_OLARAK_KAYDET = ("PowerPoint'te Dosya > Farklı Kaydet > PDF ile kaydedip PDF dosyasını tahtaya bırakabilirsiniz.")


class DonusturmeHatasi(Exception):
    """Öğretmene gösterilecek, anlaşılır hata."""


# ---------------------------------------------------------------------------
# Programları bul
# ---------------------------------------------------------------------------
def libreoffice_yolu() -> Optional[str]:
    for ad in ("soffice", "libreoffice"):
        yol = shutil.which(ad)
        if yol:
            return yol
    adaylar: List[Path] = []
    if os.name == "nt":
        for kok in (os.getenv("ProgramFiles"), os.getenv("ProgramFiles(x86)"), r"C:\Program Files",
                    r"C:\Program Files (x86)"):
            if kok:
                adaylar.append(Path(kok) / "LibreOffice" / "program" / "soffice.exe")
    elif sys.platform == "darwin":
        adaylar.append(Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"))
    return next((str(a) for a in adaylar if a.exists()), None)


def _powershell() -> Optional[str]:
    if os.name != "nt":
        return None
    return shutil.which("powershell") or shutil.which("pwsh")


# ---------------------------------------------------------------------------
# Çeviriciler
# ---------------------------------------------------------------------------
_PS_POWERPOINT = r"""
$ErrorActionPreference = 'Stop'
$app = New-Object -ComObject PowerPoint.Application
$sunum = $null
try {
    # ReadOnly=-1 (evet), Untitled=0, WithWindow=0 (pencere acmadan)
    $sunum = $app.Presentations.Open($args[0], -1, 0, 0)
    $sunum.SaveAs($args[1], 32)    # 32 = ppSaveAsPDF
} finally {
    if ($sunum -ne $null) { $sunum.Close() }
    # Ogretmenin acik baska sunumu varsa PowerPoint'i KAPATMA
    if ($app.Presentations.Count -eq 0) { $app.Quit() }
}
"""

_PS_WORD = r"""
$ErrorActionPreference = 'Stop'
$app = New-Object -ComObject Word.Application
$app.Visible = $false
$app.DisplayAlerts = 0
$belge = $null
try {
    $belge = $app.Documents.Open($args[0], $false, $true)   # ConfirmConversions=hayir, ReadOnly=evet
    $belge.ExportAsFixedFormat($args[1], 17)                # 17 = wdExportFormatPDF
} finally {
    if ($belge -ne $null) { $belge.Close(0) }
    if ($app.Documents.Count -eq 0) { $app.Quit() }
}
"""


def _son_satir(metin: str) -> str:
    satirlar = [s.strip() for s in (metin or "").splitlines() if s.strip()]
    return satirlar[-1][:200] if satirlar else ""


def _office_ile(betik: str, ad: str) -> Callable[[Path, Path], None]:
    def cevir(kaynak: Path, hedef: Path) -> None:
        ps = _powershell()
        if not ps:
            raise FileNotFoundError("PowerShell yok")
        betik_yolu = kaynak.with_name("cevir.ps1")
        betik_yolu.write_text(betik, encoding="utf-8-sig")   # BOM: Windows PowerShell 5.1 UTF-8 okusun
        sonuc = subprocess.run(
            [ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(betik_yolu),
             str(kaynak), str(hedef)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=ZAMAN_ASIMI,
            creationflags=_PENCERESIZ)
        if sonuc.returncode != 0 or not hedef.exists():
            hata = _son_satir(sonuc.stderr) or _son_satir(sonuc.stdout)
            if "80040154" in hata or "REGDB_E_CLASSNOTREG" in hata:   # program kayıtlı değil (yüklü değil)
                raise FileNotFoundError(f"{ad} yüklü değil")
            raise RuntimeError(hata or f"{ad} PDF oluşturmadı")
    return cevir


def _libreoffice_ile(kaynak: Path, hedef: Path) -> None:
    soffice = libreoffice_yolu()
    if not soffice:
        raise FileNotFoundError("LibreOffice yok")
    profil = kaynak.parent / "lo_profil"     # açık bir LibreOffice penceresiyle çakışmasın
    sonuc = subprocess.run(
        [soffice, f"-env:UserInstallation={profil.as_uri()}", "--headless", "--norestore", "--nologo",
         "--convert-to", "pdf", "--outdir", str(hedef.parent), str(kaynak)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=ZAMAN_ASIMI,
        creationflags=_PENCERESIZ)
    # Windows'ta soffice.exe dönüştürme bitmeden dönebilir: dosya oluşup boyutu sabitlenene kadar bekle
    bitis, onceki = time.time() + 30, -1
    while time.time() < bitis:
        if hedef.exists():
            boyut = hedef.stat().st_size
            if boyut > 0 and boyut == onceki:
                return
            onceki = boyut
        time.sleep(0.5)
    raise RuntimeError(_son_satir(sonuc.stderr) or _son_satir(sonuc.stdout) or "LibreOffice PDF oluşturmadı")


def _ceviriciler(uzanti: str) -> List[Tuple[str, Callable[[Path, Path], None]]]:
    liste: List[Tuple[str, Callable[[Path, Path], None]]] = []
    if os.name == "nt":
        if uzanti in OFFICE_SUNUM:
            liste.append(("PowerPoint", _office_ile(_PS_POWERPOINT, "PowerPoint")))
        if uzanti in OFFICE_METIN:
            liste.append(("Word", _office_ile(_PS_WORD, "Word")))
    liste.append(("LibreOffice", _libreoffice_ile))
    return liste


# ---------------------------------------------------------------------------
# Dışa açık
# ---------------------------------------------------------------------------
def pdfe_cevir(veri: bytes, ad: str) -> bytes:
    """Sunum / belge baytlarını PDF baytlarına çevirir. Başarısızsa DonusturmeHatasi."""
    uzanti = Path(ad or "").suffix.lower()
    if uzanti not in DESTEKLENEN:
        raise DonusturmeHatasi(f"'{uzanti or ad}' dosyaları açılamıyor. PDF, PowerPoint, Word ya da resim bırakın.")
    if not veri:
        raise DonusturmeHatasi("Dosya boş.")
    if len(veri) > EN_BUYUK:
        raise DonusturmeHatasi(f"Dosya {EN_BUYUK // (1024 * 1024)} MB'tan büyük. {PDF_OLARAK_KAYDET}")

    denenen: List[str] = []
    with tempfile.TemporaryDirectory(prefix="tahta_belge_") as klasor:
        # İngilizce karakterli ad: Office / LibreOffice yol sorunları yaşamasın
        kaynak = Path(klasor) / f"belge{uzanti}"
        kaynak.write_bytes(veri)
        hedef = Path(klasor) / "belge.pdf"
        for program, cevir in _ceviriciler(uzanti):
            hedef.unlink(missing_ok=True)
            try:
                cevir(kaynak, hedef)
            except FileNotFoundError:
                continue                                  # program yüklü değil: sıradakini dene
            except subprocess.TimeoutExpired:
                denenen.append(f"{program} {ZAMAN_ASIMI} sn içinde bitiremedi")
                continue
            except Exception as e:                        # program var ama dosyayı açamadı
                denenen.append(f"{program}: {str(e)[:160]}")
                continue
            if hedef.exists() and hedef.stat().st_size > 0:
                pdf = hedef.read_bytes()
                if len(pdf) > EN_BUYUK_PDF:
                    raise DonusturmeHatasi(f"Oluşan PDF {len(pdf) // (1024 * 1024)} MB; tahtaya göndermek için çok "
                                           f"büyük. Sunumu daha az sayfayla ya da sıkıştırılmış resimlerle kaydedin.")
                return pdf
            denenen.append(f"{program}: PDF oluşmadı")

    if not denenen:
        programlar = "PowerPoint/Word ya da LibreOffice" if os.name == "nt" else "LibreOffice"
        raise DonusturmeHatasi(f"Bu bilgisayarda {programlar} bulunamadı, bu yüzden dosya PDF'e çevrilemedi. "
                               f"{PDF_OLARAK_KAYDET}")
    raise DonusturmeHatasi("Dosya PDF'e çevrilemedi (" + "; ".join(denenen) + "). " + PDF_OLARAK_KAYDET)
