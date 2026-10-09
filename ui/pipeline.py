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

STUDENT_KEYS = ("focus_raw", "focus_smooth", "gaps", "gap_parts", "cards", "llm_chars_sent")


# ---------------------------------------------------------------------------
# Öğretmen tarafı (paylaşımlı önbellek uygun)
# ---------------------------------------------------------------------------
@st.cache_resource
def get_llm() -> LLMService:
    return LLMService()


@st.cache_data(show_spinner=False)
def load_lecture() -> Lecture:
    return SimulatedSpeechSource().lecture()


@st.cache_data(show_spinner="Ders notları hazırlanıyor…")
def load_lecture_notes(_lecture: Lecture, lecture_id: str) -> LectureNotes:
    return get_llm().generate_lecture_notes(_lecture)


def llm_mode_label() -> str:
    llm = get_llm()
    return "Mock (çevrimdışı demo)" if (llm.config.use_mock or llm.client is None) else f"Claude API · {llm.config.model}"


# ---------------------------------------------------------------------------
# Öğrenci tarafı (yalnızca bu oturum)
# ---------------------------------------------------------------------------
def student_data_present() -> bool:
    return "focus_raw" in st.session_state


def run_student_pipeline(lecture: Lecture, threshold: float, force: bool = False) -> None:
    """Odak verisini üretir, eşleştirir ve kartları oluşturur. Sonuçlar session_state'e yazılır.

    Eşik değiştiğinde yalnızca korelasyon ve (gerekirse) kartlar yeniden hesaplanır;
    aynı aralık için daha önce üretilmiş kart tekrar LLM'e gönderilmez.
    """
    ss = st.session_state

    if force or "focus_raw" not in ss:
        ss.focus_raw = SimulatedFocusSource(
            duration=lecture.duration, sample_rate_hz=settings.focus.sample_rate_hz
        ).collect()
        ss.card_cache = {}
        ss.llm_chars_sent = 0
        ss.pop("threshold_used", None)

    if ss.get("threshold_used") == threshold and "gaps" in ss:
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
        if k in STUDENT_KEYS or k in ("card_cache", "threshold_used", "card_choice", "chart_sel_seen") or str(k).startswith("quiz_"):
            del st.session_state[k]


def focus_stats(raw: List[FocusSample], gaps: List[GapWindow],
                parts: List[Tuple[GapWindow, int]]) -> dict:
    scores = [s.focus_score for s in raw]
    return {
        "mean": sum(scores) / len(scores) if scores else 0.0,
        "missed_s": sum(g.duration for g, _ in parts),  # gerçek düşüş süreleri
        "n_gaps": len(gaps),
    }
