"""
Arayüz ile backend arasındaki orkestrasyon katmanı.

Veri yerleşimi (Privacy by Design):
* Ders içeriği (transkript, ders notu) öğretmene ait, kişisel veri değil
  → st.cache_data ile paylaşımlı önbellekte tutulabilir.
* Öğrencinin odak serisi, düşüş aralıkları ve kartları kişisel veri
  → YALNIZCA st.session_state'te, yani bu tarayıcı oturumunun belleğinde.
  st.cache_data tüm kullanıcılar arasında paylaşıldığı için burada KULLANILMAZ.
"""

from __future__ import annotations

import dataclasses
from typing import List, Tuple

import streamlit as st

from core.config import settings
from core.schemas import FocusSample, GapWindow, Lecture, LectureNotes, RecoveryCard
from engine.matcher import TimeSeriesMatcher
from llm.client import LLMService
from sensing.focus.simulated import SimulatedFocusSource
from sensing.speech.simulated import SimulatedSpeechSource
from ui import gercek_veri

STUDENT_KEYS = ("focus_raw", "focus_smooth", "gaps", "gap_parts", "cards", "llm_chars_sent")

# Veri kaynakları
KAYNAK_DEMO = "demo"
KAYNAK_GERCEK = "gercek"


# ---------------------------------------------------------------------------
# Öğretmen tarafı (paylaşımlı önbellek uygun)
# ---------------------------------------------------------------------------
@st.cache_resource
def get_llm() -> LLMService:
    return LLMService()


@st.cache_data(show_spinner=False)
def load_lecture(kaynak: str = KAYNAK_DEMO, imza: str = "") -> Lecture:
    """imza: gerçek veri dosyaları değişince önbelleği tazelemek için (gercek_veri.veri_imzasi())."""
    if kaynak == KAYNAK_GERCEK:
        return gercek_veri.gercek_ders()
    return SimulatedSpeechSource().lecture()


@st.cache_data(show_spinner="Ders notları hazırlanıyor…")
def load_lecture_notes(_lecture: Lecture, lecture_id: str, kaynak: str = KAYNAK_DEMO, imza: str = "") -> LectureNotes:
    if kaynak == KAYNAK_GERCEK:
        # Notlar ses hattında (notlar.py, Gemini) zaten üretildi; tekrar LLM'e gitmeye gerek yok
        return gercek_veri.gercek_notlar()
    return get_llm().generate_lecture_notes(_lecture)


def llm_mode_label() -> str:
    llm = get_llm()
    if llm.config.use_mock or llm.client is None:
        return "Mock (çevrimdışı demo)"
    ad = {"gemini": "Gemini API", "anthropic": "Claude API"}.get(llm.config.provider, llm.config.provider)
    return f"{ad} · {llm.active_model or llm.config.model}"


# ---------------------------------------------------------------------------
# Öğrenci tarafı (yalnızca bu oturum)
# ---------------------------------------------------------------------------
def student_data_present() -> bool:
    return "focus_raw" in st.session_state


