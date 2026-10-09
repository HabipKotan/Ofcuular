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
VERI_KLASORU = Path(os.getenv("GERCEK_VERI_KLASORU") or PROJE_KLASORU)  # boş bırakılırsa proje klasörü

TRANSKRIPT = VERI_KLASORU / "transkript.json"
NOTLAR = VERI_KLASORU / "notlar.json"
KAYITLAR = VERI_KLASORU / "kayitlar"
PAYLASIM = VERI_KLASORU / "paylasim.json"  # öğretmenin onaylayıp öğrencilerle paylaştığı ders (oturumlar arası ortak)
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
    for p in (TRANSKRIPT, NOTLAR):
        if p and p.exists():
            parcalar.append(f"{p.name}:{int(p.stat().st_mtime)}")
    return "|".join(parcalar)


def _oku_json(yol: Path):
    return json.loads(yol.read_text(encoding="utf-8"))


def notlar_ham() -> dict:
    veri = _oku_json(NOTLAR)
    return veri if isinstance(veri, dict) else {}


def _transkript() -> List[dict]:
    """transkript.json: yalnızca metni olan, zamanı okunabilen parçalar."""
    veri = _oku_json(TRANSKRIPT)
    parcalar = []
    for p in veri if isinstance(veri, list) else []:
        if isinstance(p, dict) and str(p.get("metin") or "").strip():
            bas = _sayi(p.get("baslangic")) or 0.0
            parcalar.append({"baslangic": bas, "bitis": _sayi(p.get("bitis")) or bas, "metin": str(p["metin"]).strip()})
    return parcalar


def _liste(v) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _bolumler(notlar: dict) -> List[dict]:
    bolumler = [b for b in _liste(notlar.get("bolumler")) if isinstance(b, dict)]
    return sorted(bolumler, key=lambda b: _sayi(b.get("baslangic_saniye")) or 0.0)


# ---------------------------------------------------------------------------
# Ders (Lecture)
# ---------------------------------------------------------------------------
def gercek_ders() -> Lecture:
    transkript = _transkript()
    notlar = notlar_ham()
    sure = _sayi(notlar.get("sure_saniye")) or (transkript[-1]["bitis"] if transkript else 1.0)

    bolumler = _bolumler(notlar)
    segmentler: List[TranscriptSegment] = []
    onceki_bitis = 0.0
    for i, b in enumerate(bolumler):
        bas = 0.0 if i == 0 else max(onceki_bitis, _sayi(b.get("baslangic_saniye")) or onceki_bitis)
        bit = _sayi(b.get("bitis_saniye")) or bas + 1
        if i == len(bolumler) - 1:
            bit = max(bit, sure)
        if bit <= bas:
            bit = bas + 1.0
        metin = " ".join(p["metin"] for p in transkript if bas <= p["baslangic"] < bit).strip()
        if not metin:
            metin = " ".join(str(m) for m in _liste(b.get("notlar"))) or str(b.get("baslik") or "—")
        segmentler.append(TranscriptSegment(start_time=round(bas, 2), end_time=round(bit, 2),
                                            topic=str(b.get("baslik") or f"Bölüm {i + 1}"), transcript=metin))
        onceki_bitis = bit

    if not segmentler:  # bölüm yoksa tüm dersi tek bölüm say
        segmentler.append(TranscriptSegment(
            start_time=0.0, end_time=max(sure, 1.0), topic=str(notlar.get("ders_basligi") or "Ders"),
            transcript=" ".join(p["metin"] for p in transkript) or "—"))

    zaman = datetime.fromtimestamp(NOTLAR.stat().st_mtime)
    return Lecture(
        lecture_id=f"gercek-{zaman:%Y%m%d-%H%M%S}",
        title=str(notlar.get("konu") or notlar.get("ders_basligi") or "Ders Kaydı"),  # öğretmenin verdiği ad
        subject="Canlı ders kaydı",
        grade_level=f"{zaman:%d.%m.%Y %H:%M}",
        segments=segmentler,
    )


# ---------------------------------------------------------------------------
# Ders notları (LectureNotes) - Gemini'nin ürettiği notlar.json'dan, ek LLM çağrısı yok
# ---------------------------------------------------------------------------
def gercek_notlar() -> LectureNotes:
    n = notlar_ham()
    bolumler = _bolumler(n)
    sections: List[NoteSection] = []
    tahta: List[str] = []

    for b in bolumler:
        satirlar = [f"• {m}" for m in _liste(b.get("notlar"))]
        kavramlar = [k for k in _liste(b.get("anahtar_kavramlar")) if isinstance(k, dict) and k.get("kavram")]
        for k in kavramlar:
            satirlar.append(f"• {k.get('kavram', '')}: {k.get('tanim') or ''}".rstrip(": "))
        for o in _liste(b.get("ornekler")):
            satirlar.append(f"Örnek: {o}")
            tahta.append(f"{b.get('baslik', '')}: {o}")

        if b.get("zorlanilan_konu"):
            uyari = f"⭐ Sınıf bu bölümde zorlandı (ortalama odak {b.get('ortalama_odak', '?')}/100)."
            neden = b.get("dikkat_nedeni")
            if isinstance(neden, dict) and neden.get("aciklama"):
                uyari += f" Bu sırada {neden['aciklama']}."
            satirlar = [uyari, ""] + satirlar
            ek = b.get("ek_destek") if isinstance(b.get("ek_destek"), dict) else {}
            if ek.get("basit_anlatim"):
                satirlar += ["", "Ek destek (basit anlatım):", ek["basit_anlatim"]]
            for a in _liste(ek.get("adimlar")):
                satirlar.append(f"  {a}")
            if ek.get("sik_yapilan_hata"):
                satirlar.append(f"Sık yapılan hata: {ek['sik_yapilan_hata']}")
            for o in (x for x in _liste(ek.get("ek_ornekler")) if isinstance(x, dict)):
                tahta.append(f"Ek örnek ({b.get('baslik', '')}): {o.get('soru', '')}\n   Çözüm: {o.get('cozum', '')}")

        sections.append(NoteSection(
            topic=str(b.get("baslik") or "Bölüm"),
            content="\n".join(satirlar) or "—",
            key_terms=[str(k["kavram"]) for k in kavramlar],
        ))

    return LectureNotes(
        title=n.get("ders_basligi") or "Ders Notları",
        summary=n.get("ders_ozeti") or "",
        sections=sections or [NoteSection(topic="Genel", content="—")],
        board_solutions=tahta,
    )


