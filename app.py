"""
Multimodal Kişiselleştirilmiş Ders Asistanı — Streamlit giriş noktası.

Çalıştırma:  streamlit run app.py

İki ayrı arayüz vardır (adres çubuğundaki ?rol=... ile seçilir; giriş sayfası bunu sorar):
    ?rol=ogretmen  -> Öğretmen: dersi başlat/bitir, ders özeti (öğrenci sayısı, sınıf odağı), notları düzenle ve paylaş
    ?rol=ogrenci   -> Öğrenci: öğretmenin paylaştığı notlar, kendi eksik tamamlama kartları, mini quiz

Öğretmenin "paylaş" onayı paylasim.json dosyasında tutulur; böylece öğrenci başka bir tarayıcıdan/cihazdan
açsa da aynı dersi görür. .env içinde OGRETMEN_SIFRESI tanımlıysa öğretmen arayüzü bu şifreyi ister.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import streamlit as st

st.set_page_config(page_title="Ders Asistanı", page_icon="🎓", layout="wide")

from core.config import settings  # noqa: E402
from core.schemas import LectureNotes  # noqa: E402
from ui import components as ui  # noqa: E402
from ui import ders_kontrol  # noqa: E402
from ui import gercek_veri  # noqa: E402
from ui import ogrenci_kayit  # noqa: E402
from core import ogrenci_db  # noqa: E402
from ui import pipeline as pl  # noqa: E402

ui.inject_css()
ss = st.session_state
ROLLER = {"ogretmen": "👩‍🏫 Öğretmen", "ogrenci": "🧑‍🎓 Öğrenci"}


# ---------------------------------------------------------------------------
# Ortak yardımcılar
# ---------------------------------------------------------------------------
def rol_sec(rol: str | None) -> None:
    if rol:
        st.query_params["rol"] = rol
    else:
        st.query_params.clear()
    st.rerun()


def baslik(alt: str, rol: str) -> None:
    st.markdown(f'<p class="app-title">🎓 Ders Asistanı <span style="font-weight:400;color:#6B7385">· '
                f'{ROLLER[rol]}</span></p>', unsafe_allow_html=True)
    st.markdown(f'<p class="app-sub">{alt}</p>', unsafe_allow_html=True)


def yan_panel_rol(rol: str) -> None:
    st.sidebar.markdown(f"### {ROLLER[rol]} arayüzü")
    if st.sidebar.button("↩ Çıkış / rol değiştir", width="stretch"):
        ss.pop("ogretmen_giris", None)
        ss.pop("ogrenci", None)
        pl.wipe_student_data()
        rol_sec(None)
    st.sidebar.divider()


def dersi_yukle(kaynak: str):
    """(lecture, notes, kaynak). Gerçek ders dosyaları bozuksa demo verisine düşer."""
    imza = gercek_veri.veri_imzasi() if kaynak == pl.KAYNAK_GERCEK else ""
    try:
        lecture = pl.load_lecture(kaynak, imza)
        return lecture, pl.load_lecture_notes(lecture, lecture.lecture_id, kaynak, imza), kaynak
    except Exception as e:  # bozuk/yarım yazılmış ders dosyası uygulamayı çökertmesin
        if kaynak != pl.KAYNAK_GERCEK:
            raise
        st.sidebar.error(f"Gerçek ders dosyaları okunamadı ({e.__class__.__name__}: {str(e)[:200]}). "
                         "Demo verisi gösteriliyor.")
        lecture = pl.load_lecture(pl.KAYNAK_DEMO, "")
        return lecture, pl.load_lecture_notes(lecture, lecture.lecture_id, pl.KAYNAK_DEMO, ""), pl.KAYNAK_DEMO


# ---------------------------------------------------------------------------
# Giriş sayfası
# ---------------------------------------------------------------------------
def giris_sayfasi() -> None:
    st.markdown('<p class="app-title">🎓 Ders Asistanı</p>', unsafe_allow_html=True)
    st.markdown('<p class="app-sub">Nasıl devam etmek istersiniz?</p>', unsafe_allow_html=True)
    ui.render_privacy_strip()
    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.markdown('<div class="rol-kart"><h3>👩‍🏫 Öğretmen</h3><p>Dersi başlatın ve bitirin; ders sonunda öğrenci '
                    'sayısını, sınıfın odak ortalamasını ve otomatik ders notlarını görün; notları düzenleyip '
                    'öğrencilerle paylaşın.</p></div>', unsafe_allow_html=True)
        if st.button("Öğretmen olarak gir", type="primary", width="stretch"):
            rol_sec("ogretmen")
    with c2:
        st.markdown('<div class="rol-kart"><h3>🧑‍🎓 Öğrenci</h3><p>Öğretmeninizin verdiği şifreyle girin; paylaşılan ders notlarını okuyun, '
                    '<b>kendi</b> odak raporunuzu, dikkatinizin dağıldığı konular için eksik tamamlama kartlarını ve '
                    'ders sonu mini quizi görün.'
                    '</p></div>', unsafe_allow_html=True)
        if st.button("Öğrenci olarak gir", width="stretch"):
            rol_sec("ogrenci")


# ---------------------------------------------------------------------------
# Öğretmen arayüzü
# ---------------------------------------------------------------------------
def ogretmen_sifre_kapisi() -> None:
    sifre = (os.getenv("OGRETMEN_SIFRESI") or "").strip()
    if not sifre or ss.get("ogretmen_giris"):
        return
    baslik("Öğretmen girişi", "ogretmen")
    with st.form("ogretmen_giris_formu"):
        girilen = st.text_input("Öğretmen şifresi", type="password")
        if st.form_submit_button("Giriş yap", type="primary"):
            if girilen == sifre:
                ss.ogretmen_giris = True
                st.rerun()
            st.error("Şifre yanlış.")
    if st.button("↩ Geri"):
        rol_sec(None)
    st.stop()


def ogretmen_arayuzu() -> None:
    ogretmen_sifre_kapisi()
    yan_panel_rol("ogretmen")

    # --- Yan panel: veri kaynağı ---
    st.sidebar.markdown("### 📂 Gösterilen ders")
    etiket = {pl.KAYNAK_GERCEK: "🎙️ Son ders kaydı", pl.KAYNAK_DEMO: "🧪 Demo (türev dersi)"}
    eksik = gercek_veri.eksik_dosyalar()
    if ss.pop("kaynaga_gec", False) or "veri_kaynagi" not in ss:
        # İlk açılışta gerçek ders varsa onu göster; yeni ders işlenince otomatik olarak ona geç
        ss.veri_kaynagi = pl.KAYNAK_GERCEK if not eksik else pl.KAYNAK_DEMO
    kaynak = st.sidebar.radio("Gösterilen ders", list(etiket), format_func=etiket.get, key="veri_kaynagi",
                              label_visibility="collapsed",
                              help="Son ders kaydı: 'Dersi Başlat' ile kaydettiğiniz en son ders. "
                                   "Demo: hazır türev dersi senaryosu (yedek).")
    if kaynak == pl.KAYNAK_GERCEK and eksik:
        st.sidebar.info("Henüz kaydedilmiş bir ders yok; demo dersi gösteriliyor.")
        kaynak = pl.KAYNAK_DEMO
    if kaynak == pl.KAYNAK_GERCEK and st.sidebar.button("🔄 Son kaydı yeniden yükle", width="stretch"):
        st.cache_data.clear()
        st.rerun()

    lecture, notes, kaynak = dersi_yukle(kaynak)
    gercek = kaynak == pl.KAYNAK_GERCEK

    st.sidebar.divider()
    st.sidebar.markdown("### ⚙️ Odak eşiği")
    threshold = st.sidebar.slider(
        "Odak eşiği", 30, 70, int(settings.focus.threshold), step=5, label_visibility="collapsed",
        help="Sınıfın yumuşatılmış odak ortalaması bu değerin altına inerse 'dikkat düşük' sayılır.")
    st.sidebar.divider()
    ui.render_privacy_sidebar(pl.llm_mode_label(), None, lambda: None)

    # --- Sayfa ---
    baslik(f"{lecture.subject} · {lecture.grade_level or ''} · {lecture.title}", "ogretmen")
    ui.render_privacy_strip()
    ders_kontrol.render_ders_kaydi()
    ogrenci_kayit.render_ogrenci_kayit()

    bilgi = gercek_veri.ders_bilgisi() if gercek else {}
    if gercek and bilgi.get("ses_kaydedildi", True) and not bilgi.get("ders_algilandi", True):
        st.warning("🎙️ Bu kayıtta bir ders anlatımı algılanamadı, bu yüzden not üretilmedi. Sayfanın altındaki ham "
                   "transkripte bakabilir; mikrofona yakın ve net konuşarak yeniden kaydedebilirsiniz.")
    oneri = gercek_veri.ogretmen_onerisi() if gercek else None
    if oneri:
        st.info(f"💡 **Öğretmene not:** {oneri}")

    ui.render_ders_ozeti(lecture, bilgi, pl.sinif_odagi(lecture, float(threshold), kaynak), float(threshold))
    if gercek:
        gorulen, beklenen = ogrenci_db.katilim(gercek_veri.odak_kaydi())
        if beklenen:
            st.caption(f"🔒 Yüz kaydı olan **{beklenen}** öğrenciden **{gorulen}**'i derste tanındı ve kişisel odak raporu "
                       f"oluştu (raporu yalnızca öğrencinin kendisi görür). Derste görülmeyen {beklenen - gorulen} "
                       "öğrencinin odak puanı 0 sayılır; ders notları onlara da gider.")
    st.divider()

    if gercek and not bilgi.get("ses_kaydedildi", True):
        st.info("📝 Bu derste ses dinlenmediği için ders notu üretilmedi. Not almak için dersi başlatırken "
                "“Ses dinlenip metne çevrilsin mi?” sorusunu açık bırakın.")
        return

    if gercek and not bilgi.get("ders_algilandi", True):
        with st.expander("Ham transkript (ses tanıma çıktısı)", expanded=True):
            st.text(lecture.full_transcript)
        return

    paylasim = gercek_veri.paylasim_oku()
    onayli = bool(paylasim) and paylasim.get("lecture_id") == lecture.lecture_id
    if onayli:
        try:  # paylaşılan (öğretmenin düzenlediği) hali göster
            notes = LectureNotes.model_validate(paylasim["notlar"])
        except Exception:
            pass
    elif paylasim:
        st.caption(f"Şu anda öğrencilerle paylaşılan ders: **{(paylasim.get('ders') or {}).get('title', '—')}** "
                   f"({str(paylasim.get('onay_zamani', ''))[:16].replace('T', ' ')}). "
                   "Bu dersi onaylarsanız onun yerine geçer.")

    def onayla(son: LectureNotes) -> None:
        gercek_veri.paylasim_yaz(lecture.lecture_id, kaynak, son.model_copy(update={"approved": True}).model_dump(),
                                 {"title": lecture.title, "subject": lecture.subject,
                                  "grade_level": lecture.grade_level, "duration": lecture.duration})

    ui.render_teacher_view(lecture, notes, onayli, onayla, gercek_veri.paylasim_sil)


# ---------------------------------------------------------------------------
# Öğrenci arayüzü
# ---------------------------------------------------------------------------
@st.fragment(run_every=10)
def _paylasim_bekcisi() -> None:
    """Öğretmen yeni bir ders paylaşırsa (ya da geri alırsa) öğrenci sayfası kendiliğinden yenilenir."""
    p = gercek_veri.paylasim_oku()
    imza = (p or {}).get("onay_zamani")
    if "gorulen_paylasim" not in ss:
        ss.gorulen_paylasim = imza
    elif imza != ss.gorulen_paylasim:
        ss.gorulen_paylasim = imza
        st.cache_data.clear()
        st.rerun(scope="app")


def ogrenci_giris_kapisi() -> None:
    """Kayıtlı öğrenci kendi şifresiyle girer (kişisel odak raporu); kayıtsız öğrenci şifresiz girer (sınıf ortalaması)."""
    if ss.get("ogrenci"):
        return
    baslik("Öğrenci girişi", "ogrenci")
    ui.render_privacy_strip()
    c1, c2 = st.columns(2, gap="large")
    with c1:
        with st.container(border=True):
            st.markdown("#### 🔑 Kayıtlı öğrenci")
            st.caption("Öğretmeninizin size verdiği şifreyle girin: ders notları + **kendi** odak raporunuz ve kartlarınız.")
            with st.form("ogrenci_giris_formu"):
                sifre = st.text_input("Şifre", type="password", placeholder="Örn. 7KQ-M3P")
                if st.form_submit_button("Giriş yap", type="primary", width="stretch"):
                    o = ogrenci_db.giris(sifre)
                    if o:
                        pl.wipe_student_data()  # önceki öğrencinin oturum verisi kalmasın
                        ss.ogrenci = o
                        st.rerun()
                    st.error("Şifre bulunamadı. Büyük/küçük harf ve tire önemli değil; öğretmeninizden kontrol etmesini isteyin.")
    with c2:
        with st.container(border=True):
            st.markdown("#### 👤 Kayıtsız öğrenci")
            st.caption("Yüz kaydı olmayan öğrenciler: ders notları, **sınıfın ortalama** odağına göre hazırlanan kartlar "
                       "ve mini quiz. Kimlik sorulmaz, kişisel veri tutulmaz.")
            if st.button("Kayıtsız öğrenci olarak devam et", width="stretch"):
                pl.wipe_student_data()
                ss.ogrenci = {"id": None, "ad": "Kayıtsız öğrenci", "misafir": True}
                st.rerun()
    if st.button("↩ Geri"):
        rol_sec(None)
    st.stop()


def ogrenci_yan_paneli() -> None:
    o = ss.ogrenci
    st.sidebar.markdown(f"### 👤 {o['ad']}")
    if st.sidebar.button("Çıkış yap", width="stretch"):
        ss.pop("ogrenci", None)
        pl.wipe_student_data()
        st.rerun()
    if o.get("misafir"):
        st.sidebar.caption("Kayıtsız girişte kişisel veri tutulmaz.")
        st.sidebar.divider()
        return
    with st.sidebar.expander("🗑 Kişisel verilerimi kalıcı olarak sil"):
        st.caption("Yüz izin ve bütün derslerdeki kişisel odak ölçümlerin silinir, kaydın kapanır. Geri alınamaz.")
        if st.checkbox("Eminim", key="kendini_sil_onay") and st.button("Sil", type="primary"):
            ogrenci_db.ogrenci_sil(o["id"])
            ss.pop("ogrenci", None)
            pl.wipe_student_data()
            st.rerun()
    st.sidebar.divider()


def ogrenci_arayuzu() -> None:
    yan_panel_rol("ogrenci")
    ogrenci_giris_kapisi()
    ogrenci_yan_paneli()
    ogrenci_id = ss.ogrenci["id"]
    _paylasim_bekcisi()
    paylasim = gercek_veri.paylasim_oku()

    def yan_panel_gizlilik() -> None:
        ledger = None
        if pl.student_data_present():
            ledger = {"samples": len(ss.focus_raw), "llm_chars": ss.get("llm_chars_sent", 0)}

        def _wipe():
            pl.wipe_student_data()
            ss.wiped = True

        ui.render_privacy_sidebar(pl.llm_mode_label(), ledger, _wipe)

    if not paylasim:
        yan_panel_gizlilik()
        baslik("Paylaşılan ders bekleniyor", "ogrenci")
        ui.render_privacy_strip()
        st.info("Öğretmeninizin paylaştığı bir ders henüz yok. Öğretmen notları onayladığında bu sayfa "
                "kendiliğinden güncellenir.")
        return

    # Paylaşılan notlar dosyada kendi başına durur; odak / quiz içinse o dersin verisi hâlâ yerinde olmalı
    d = paylasim.get("ders") or {}
    kaynak = paylasim.get("kaynak") or pl.KAYNAK_DEMO
    lecture = None
    if kaynak == pl.KAYNAK_DEMO or not gercek_veri.eksik_dosyalar():
        aday, _, yuklenen = dersi_yukle(kaynak)
        if yuklenen == kaynak and aday.lecture_id == paylasim["lecture_id"]:
            lecture = aday
    try:
        notes = LectureNotes.model_validate(paylasim["notlar"])
    except Exception:
        st.error("Paylaşılan notlar okunamadı. Öğretmeninizden yeniden paylaşmasını isteyin.")
        return
    gosterim = lecture or SimpleNamespace(lecture_id=paylasim["lecture_id"], title=d.get("title", notes.title),
                                          subject=d.get("subject", ""), grade_level=d.get("grade_level", ""),
                                          duration=float(d.get("duration") or 0))

    baslik(f"{gosterim.subject} · {gosterim.grade_level or ''} · {gosterim.title}", "ogrenci")
    ui.render_privacy_strip()

    gercek = kaynak == pl.KAYNAK_GERCEK
    threshold = float(settings.focus.threshold)
    odak_var = lecture is not None and (not gercek or gercek_veri.ders_bilgisi().get("odak_izlendi"))
    if odak_var and ss.get("consent") and not ss.get("wiped"):
        pl.run_student_pipeline(lecture, threshold, kaynak=kaynak, ogrenci_id=ogrenci_id)  # idempotent
    yan_panel_gizlilik()
    sorular = gercek_veri.quiz() if (gercek and lecture) else []
    sekmeler = ["📒 Ders notları", "🎯 Odak ve eksik tamamlama"] + (["📝 Mini quiz"] if sorular else [])
    tabs = st.tabs(sekmeler)

    with tabs[0]:
        ui.render_student_notes(gosterim, notes)

    with tabs[1]:
        consent = ss.get("consent", False)
        if lecture is None:
            st.info("Bu dersin odak verisi artık kullanılamıyor (öğretmen yeni bir ders kaydetti). "
                    "Yeni ders paylaşıldığında burada görünecek.")
        elif not odak_var:
            st.info("Bu derste odak izlenmedi; bu yüzden eksik tamamlama kartı yok.")
        elif not consent:
            with st.container(border=True):
                st.markdown("#### Odak analizi için onayın gerekiyor")
                st.markdown(
                    "Sınıf kamerası ders boyunca **yalnızca dersin işlendiği cihazda** çalışır. Görüntü diske "
                    "yazılmaz, sunucuya gönderilmez. Kayıtlı öğrencinin odak puanları, kayıtta verdiği **rızayla** "
                    "**kendi adına** ayrılır ve raporu yalnızca kendisi görür. Kayıtlı olmayan kimse tanınmaz; "
                    "yalnızca anonim sınıf ortalamasına katılır."
                )
                if st.button("Onaylıyorum, analizi başlat", type="primary"):
                    ss.consent = True
                    ss.wiped = False
                    st.rerun()
        elif ss.get("wiped"):
            st.info("Odak verilerin bu oturumdan silindi. Hiçbir kopyası saklanmadı.")
            if st.button("Analizi yeniden başlat"):
                ss.wiped = False
                pl.run_student_pipeline(lecture, threshold, force=True, kaynak=kaynak, ogrenci_id=ogrenci_id)
                st.rerun()
        elif ss.get("focus_durum") == "yok":
            m1, m2 = st.columns([1, 3])
            m1.metric("Odak puanın", "0/100")
            m2.warning(f"**{ss.ogrenci['ad']}**, bu derste kamerada görünmedin (derste değildin ya da kamera seni "
                       "göremedi), bu yüzden odak puanın **0**. Dersin notlarının tamamı **📒 Ders notları** sekmesinde; "
                       "mini quiz ile konuyu kontrol edebilirsin.")
        else:
            if not ss.get("focus_raw"):
                st.warning("Bu ders için odak verisi bulunamadı.")
            else:
                if ss.get("focus_kisisel"):
                    st.success(f"🎯 Bu grafik **senin** odağın, {ss.ogrenci['ad']}. Sınıf kamerası seni kayıtta verdiğin "
                               "rızayla tanıdı; görüntün saklanmadı, yalnızca odak puanların senin adına ayrıldı.")
                elif gercek and ss.ogrenci.get("misafir"):
                    st.info("Kayıtsız girdiğin için **sınıfın ortalama** odağı ve buna göre hazırlanan kartlar gösteriliyor.")
                elif gercek:
                    st.info("Bu derste senin için kişisel ölçüm yok (ders, yüz kaydından önce yapılmış olabilir). "
                            "Aşağıda **sınıfın ortalama** odağı ve buna göre hazırlanan kartlar gösteriliyor.")
                stats = pl.focus_stats(ss.focus_raw, ss.gaps, ss.gap_parts)
                ui.render_student_view(lecture, ss.focus_raw, ss.focus_smooth, ss.gaps, ss.gap_parts, ss.cards,
                                       threshold, stats)

    if sorular:
        with tabs[2]:
            ui.render_genel_quiz(sorular, lecture.lecture_id)


# ---------------------------------------------------------------------------
# Yönlendirme
# ---------------------------------------------------------------------------
rol = st.query_params.get("rol")
if rol == "ogretmen":
    ogretmen_arayuzu()
elif rol == "ogrenci":
    ogrenci_arayuzu()
else:
    giris_sayfasi()