def run_student_pipeline(lecture: Lecture, threshold: float, force: bool = False,
                         kaynak: str = KAYNAK_DEMO, ogrenci_id: int | None = None) -> None:
    """Odak verisini üretir, eşleştirir ve kartları oluşturur. Sonuçlar session_state'e yazılır.

    Eşik değiştiğinde yalnızca korelasyon ve (gerekirse) kartlar yeniden hesaplanır;
    aynı aralık için daha önce üretilmiş kart tekrar LLM'e gönderilmez.
    Ders (veri kaynağı ya da yeni kayıt) değişirse her şey baştan hesaplanır.
    """
    ss = st.session_state

    if ss.get("focus_lecture_id") != lecture.lecture_id or ss.get("focus_ogrenci") != ogrenci_id:
        force = True

    if force or "focus_raw" not in ss:
        ss.focus_kisisel = False
        ss.focus_durum = "sinif"   # sinif: sınıf ortalaması | kisisel: kendi ölçümü | yok: derste görülmedi (0)
        kisisel, derste_yok = [], False
        if kaynak == KAYNAK_GERCEK and ogrenci_id is not None:
            # Rızalı kayıtlı öğrenci: sınıf kamerasının YALNIZCA ona ait ölçümleri
            from core import ogrenci_db
            kayit = gercek_veri.odak_kaydi()
            kisisel = [FocusSample(timestamp=round(t, 2), focus_score=round(min(100.0, max(0.0, sk)), 1))
                       for t, sk in ogrenci_db.kisisel_odak(kayit, ogrenci_id)]
            # Kamerada arandı ama hiç görülmedi: derste yok -> odak 0 (notları yine alır)
            derste_yok = not kisisel and ogrenci_db.beklenen_mi(kayit, ogrenci_id)
        if kisisel:
            ss.focus_raw, ss.focus_kisisel, ss.focus_durum = kisisel, True, "kisisel"
        elif derste_yok:
            ss.focus_raw, ss.focus_durum = [], "yok"
        elif kaynak == KAYNAK_GERCEK:
            ss.focus_raw = gercek_veri.gercek_odak()
        else:
            ss.focus_raw = SimulatedFocusSource(
                duration=lecture.duration, sample_rate_hz=settings.focus.sample_rate_hz
            ).collect()
        ss.focus_lecture_id = lecture.lecture_id
        ss.focus_ogrenci = ogrenci_id
        for k in [k for k in ss.keys() if str(k).startswith("quiz_") and not str(k).startswith("quiz_genel_")]:
            del ss[k]  # önceki dersin kart cevapları
        ss.pop("card_choice", None)
        ss.pop("clicked_segment", None)
        ss.card_cache = {}
        ss.llm_chars_sent = 0
        ss.pop("threshold_used", None)

    if ss.get("threshold_used") == threshold and "gaps" in ss:
        return
    if ss.get("focus_durum") == "yok":  # derste değildi: kart üretilmez (yapay zekâ kotası da harcanmaz)
        ss.focus_smooth, ss.gaps, ss.gap_parts, ss.cards = [], [], [], []
        ss.threshold_used = threshold
        return

    cfg = dataclasses.replace(settings.focus, threshold=threshold)
    matcher = TimeSeriesMatcher(config=cfg)
    ss.focus_smooth = matcher.smooth_focus_samples(ss.focus_raw)
    ss.gaps, ss.gap_parts = group_gaps_by_segment(matcher.match_with_lecture(ss.focus_raw, lecture))

    cards: List[RecoveryCard] = []
    llm = get_llm()
    for gap in ss.gaps:
        key = (gap.segment_index, gap.start_time, gap.end_time)
        if key not in ss.card_cache:
            with st.spinner(f"“{gap.topic}” için Eksik Tamamlama Kartı hazırlanıyor…"):
                ss.card_cache[key] = llm.generate_recovery_card(gap)
            # LLM'e giden tek içerik: o aralıkta anlatılan ders metni
            ss.llm_chars_sent += len(gap.missed_transcript)
        cards.append(ss.card_cache[key])
    ss.cards = cards
    ss.threshold_used = threshold

    # Eski seçim artık geçersizse sıfırla
    if ss.get("card_choice") is not None and ss.card_choice >= len(cards):
        ss.card_choice = 0 if cards else None


def sinif_odagi(lecture: Lecture, threshold: float, kaynak: str = KAYNAK_DEMO) -> dict | None:
    """Öğretmen paneli için sınıf odağı: ham + yumuşatılmış seri ve eşik altı aralıklar (LLM çağrısı yok).
    Odak verisi yoksa None."""
    ss = st.session_state
    anahtar = (lecture.lecture_id, kaynak)
    if ss.get("sinif_odak_anahtar") != anahtar:
        if kaynak == KAYNAK_GERCEK:
            ham = gercek_veri.gercek_odak()
        else:
            ham = SimulatedFocusSource(duration=lecture.duration,
                                       sample_rate_hz=settings.focus.sample_rate_hz).collect()
        ss.sinif_odak_ham, ss.sinif_odak_anahtar = ham, anahtar
    ham = ss.sinif_odak_ham
    if not ham:
        return None
    matcher = TimeSeriesMatcher(config=dataclasses.replace(settings.focus, threshold=threshold))
    gaps, parts = group_gaps_by_segment(matcher.match_with_lecture(ham, lecture))
    return {"raw": ham, "smooth": matcher.smooth_focus_samples(ham), "gaps": gaps, "parts": parts}