def quiz() -> List[dict]:
    """notlar.json içindeki genel ders quiz'i: [{"soru", "secenekler", "dogru_cevap", "aciklama"}] (geçerli olanlar)."""
    try:
        ham = _liste(notlar_ham().get("quiz"))
    except Exception:
        return []
    sorular = []
    for q in ham:
        if not isinstance(q, dict) or not q.get("soru"):
            continue
        secenekler = [str(x) for x in _liste(q.get("secenekler"))]
        dogru = _sayi(q.get("dogru_cevap"))
        if len(secenekler) >= 2 and dogru is not None and 0 <= int(dogru) < len(secenekler):
            sorular.append({"soru": str(q["soru"]), "secenekler": secenekler, "dogru_cevap": int(dogru),
                            "aciklama": str(q.get("aciklama") or "")})
    return sorular


def ders_bilgisi() -> dict:
    """Son dersin özet bilgileri (öğretmen panelindeki tablo için)."""
    try:
        n = notlar_ham()
    except Exception:
        return {}
    ses = n.get("ses") if isinstance(n.get("ses"), dict) else {}
    ayrim = ses.get("ogretmen_ayrimi") if isinstance(ses.get("ogretmen_ayrimi"), dict) else {}
    izlendi = n.get("odak_izlendi")
    if izlendi is None:  # eski kayıt: odak serisi varsa izlenmiş say
        izlendi = bool(n.get("odak_serisi"))
    return {
        "konu": str(n.get("konu") or ""),
        "baslik": str(n.get("ders_basligi") or ""),
        "sure_saniye": _sayi(n.get("sure_saniye")) or 0.0,
        "ses_kaydedildi": not n.get("ses_kaydedilmedi"),
        "ders_algilandi": not n.get("ders_algilanmadi"),
        "odak_izlendi": bool(izlendi),
        "ortalama_odak": _sayi(n.get("ortalama_odak")),
        "ogrenci_sayisi": int(_sayi(n.get("ogrenci_sayisi")) or 0) or None,
        "model": ses.get("model"),
        "duzeltilen_satir": int(_sayi(ses.get("duzeltilen_satir")) or 0),
        "ayrim": ayrim,
        "zaman": datetime.fromtimestamp(NOTLAR.stat().st_mtime).strftime("%d.%m.%Y %H:%M"),
    }


# ---------------------------------------------------------------------------
# Paylaşım: öğretmenin onayı tüm oturumlarda (öğrenci arayüzü dahil) geçerli olsun diye dosyada tutulur
# ---------------------------------------------------------------------------
def paylasim_oku() -> Optional[dict]:
    try:
        veri = _oku_json(PAYLASIM)
        return veri if isinstance(veri, dict) and veri.get("lecture_id") else None
    except Exception:
        return None


def paylasim_yaz(lecture_id: str, kaynak: str, notlar: dict, ders: Optional[dict] = None) -> None:
    """Öğretmen onayladı: düzenlenmiş notlar öğrencilere açılır. ders: başlık bilgileri (title, subject, ...)."""
    veri = {"lecture_id": lecture_id, "kaynak": kaynak, "notlar": notlar, "ders": ders or {},
            "onay_zamani": datetime.now().isoformat(timespec="seconds")}
    gecici = PAYLASIM.with_suffix(".tmp")
    gecici.write_text(json.dumps(veri, ensure_ascii=False), encoding="utf-8")
    os.replace(gecici, PAYLASIM)


def paylasim_sil() -> None:
    PAYLASIM.unlink(missing_ok=True)


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
    izlendi = None
    try:
        ham = notlar_ham()
        izlendi = ham.get("odak_izlendi")
        seri = [(float(v["saniye"]), float(v["skor"])) for v in ham.get("odak_serisi", [])]
    except Exception:
        seri = []

    # Eski kayıtlarda (odak_izlendi alanı yokken) en yeni ölçüm dosyasına bakılır. Yeni kayıtlarda bakılmaz:
    # odak izlenmeden işlenen bir derse, önceki bir dersin ölçümü karışmasın.
    if not seri and izlendi is None:
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
