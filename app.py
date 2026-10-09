"""
Multimodal Kişiselleştirilmiş Ders Asistanı — Streamlit giriş noktası.

Çalıştırma:  streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Ders Asistanı", page_icon="🎓", layout="wide")

from core.config import settings  # noqa: E402
from ui import components as ui  # noqa: E402
from ui import pipeline as pl  # noqa: E402

ui.inject_css()

# ---------------------------------------------------------------------------
# Veri
# ---------------------------------------------------------------------------
lecture = pl.load_lecture()
notes = pl.load_lecture_notes(lecture, lecture.lecture_id)

# ---------------------------------------------------------------------------
# Yan panel: demo kontrolleri + KVKK
# ---------------------------------------------------------------------------
st.sidebar.markdown("### ⚙️ Demo kontrolleri")
threshold = st.sidebar.slider(
    "Odak eşiği", 30, 70, int(settings.focus.threshold), step=5,
    help="Yumuşatılmış odak bu değerin altına inerse 'dikkat düşük' sayılır. "
         "Değiştirince korelasyon canlı olarak yeniden hesaplanır.",
)

consent = st.session_state.get("consent", False)
if consent and not st.session_state.get("wiped"):
    # İdempotent: veri varsa ve eşik değişmediyse hiçbir şey yeniden hesaplanmaz
    pl.run_student_pipeline(lecture, float(threshold))

ledger = None
if pl.student_data_present():
    ledger = {"samples": len(st.session_state.focus_raw), "llm_chars": st.session_state.get("llm_chars_sent", 0)}


def _wipe():
    pl.wipe_student_data()
    st.session_state.wiped = True


st.sidebar.divider()
ui.render_privacy_sidebar(pl.llm_mode_label(), ledger, _wipe)

# ---------------------------------------------------------------------------
# Başlık
# ---------------------------------------------------------------------------
st.markdown('<p class="app-title">🎓 Kişiselleştirilmiş Ders Asistanı</p>', unsafe_allow_html=True)
st.markdown(f'<p class="app-sub">{lecture.subject} · {lecture.grade_level} · {lecture.title}</p>',
            unsafe_allow_html=True)
ui.render_privacy_strip()

tab_teacher, tab_student = st.tabs(["👩‍🏫 Öğretmen Görünümü", "🧑‍🎓 Öğrenci Görünümü"])

with tab_teacher:
    ui.render_teacher_view(lecture, notes)

with tab_student:
    if not consent:
        with st.container(border=True):
            st.markdown("#### Odak analizi için onayın gerekiyor")
            st.markdown(
                "Kameran ders boyunca **yalnızca bu cihazda** çalışır. Görüntü diske yazılmaz, sunucuya "
                "gönderilmez; her kare bellekte 0-100 arası soyut bir odak skoruna çevrilip anında silinir. "
                "Yüz tanıma yapılmaz. Bu skorlar yalnızca bu oturumda tutulur ve istediğin an silebilirsin."
            )
            if st.button("Onaylıyorum, analizi başlat", type="primary"):
                st.session_state.consent = True
                st.session_state.wiped = False
                st.rerun()
    elif st.session_state.get("wiped"):
        st.info("Odak verilerin bu oturumdan silindi. Hiçbir kopyası saklanmadı.")
        if st.button("Demo oturumunu yeniden başlat"):
            st.session_state.wiped = False
            pl.run_student_pipeline(lecture, float(threshold), force=True)
            st.rerun()
    else:
        ss = st.session_state
        stats = pl.focus_stats(ss.focus_raw, ss.gaps, ss.gap_parts)
        ui.render_student_view(lecture, ss.focus_raw, ss.focus_smooth, ss.gaps, ss.gap_parts, ss.cards,
                              float(threshold), stats)