def group_gaps_by_segment(gaps: List[GapWindow]) -> Tuple[List[GapWindow], List[Tuple[GapWindow, int]]]:
    """Aynı konu bölümündeki birden fazla düşüşü tek karta indirger.

    Dönüş:
      merged → kart başına bir GapWindow (LLM'e bu gider)
      parts  → (gerçek düşüş aralığı, kart indeksi); grafikte gölgeleme ve tıklama için
    """
    by_seg: dict[int, List[GapWindow]] = {}
    for g in gaps:
        by_seg.setdefault(g.segment_index, []).append(g)

    merged: List[GapWindow] = []
    parts: List[Tuple[GapWindow, int]] = []
    for card_idx, seg_idx in enumerate(sorted(by_seg)):
        group = by_seg[seg_idx]
        total = sum(g.duration for g in group) or 1.0
        merged.append(group[0].model_copy(update={
            "start_time": min(g.start_time for g in group),
            "end_time": max(g.end_time for g in group),
            "mean_focus": round(sum(g.mean_focus * g.duration for g in group) / total, 1),
            "min_focus": min(g.min_focus for g in group),
            "coverage": round(min(1.0, sum(g.coverage for g in group)), 2),
            "missed_transcript": " … ".join(g.missed_transcript for g in group),
        }))
        parts.extend((g, card_idx) for g in group)
    return merged, parts


def wipe_student_data() -> None:
    """'Verilerimi sil': öğrenciye ait her şeyi oturum belleğinden kaldırır."""
    for k in list(st.session_state.keys()):
        if k in STUDENT_KEYS or k in ("card_cache", "threshold_used", "card_choice", "chart_sel_seen",
                                      "focus_lecture_id", "focus_ogrenci", "focus_kisisel", "focus_durum") \
                or str(k).startswith("quiz_"):
            del st.session_state[k]


def dusuk_odak(smooth: List[FocusSample], threshold: float) -> dict:
    """Yumuşatılmış odağın eşiğin altında kaldığı TOPLAM süre ve aralıklar.
    (Kartlardan bağımsız: kısa düşüşler ve konu bölümü bulunamayan anlar da sayılır.)"""
    if not smooth:
        return {"toplam_s": 0.0, "araliklar": [], "en_uzun": None}
    ts = [s.timestamp for s in smooth]
    farklar = sorted(b - a for a, b in zip(ts, ts[1:]) if b > a)
    dt = farklar[len(farklar) // 2] if farklar else 1.0
    araliklar, bas, en_dusuk = [], None, 100.0
    for i, s in enumerate(smooth):
        if s.focus_score < threshold:
            if bas is None:
                bas, en_dusuk = s.timestamp, s.focus_score
            en_dusuk = min(en_dusuk, s.focus_score)
            son = s.timestamp
        elif bas is not None:
            araliklar.append((bas, son + dt, en_dusuk))
            bas = None
    if bas is not None:
        araliklar.append((bas, son + dt, en_dusuk))
    toplam = sum(b - a for a, b, _ in araliklar)  # toplam süre: her eşik altı an sayılır
    # Sayım/liste için eşiğin etrafında gidip gelen kısa kopuklukları (< 6 sn arayla) tek düşüş say
    birlesik = []
    for a, b, m in araliklar:
        if birlesik and a - birlesik[-1][1] < 6:
            birlesik[-1] = (birlesik[-1][0], b, min(birlesik[-1][2], m))
        else:
            birlesik.append((a, b, m))
    araliklar = birlesik
    return {"toplam_s": toplam, "araliklar": araliklar,
            "en_uzun": max(araliklar, key=lambda a: a[1] - a[0]) if araliklar else None}


def focus_stats(raw: List[FocusSample], gaps: List[GapWindow],
                parts: List[Tuple[GapWindow, int]], smooth: List[FocusSample] | None = None,
                threshold: float | None = None) -> dict:
    scores = [s.focus_score for s in raw]
    missed = (dusuk_odak(smooth, threshold)["toplam_s"] if smooth and threshold is not None
              else sum(g.duration for g, _ in parts))
    return {
        "mean": sum(scores) / len(scores) if scores else 0.0,
        "missed_s": missed,  # odağın eşik altında kaldığı toplam süre
        "n_gaps": len(gaps),
    }
