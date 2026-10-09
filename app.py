"""
Multimodal Kişiselleştirilmiş Ders Asistanı — Streamlit giriş noktası.

Çalıştırma:  streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Ders Asistanı", page_icon="🎓", layout="wide")

from core.config import settings  # noqa: E402
from ui import components as ui  # noqa: E402
from ui import gercek_veri  # noqa: E402
from ui import pipeline as pl
  # noqa: E402

ui.inject_css()

# ---------------------------------------------------------------------------
# Yan panel: veri kaynağı
# ---------------------------------------------------------------------------
st.sidebar.markdown("### 📂 Veri kaynağı")
KAYNAK_ETIKETI = {pl.KAYNAK_GERCEK: "🎙️ Gerçek ders (son kayıt)", pl.KAYNAK_DEMO: "🧪 Demo (türev dersi)"}
eksik = gercek_veri.eksik_dosyalar()
kaynak = st.sidebar.radio(
    "Veri kaynağı", list(KAYNAK_ETIKETI), format_func=KAYNAK_ETIKETI.get,
    index=0 if not eksik else 1, label_visibility="collapsed",
    help="Gerçek ders: transkript.py + notlar.py + görüntü işleme çıktıları. "
         "Demo: hazır türev dersi senaryosu (yedek).",
)
if kaynak == pl.KAYNAK_GERCEK and eksik:
    st.sidebar.error(
        "Gerçek ders dosyaları bulunamadı: " + ", ".join(eksik)
        + f"\n\nBu dosyaları şu klasöre koyun: {gercek_veri.VERI_KLASORU}"
    )
    kaynak = pl.KAYNAK_DEMO

imza = gercek_veri.veri_imzasi() if kaynak == pl.KAYNAK_GERCEK else ""
if kaynak == pl.KAYNAK_GERCEK:
    if st.sidebar.button("🔄 Son kaydı yeniden yükle", width="stretch",
                         help="Yeni bir ders işlendiyse (notlar.json değiştiyse) sayfayı yeni veriyle doldurur."):
        st.cache_data.clear()
        st.session_state.notes_approved = False
        st.rerun()

# ---------------------------------------------------------------------------
# Veri
# ---------------------------------------------------------------------------
lecture = pl.load_lecture(kaynak, imza)
notes = pl.load_lecture_notes(lecture, lecture.lecture_id, kaynak, imza)

# Ders değişince öğretmen onayı ve not düzenlemeleri sıfırlansın
if st.session_state.get("teacher_lecture_id") != lecture.lecture_id:
    for k in list(st.session_state.keys()):
        if str(k).startswith(("note_sec_", "note_board_")) or k in ("note_summary", "notes_approved"):
            del st.session_state[k]
    st.session_state.teacher_lecture_id = lecture.lecture_id

# ---------------------------------------------------------------------------
# Yan panel: demo kontrolleri + KVKK
# ---------------------------------------------------------------------------
st.sidebar.divider()
st.sidebar.markdown("### ⚙️ Demo kontrolleri")
threshold = st.sidebar.slider(
    "Odak eşiği", 30, 70, int(settings.focus.threshold), step=5,
    help="Yumuşatılmış odak bu değerin altına inerse 'dikkat düşük' sayılır. "
         "Değiştirince korelasyon canlı olarak yeniden hesaplanır.",
)

consent = st.session_state.get("consent", False)
if consent and not st.session_state.get("wiped"):
    # İdempotent: veri varsa ve eşik değişmediyse hiçbir şey yeniden hesaplanmaz
    pl.run_student_pipeline(lecture, float(threshold), kaynak=kaynak)

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
st.markdown(f'<p class="app-sub">{lecture.subject} · {lecture.grade_level or ""} · {lecture.title}</p>',
            unsafe_allow_html=True)
ui.render_privacy_strip()

tab_teacher, tab_student, tab_board = st.tabs(["👩‍🏫 Öğretmen Görünümü", "🧑‍🎓 Öğrenci Görünümü", "🎨 Dijital Ders Tahtası"])

with tab_teacher:
    if kaynak == pl.KAYNAK_GERCEK:
        oneri = gercek_veri.ogretmen_onerisi()
        if oneri:
            st.info(f"💡 **Öğretmene not:** {oneri}")
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
            pl.run_student_pipeline(lecture, float(threshold), force=True, kaynak=kaynak)
            st.rerun()
    elif not st.session_state.get("focus_raw"):
        st.warning("Bu ders için odak verisi bulunamadı. Görüntü işleme modülünün çıktısını "
                   "(kayitlar/dikkat_*.csv) ya da odak serisi içeren notlar.json'u ekleyip "
                   "'Son kaydı yeniden yükle'ye basın.")
    else:
        ss = st.session_state
        stats = pl.focus_stats(ss.focus_raw, ss.gaps, ss.gap_parts)
        ui.render_student_view(lecture, ss.focus_raw, ss.focus_smooth, ss.gaps, ss.gap_parts, ss.cards,
                              float(threshold), stats)

with tab_board:
    st.markdown("#### 🎨 Canlı Ders Tahtası ve Çözüm Defteri")
    ui.render_tahta_sekmesi(yukseklik=680)
