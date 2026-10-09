"""
Streamlit arayüz bileşenleri.

render_privacy_strip     → üst bant: KVKK rozetleri (her sekmede görünür)
render_privacy_sidebar   → yan panel: ilkeler, oturum defteri, "Verilerimi sil"
render_teacher_view      → ders notu + tahta çözümleri onay ekranı
render_student_view      → odak grafiği (tıklanabilir) + Eksik Tamamlama Kartları
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from core.schemas import FocusSample, GapWindow, Lecture, LectureNotes, RecoveryCard

# ---------------------------------------------------------------------------
# Tasarım belirteçleri
# ---------------------------------------------------------------------------
INK = "#1F2A44"
MUTED = "#6B7385"
LINE = "#2F6FDE"
RAW = "#C3C8D2"
THRESH = "#8A93A6"
GAP_SEVERE = "#E5484D"   # ortalama odak < 30
GAP_MILD = "#F5A524"     # ortalama odak 30-eşik
OK = "#30A46C"

CSS = """
<style>
.block-container {padding-top: 2.2rem; max-width: 1200px;}
.app-title {font-size: 1.75rem; font-weight: 700; color: var(--text-color); margin: 0;}
.app-sub {color: #6B7385; margin: .15rem 0 1rem 0; font-size: .95rem;}
.badge-row {display:flex; flex-wrap:wrap; gap:.5rem; margin:.25rem 0 1.1rem 0;}
.badge {display:inline-flex; align-items:center; gap:.4rem; padding:.32rem .7rem;
        border-radius:999px; font-size:.8rem; font-weight:600; line-height:1;
        background: rgba(48,164,108,.12); color:#1E7A4F; border:1px solid rgba(48,164,108,.35);}
.badge.info {background: rgba(47,111,222,.10); color:#2459B8; border-color: rgba(47,111,222,.30);}
.pcard {border:1px solid rgba(128,128,128,.25); border-radius:12px; padding:.75rem .85rem; margin-bottom:.6rem;}
.pcard h4 {margin:0 0 .25rem 0; font-size:.9rem;}
.pcard p {margin:0; font-size:.8rem; color:#6B7385; line-height:1.35;}
.ledger {font-variant-numeric: tabular-nums; font-size:.85rem;}
.ledger td {padding:.15rem .4rem .15rem 0;}
.ledger td.v {font-weight:700; text-align:right;}
.chip {display:inline-block; padding:.12rem .55rem; margin:0 .3rem .3rem 0; border-radius:6px;
       font-size:.78rem; background: rgba(47,111,222,.10); color:#2459B8;}
.status {display:inline-block; padding:.25rem .65rem; border-radius:8px; font-size:.82rem; font-weight:600;}
.status.wait {background: rgba(245,165,36,.15); color:#A86B00;}
.status.done {background: rgba(48,164,108,.15); color:#1E7A4F;}
.missed {border-left:3px solid #E5484D; padding:.5rem .8rem; background: rgba(229,72,77,.06);
         border-radius:0 8px 8px 0; font-size:.92rem; line-height:1.5;}
.missed.mild {border-left-color:#F5A524; background: rgba(245,165,36,.07);}
.summary-box {font-size:1.02rem; line-height:1.6;}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def fmt_t(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


def gap_color(gap: GapWindow) -> str:
    return GAP_SEVERE if gap.mean_focus < 30 else GAP_MILD


# ---------------------------------------------------------------------------
# KVKK / Gizlilik
# ---------------------------------------------------------------------------
PRIVACY_BADGES = [
    ("📷", "Kamera görüntüsü diske yazılmaz", ""),
    ("🧠", "Kareler RAM'de işlenir ve anında atılır", ""),
    ("🚫", "Yüz tanıma / kimlik tespiti yok", ""),
    ("🎙️", "Ses metne çevrilince silinir", ""),
    ("💻", "Odak profili yalnızca bu oturumda", "info"),
]

PRIVACY_PRINCIPLES = [
    ("Zero-Storage Video",
     "Kamera akışı yalnızca bellekte işlenir. Fotoğraf ya da video asla diske yazılmaz, sunucuya ham görüntü gönderilmez."),
    ("Uçta Anonim Analiz",
     "Yalnızca baş açısı ve göz açıklık oranından 0-100 arası soyut bir odak skoru üretilir. Kare hemen yok edilir."),
    ("Geçici Ses İşleme",
     "Öğretmen sesi yerel Whisper ile metne çevrildiği anda geçici ses dosyası bellekten ve diskten silinir."),
    ("İstemci Taraflı Öğrenci Verisi",
     "Dikkat profili merkezi bir veritabanına gitmez; bu tarayıcı oturumu kapanınca kaybolur."),
    ("Buluta Yalnızca Ders İçeriği",
     "LLM'e yalnızca kaçırılan bölümün ders metni gider. Öğrencinin skoru, görüntüsü ya da kimliği gitmez."),
]


def render_privacy_strip() -> None:
    html = "".join(
        f'<span class="badge {cls}">{icon} {text}</span>' for icon, text, cls in PRIVACY_BADGES
    )
    st.markdown(f'<div class="badge-row">{html}</div>', unsafe_allow_html=True)


def render_privacy_sidebar(llm_label: str, ledger: Optional[dict], on_wipe) -> None:
    st.sidebar.markdown("### 🔒 Gizlilik ve KVKK")
    st.sidebar.caption("Tasarım yoluyla mahremiyet (Privacy by Design)")
    for title, body in PRIVACY_PRINCIPLES:
        st.sidebar.markdown(f'<div class="pcard"><h4>✅ {title}</h4><p>{body}</p></div>', unsafe_allow_html=True)

    st.sidebar.markdown("#### Bu oturumun veri defteri")
    if ledger:
        rows = [
            ("Diske yazılan kamera karesi", "0"),
            ("Sunucuya giden görüntü", "0 bayt"),
            ("Saklanan ses dosyası", "0"),
            ("Oturumdaki odak örneği", f"{ledger['samples']}"),
            ("LLM'e giden ders metni", f"{ledger['llm_chars']} karakter"),
            ("LLM'e giden kişisel veri", "0"),
        ]
        html = "".join(f"<tr><td>{k}</td><td class='v'>{v}</td></tr>" for k, v in rows)
        st.sidebar.markdown(f"<table class='ledger'>{html}</table>", unsafe_allow_html=True)
        st.sidebar.caption(f"LLM modu: {llm_label}")
        if st.sidebar.button("🗑️ Verilerimi sil", width="stretch",
                             help="Odak serisi, düşüş aralıkları, kartlar ve cevaplar bu oturumdan kalıcı olarak silinir."):
            on_wipe()
            st.rerun()
    else:
        st.sidebar.info("Bu oturumda öğrenciye ait veri yok.")


# ---------------------------------------------------------------------------
# Öğretmen görünümü
# ---------------------------------------------------------------------------
def _notes_to_markdown(notes: LectureNotes, lecture: Lecture) -> str:
    out = [f"# {notes.title}", f"*{lecture.subject} · {lecture.grade_level or ''}*", "", "## Özet", notes.summary, ""]
    for sec in notes.sections:
        out += [f"## {sec.topic}", sec.content]
        if sec.key_terms:
            out.append("**Anahtar kavramlar:** " + ", ".join(sec.key_terms))
        out.append("")
    if notes.board_solutions:
        out.append("## Tahta Çözümleri")
        out += [f"{i}. " + b.replace("\n", "\n   ") for i, b in enumerate(notes.board_solutions, 1)]
    return "\n".join(out)


def render_teacher_view(lecture: Lecture, notes: LectureNotes) -> None:
    ss = st.session_state
    approved = ss.get("notes_approved", False)

    head, status = st.columns([3, 1])
    with head:
        st.subheader(notes.title)
        st.caption(f"{lecture.subject} · {lecture.grade_level or ''} · {fmt_t(lecture.duration)} dk · "
                   f"{len(lecture.segments)} bölüm")
    with status:
        cls, txt = ("done", "✓ Onaylandı") if approved else ("wait", "● Onay bekliyor")
        st.markdown(f'<div style="text-align:right;margin-top:.6rem"><span class="status {cls}">{txt}</span></div>',
                    unsafe_allow_html=True)

    st.markdown("**Ders özeti**")
    summary = st.text_area("Ders özeti", notes.summary, height=90, key="note_summary",
                           label_visibility="collapsed", disabled=approved)

    st.markdown("#### Bölüm notları")
    st.caption("Notlar düzenlenebilir. Onaydan sonra kilitlenir ve paylaşıma hazır hale gelir.")
    edited_sections = []
    for i, sec in enumerate(notes.sections):
        seg = lecture.segments[i] if i < len(lecture.segments) else None
        label = f"{i + 1}. {sec.topic}" + (f"  ·  {fmt_t(seg.start_time)}–{fmt_t(seg.end_time)}" if seg else "")
        with st.expander(label, expanded=(i == 0)):
            content = st.text_area("İçerik", sec.content, height=130, key=f"note_sec_{i}",
                                   label_visibility="collapsed", disabled=approved)
            if sec.key_terms:
                st.markdown("".join(f'<span class="chip">{t}</span>' for t in sec.key_terms),
                            unsafe_allow_html=True)
            if seg:
                with st.popover("Ham transkripti göster"):
                    st.caption("STT çıktısı (düzenlenmemiş)")
                    st.write(seg.transcript)
            edited_sections.append(sec.model_copy(update={"content": content}))

    st.markdown("#### Tahta çözümleri")
    edited_board = []
    for i, sol in enumerate(notes.board_solutions):
        lines = sol.count("\n") + 1
        edited_board.append(st.text_area(f"Çözüm {i + 1}", sol, key=f"note_board_{i}", disabled=approved,
                                          height=max(68, 28 * lines + 20)))

    final = notes.model_copy(update={"summary": summary, "sections": edited_sections,
                                     "board_solutions": edited_board, "approved": approved})

    st.divider()
    c1, c2, c3 = st.columns([1.2, 1.2, 2])
    with c1:
        if not approved:
            if st.button("✓ Onayla ve paylaşıma hazırla", type="primary", width="stretch"):
                ss.notes_approved = True
                st.rerun()
        else:
            if st.button("↺ Onayı geri al", width="stretch"):
                ss.notes_approved = False
                st.rerun()
    with c2:
        st.download_button("⬇ Notları indir (.md)", _notes_to_markdown(final, lecture),
                           file_name=f"{lecture.lecture_id}-ders-notu.md", mime="text/markdown",
                           disabled=not approved, width="stretch")
    with c3:
        if approved:
            st.success("Notlar onaylandı. Öğrencilerle paylaşılabilir.")

    with st.expander("Tam ham transkript (karşılaştırma için)"):
        st.text(lecture.full_transcript)


# ---------------------------------------------------------------------------
# Öğrenci görünümü: odak grafiği
# ---------------------------------------------------------------------------
def build_focus_figure(raw: List[FocusSample], smooth: List[FocusSample], gaps: List[GapWindow],
                       lecture: Lecture, threshold: float, selected: Optional[int],
                       parts: Optional[List[Tuple[GapWindow, int]]] = None) -> go.Figure:
    """gaps: kart başına birleşik aralık; parts: (gerçek düşüş aralığı, kart indeksi)."""
    if parts is None:
        parts = [(g, i) for i, g in enumerate(gaps)]
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.84, 0.16], vertical_spacing=0.04)
    t_raw = [s.timestamp for s in raw]
    t_sm = [s.timestamp for s in smooth]
    y_sm = [s.focus_score for s in smooth]

    # Konu sınırları ve etiketleri
    for i, seg in enumerate(lecture.segments):
        if i > 0:
            fig.add_vline(x=seg.start_time, line=dict(color="rgba(128,128,128,.35)", width=1, dash="dot"), row=1, col=1)
        short = seg.topic if len(seg.topic) <= 22 else seg.topic[:20] + "…"
        fig.add_annotation(x=(seg.start_time + seg.end_time) / 2, y=104, text=f"<b>{i + 1}</b> {short}",
                           showarrow=False, font=dict(size=10, color=MUTED), row=1, col=1)

    # Odak kaybı aralıkları: gölgeli alan
    for g, i in parts:
        col = gap_color(gaps[i])
        fig.add_vrect(x0=g.start_time, x1=g.end_time, fillcolor=col,
                      opacity=0.32 if i == selected else 0.16, line_width=2 if i == selected else 0,
                      line_color=col, layer="below", row=1, col=1)

    # Ham sinyal (göz kırpma gürültüsü dahil)
    fig.add_trace(go.Scatter(x=t_raw, y=[s.focus_score for s in raw], mode="lines", name="Ham sinyal",
                             line=dict(color=RAW, width=1), hoverinfo="skip"), row=1, col=1)

    # Yumuşatılmış odak (tıklanabilir noktalar)
    fig.add_trace(go.Scatter(
        x=t_sm, y=y_sm, mode="lines+markers", name="Odak (yumuşatılmış)",
        line=dict(color=LINE, width=2.5), marker=dict(size=4, color=LINE, opacity=0.0),
        customdata=[fmt_t(t) for t in t_sm],
        hovertemplate="%{customdata} · odak %{y:.0f}<extra></extra>"), row=1, col=1)

    # Eşik çizgisi
    fig.add_hline(y=threshold, line=dict(color=THRESH, width=1.2, dash="dash"), row=1, col=1,
                  annotation_text=f"eşik {threshold:.0f}", annotation_position="bottom right",
                  annotation_font=dict(size=10, color=MUTED))

    # Kart işaretleri: tıklanınca ilgili kart açılır
    if gaps:
        fig.add_trace(go.Scatter(
            x=[_marker_x(i, parts) for i in range(len(gaps))], y=[90] * len(gaps),
            mode="markers+text", name="Eksik Tamamlama Kartı",
            marker=dict(size=[24 if i == selected else 19 for i in range(len(gaps))],
                        color=[gap_color(g) for g in gaps], symbol="square",
                        line=dict(color="white", width=1.5)),
            text=[f"{i + 1}" for i in range(len(gaps))], textposition="middle center",
            textfont=dict(color="white", size=11),
            customdata=[[g.topic, fmt_t(g.start_time), fmt_t(g.end_time)] for g in gaps],
            hovertemplate="<b>Kart %{text}</b> · %{customdata[0]}<br>%{customdata[1]}–%{customdata[2]} · tıkla ve aç<extra></extra>",
        ), row=1, col=1)

    # Isı şeridi
    fig.add_trace(go.Heatmap(
        x=t_sm, y=["Odak"], z=[y_sm], zmin=0, zmax=100, showscale=False,
        colorscale=[[0, GAP_SEVERE], [0.35, GAP_MILD], [0.55, "#E9E3B5"], [1, OK]],
        hovertemplate="%{x:.0f} sn · odak %{z:.0f}<extra></extra>"), row=2, col=1)

    ticks = list(range(0, int(lecture.duration) + 1, 60))
    fig.update_xaxes(tickvals=ticks, ticktext=[fmt_t(t) for t in ticks], showgrid=False,
                     range=[0, lecture.duration], row=2, col=1)
    fig.update_xaxes(showgrid=False, range=[0, lecture.duration], row=1, col=1)
    fig.update_yaxes(range=[0, 110], tickvals=[0, 25, 50, 75, 100], gridcolor="rgba(128,128,128,.15)",
                     title_text="Odak", row=1, col=1)
    fig.update_yaxes(showticklabels=False, row=2, col=1)
    fig.update_layout(height=430, margin=dict(l=10, r=10, t=10, b=10), hovermode="closest",
                      clickmode="event+select", dragmode=False, showlegend=True,
                      legend=dict(orientation="h", y=-0.12, x=0, font=dict(size=11)),
                      plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
    return fig


def _marker_x(card_idx: int, parts: List[Tuple[GapWindow, int]]) -> float:
    """Kart işaretini o kartın en uzun düşüş aralığının ortasına koyar."""
    g = max((p for p, i in parts if i == card_idx), key=lambda p: p.duration)
    return (g.start_time + g.end_time) / 2


def _gap_at(x: float, parts: List[Tuple[GapWindow, int]], tol: float = 3.0) -> Optional[int]:
    for g, i in parts:
        if g.start_time - tol <= x <= g.end_time + tol:
            return i
    return None


def _segment_at(x: float, lecture: Lecture) -> Optional[int]:
    for i, s in enumerate(lecture.segments):
        if s.start_time <= x < s.end_time:
            return i
    return len(lecture.segments) - 1 if x >= lecture.duration else None


def _handle_chart_click(event, parts: List[Tuple[GapWindow, int]], lecture: Lecture) -> None:
    """Grafik tıklamasını kart ya da bölüm seçimine çevirir. Aynı seçim tekrar işlenmez."""
    ss = st.session_state
    points = (event or {}).get("selection", {}).get("points", []) if event else []
    sig = tuple(round(float(p.get("x", -1)), 1) for p in points)
    if not points or sig == ss.get("chart_sel_seen"):
        return
    ss.chart_sel_seen = sig
    x = float(points[0]["x"])
    gi = _gap_at(x, parts)
    if gi is not None:
        ss.card_choice = gi
        ss.clicked_segment = None
    else:
        ss.clicked_segment = _segment_at(x, lecture)
        ss.clicked_time = x


# ---------------------------------------------------------------------------
# Öğrenci görünümü: kartlar ve quiz
# ---------------------------------------------------------------------------
def _render_quiz(card_idx: int, card: RecoveryCard) -> None:
    for qi, q in enumerate(card.questions):
        key = f"quiz_{card_idx}_{qi}"
        st.markdown(f"**Soru {qi + 1}.** {q.question}")
        choice = st.radio(f"Soru {qi + 1}", q.options, index=None, key=key, label_visibility="collapsed")
        if choice is not None:
            if q.options.index(choice) == q.correct_index:
                st.success(f"**Doğru!** {q.explanation}")
            else:
                st.error(f"**Yanlış.** Doğru cevap: {q.options[q.correct_index]}")
                st.info(q.explanation)
        if qi < len(card.questions) - 1:
            st.write("")


def quiz_progress(cards: List[RecoveryCard]) -> tuple[int, int, int]:
    total = sum(len(c.questions) for c in cards)
    answered = correct = 0
    for ci, c in enumerate(cards):
        for qi, q in enumerate(c.questions):
            v = st.session_state.get(f"quiz_{ci}_{qi}")
            if v is not None:
                answered += 1
                correct += int(q.options.index(v) == q.correct_index)
    return answered, correct, total


def _reading_seconds(text: str) -> int:
    return max(10, round(len(text.split()) / 130 * 60))  # ~130 kelime/dk sesli okuma


def _card_minutes(card: RecoveryCard) -> str:
    """Özet okuma (~130 kelime/dk) + soru başına ~30 sn çözme süresi."""
    read_s = _reading_seconds(card.summary + " " + " ".join(card.key_points))
    total_s = read_s + 30 * len(card.questions)
    return f"~{max(1, round(total_s / 60))} dk · özet {read_s} sn + {len(card.questions)} soru"


def render_card(idx: int, card: RecoveryCard, gap: GapWindow) -> None:
    col = gap_color(gap)
    with st.container(border=True):
        top_l, top_r = st.columns([3, 1.3])
        with top_l:
            st.markdown(f"<span style='color:{col};font-weight:700'>■ Kart {idx + 1}</span> &nbsp; "
                        f"<span style='font-size:1.15rem;font-weight:700'>{card.topic}</span>",
                        unsafe_allow_html=True)
            st.caption(f"Kaçırılan an: {fmt_t(gap.start_time)}–{fmt_t(gap.end_time)} · "
                       f"bölümün %{gap.coverage * 100:.0f}'ı · ortalama odak {gap.mean_focus:.0f}")
        with top_r:
            st.markdown(f"<div style='text-align:right;color:#6B7385;font-size:.85rem;margin-top:.3rem'>"
                        f"⏱ {_card_minutes(card)}</div>", unsafe_allow_html=True)

        st.markdown(f"<div class='summary-box'>{card.summary}</div>", unsafe_allow_html=True)
        if card.key_points:
            st.markdown("**Akılda kalsın**")
            st.markdown("\n".join(f"- {p}" for p in card.key_points))

        with st.expander("Derste o an ne anlatılıyordu? (transkript)"):
            st.markdown(f"<div class='missed {'mild' if col == GAP_MILD else ''}'>…{gap.missed_transcript}…</div>",
                        unsafe_allow_html=True)

        st.markdown("##### Pekiştirme soruları")
        _render_quiz(idx, card)


def render_student_view(lecture: Lecture, raw: List[FocusSample], smooth: List[FocusSample],
                        gaps: List[GapWindow], parts: List[Tuple[GapWindow, int]],
                        cards: List[RecoveryCard], threshold: float, stats: dict) -> None:
    ss = st.session_state
    answered, correct, total = quiz_progress(cards)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Ortalama odak", f"{stats['mean']:.0f}/100")
    m2.metric("Kaçırılan süre", fmt_t(stats["missed_s"]))
    m3.metric("Eksik Tamamlama Kartı", stats["n_gaps"])
    m4.metric("Pekiştirme", f"{correct}/{total} doğru" if total else "—",
              delta=f"{answered}/{total} yanıtlandı" if total else None, delta_color="off")

    st.markdown("#### Ders boyunca odak")
    st.caption("Gölgeli alanlar dikkatin eşik altına düştüğü anlar. Bir karta ya da grafikteki bir ana tıkla.")

    selected = ss.get("card_choice")
    fig = build_focus_figure(raw, smooth, gaps, lecture, threshold, selected, parts)
    event = st.plotly_chart(fig, width="stretch", on_select="rerun", selection_mode="points",
                            key="focus_chart", config={"displayModeBar": False})
    prev_choice = ss.get("card_choice")
    _handle_chart_click(event, parts, lecture)
    if ss.get("card_choice") != prev_choice:
        st.rerun()  # grafikteki vurguyu yeni seçimle yeniden çiz

    # Odak kaybı olmayan bir ana tıklandıysa: o anın transkripti
    seg_i = ss.get("clicked_segment")
    if seg_i is not None:
        seg = lecture.segments[seg_i]
        with st.container(border=True):
            c1, c2 = st.columns([5, 1])
            c1.markdown(f"**{fmt_t(ss.get('clicked_time', seg.start_time))}** · Bölüm {seg_i + 1}: {seg.topic}  "
                        f"<span class='badge' style='margin-left:.4rem'>Bu anda odak yerindeydi</span>",
                        unsafe_allow_html=True)
            if c2.button("Kapat", key="close_seg"):
                ss.clicked_segment = None
                st.rerun()
            st.write(seg.transcript)

    st.markdown("#### Eksik Tamamlama Kartları")
    if not cards:
        st.success("Bu derste eşik altında anlamlı bir odak kaybı tespit edilmedi. Harika iş!")
        return

    if ss.get("card_choice") is None:
        ss.card_choice = 0
    st.segmented_control(
        "Kart seç", options=list(range(len(cards))), key="card_choice", label_visibility="collapsed",
        format_func=lambda i: f"{i + 1} · {cards[i].topic}  ({fmt_t(gaps[i].start_time)})",
    )
    choice = ss.get("card_choice")
    if choice is None:  # segmented_control seçimi kaldırılabilir; boş bırakma
        choice = 0
    render_card(choice, cards[choice], gaps[choice])
