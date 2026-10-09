"""
Gerçek ders verisi köprüsü
==========================
Ses/not hattının (transkript.py + notlar.py) ve görüntü işleme modülünün
(dikkat_olcer.py / classroom_focus.py) ürettiği dosyaları, arayüzün kullandığı
veri sözleşmelerine (Lecture, LectureNotes, FocusSample) çevirir.

Okunan dosyalar (varsayılan: proje klasörü, GERCEK_VERI_KLASORU ile değiştirilebilir):
    transkript.json          -> [{"baslangic", "bitis", "metin"}]
    notlar.json              -> notlar.py çıktısı (bölümler, quiz, odak_serisi ...)
    kayitlar/dikkat_*.csv    -> görüntü işleme ölçümleri (notlar.json'da odak yoksa)
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from core.schemas import FocusSample, Lecture, LectureNotes, NoteSection, TranscriptSegment

PROJE_KLASORU = Path(__file__).resolve().parents[1]
VERI_KLASORU = Path(os.getenv("GERCEK_VERI_KLASORU", PROJE_KLASORU))

TRANSKRIPT = VERI_KLASORU / "transkript.json"
NOTLAR = VERI_KLASORU / "notlar.json"
KAYITLAR = VERI_KLASORU / "kayitlar"
TAHTA_JSON = VERI_KLASORU / "tahta.json"   # eski sürümden kalan tek tahta (varsa listede gösterilir)
TAHTA_PNG = VERI_KLASORU / "tahta.png"
TAHTALAR = VERI_KLASORU / "tahtalar"       # her dersin tahtası: <tarih_saat>_<ders>.png / .json


# ---------------------------------------------------------------------------
# Durum
# ---------------------------------------------------------------------------
def eksik_dosyalar() -> List[str]:
    return [p.name for p in (TRANSKRIPT, NOTLAR) if not p.exists()]


def veri_imzasi() -> str:
    """Dosyalar değiştiğinde değişen kısa bir anahtar (önbelleği tazelemek için)."""
    parcalar = []
    for p in (TRANSKRIPT, NOTLAR, _odak_csv()):
        if p and p.exists():
            parcalar.append(f"{p.name}:{int(p.stat().st_mtime)}")
    return "|".join(parcalar)


def _oku_json(yol: Path):
    return json.loads(yol.read_text(encoding="utf-8"))


def notlar_ham() -> dict:
    return _oku_json(NOTLAR)


# ---------------------------------------------------------------------------
# Ders (Lecture)
# ---------------------------------------------------------------------------
def gercek_ders() -> Lecture:
    transkript = _oku_json(TRANSKRIPT)
    notlar = notlar_ham()
    sure = float(notlar.get("sure_saniye") or (transkript[-1]["bitis"] if transkript else 1.0))

    bolumler = sorted(notlar.get("bolumler", []), key=lambda b: float(b.get("baslangic_saniye", 0)))
    segmentler: List[TranscriptSegment] = []
    onceki_bitis = 0.0
    for i, b in enumerate(bolumler):
        bas = 0.0 if i == 0 else max(onceki_bitis, float(b.get("baslangic_saniye", onceki_bitis)))
        bit = float(b.get("bitis_saniye", bas + 1))
        if i == len(bolumler) - 1:
            bit = max(bit, sure)
        if bit <= bas:
            bit = bas + 1.0
        metin = " ".join(p["metin"] for p in transkript if bas <= float(p["baslangic"]) < bit).strip()
        if not metin:
            metin = " ".join(b.get("notlar", [])) or b.get("baslik", "—")
        segmentler.append(TranscriptSegment(start_time=round(bas, 2), end_time=round(bit, 2),
                                            topic=b.get("baslik") or f"Bölüm {i + 1}", transcript=metin))
        onceki_bitis = bit

    if not segmentler:  # bölüm yoksa tüm dersi tek bölüm say
        segmentler.append(TranscriptSegment(
            start_time=0.0, end_time=max(sure, 1.0), topic=notlar.get("ders_basligi", "Ders"),
            transcript=" ".join(p["metin"] for p in transkript) or "—"))

    zaman = datetime.fromtimestamp(NOTLAR.stat().st_mtime)
    return Lecture(
        lecture_id=f"gercek-{zaman:%Y%m%d-%H%M%S}",
        title=notlar.get("ders_basligi") or "Ders Kaydı",
        subject="Canlı ders kaydı",
        grade_level=f"{zaman:%d.%m.%Y %H:%M}",
        segments=segmentler,
    )


# ---------------------------------------------------------------------------
# Ders notları (LectureNotes) - Gemini'nin ürettiği notlar.json'dan, ek LLM çağrısı yok
# ---------------------------------------------------------------------------
def gercek_notlar() -> LectureNotes:
    n = notlar_ham()
    bolumler = sorted(n.get("bolumler", []), key=lambda b: float(b.get("baslangic_saniye", 0)))
    sections: List[NoteSection] = []
    tahta: List[str] = []

    for b in bolumler:
        satirlar = [f"• {m}" for m in b.get("notlar", [])]
        for k in b.get("anahtar_kavramlar", []):
            satirlar.append(f"• {k.get('kavram', '')}: {k.get('tanim', '')}")
        for o in b.get("ornekler", []):
            satirlar.append(f"Örnek: {o}")
            tahta.append(f"{b.get('baslik', '')}: {o}")

        if b.get("zorlanilan_konu"):
            uyari = f"⭐ Sınıf bu bölümde zorlandı (ortalama odak {b.get('ortalama_odak', '?')}/100)."
            if b.get("dikkat_nedeni"):
                uyari += f" Bu sırada {b['dikkat_nedeni']['aciklama']}."
            satirlar = [uyari, ""] + satirlar
            ek = b.get("ek_destek") or {}
            if ek.get("basit_anlatim"):
                satirlar += ["", "Ek destek (basit anlatım):", ek["basit_anlatim"]]
            for a in ek.get("adimlar", []):
                satirlar.append(f"  {a}")
            if ek.get("sik_yapilan_hata"):
                satirlar.append(f"Sık yapılan hata: {ek['sik_yapilan_hata']}")
            for o in ek.get("ek_ornekler", []):
                tahta.append(f"Ek örnek ({b.get('baslik', '')}): {o.get('soru', '')}\n   Çözüm: {o.get('cozum', '')}")

        sections.append(NoteSection(
            topic=b.get("baslik") or "Bölüm",
            content="\n".join(satirlar) or "—",
            key_terms=[k.get("kavram", "") for k in b.get("anahtar_kavramlar", []) if k.get("kavram")],
        ))

    return LectureNotes(
        title=n.get("ders_basligi") or "Ders Notları",
        summary=n.get("ders_ozeti") or "",
        sections=sections or [NoteSection(topic="Genel", content="—")],
        board_solutions=tahta,
    )


def ogretmen_onerisi() -> Optional[str]:
    try:
        return notlar_ham().get("ogretmen_onerisi")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Odak serisi (FocusSample)
# ---------------------------------------------------------------------------
def _odak_csv() -> Optional[Path]:
    if not KAYITLAR.exists():
        return None
    adaylar = [p for p in KAYITLAR.glob("dikkat_*.csv") if not p.name.endswith("_olaylar.csv")]
    return max(adaylar, key=lambda p: p.stat().st_mtime) if adaylar else None


def _sayi(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def gercek_odak() -> List[FocusSample]:
    """Önce notlar.json içindeki odak_serisi, yoksa kayitlar/ altındaki en yeni ölçüm dosyası."""
    seri = []
    try:
        seri = [(float(v["saniye"]), float(v["skor"])) for v in notlar_ham().get("odak_serisi", [])]
    except Exception:
        seri = []

    if not seri:
        yol = _odak_csv()
        if yol:
            with open(yol, encoding="utf-8") as f:
                for s in csv.DictReader(f):
                    if s.get("guvenilir") == "0":
                        continue
                    t = _sayi(s.get("ders_saniye", s.get("saniye")))
                    skor = _sayi(s.get("sinif_skoru", s.get("odak_skoru")))
                    if t is not None and skor is not None:
                        seri.append((t, skor))
            if seri and max(sk for _, sk in seri) <= 1:
                seri = [(t, sk * 100) for t, sk in seri]

    seri.sort()
    return [FocusSample(timestamp=round(t, 2), focus_score=round(min(100.0, max(0.0, sk)), 1))
            for t, sk in seri if t >= 0]


# ---------------------------------------------------------------------------
# Tahta defteri arşivi
# ---------------------------------------------------------------------------
def _tahta_kaydi(png: Path, js: Path) -> dict:
    kayit = {"png": png, "json": js if js.exists() else None, "ders": "",
             "zaman": datetime.fromtimestamp(png.stat().st_mtime).strftime("%d.%m.%Y %H:%M"),
             "sira": png.stat().st_mtime}
    try:
        kayit["ders"] = _oku_json(js).get("ders") or ""
    except Exception:
        pass
    return kayit


def tahta_listesi() -> List[dict]:
    """Arşivdeki bütün tahtalar, en yeni en başta."""
    liste = []
    if TAHTALAR.exists():
        liste = [_tahta_kaydi(png, png.with_suffix(".json")) for png in TAHTALAR.glob("*.png")]
    if TAHTA_PNG.exists():  # eski sürümle kaydedilmiş tek tahta
        liste.append(_tahta_kaydi(TAHTA_PNG, TAHTA_JSON))
    return sorted(liste, key=lambda k: k["sira"], reverse=True)


def tahta_bilgisi() -> Optional[dict]:
    """Son tahta (geriye uyumluluk için)."""
    liste = tahta_listesi()
    return liste[0] if liste else None
