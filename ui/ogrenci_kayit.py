"""
Öğretmen paneli: rızalı öğrenci kaydı (kişisel odak raporu için)
================================================================
- Öğretmen öğrencinin adını yazar, rızasını işaretler, kameradan 3-4 yüz örneği alır.
- Fotoğraflar yalnızca bu ekranda bellekte durur; kayıtta yalnızca yüz izi (sayılar) saklanır.
- Her öğrenciye FARKLI bir şifre üretilir; öğretmen bunu öğrenciye verir. Şifre yalnızca bir kez gösterilir
  (unutulursa "Yeni şifre" ile yenilenir).
"""

from __future__ import annotations

import html

import numpy as np
import streamlit as st

from core import ogrenci_db

EN_AZ_ORNEK = 2
EN_COK_ORNEK = 5


@st.cache_resource(show_spinner="Yüz modeli yükleniyor…")
def _kimlik():
    from sensing.focus.yuz_kimligi import YuzKimligi
    return YuzKimligi()


def _coz(dosya) -> np.ndarray | None:
    import cv2
    return cv2.imdecode(np.frombuffer(dosya.getvalue(), np.uint8), cv2.IMREAD_COLOR)


def _ornek_ekle(goruntu) -> None:
    ss = st.session_state
    if goruntu is None:
        st.error("Fotoğraf okunamadı.")
        return
    yuzler = _kimlik().yuzleri_bul(goruntu)
    if len(yuzler) == 0:
        ss.kayit_mesaj = ("warning", "Bu fotoğrafta yüz bulunamadı; yüz kameraya dönük ve aydınlık olacak şekilde tekrar çekin.")
        return
    ss.kayit_ornekler = ss.get("kayit_ornekler", []) + [goruntu]
    ss.kayit_mesaj = ("success", f"Örnek alındı ({len(ss.kayit_ornekler)}). "
                                 + ("Bir sonrakinde başını hafifçe sağa ya da sola çevir." if len(ss.kayit_ornekler) < 3 else ""))


def _sifirla() -> None:
    ss = st.session_state
    for k in ("kayit_ornekler", "kayit_mesaj"):
        ss.pop(k, None)
    ss.kayit_sayac = ss.get("kayit_sayac", 0) + 1  # kamera / ad / rıza alanlarını temizler


def render_ogrenci_kayit() -> None:
    ss = st.session_state
    liste = ogrenci_db.ogrenciler()
    baslik = f"👥 Rızalı öğrenci kaydı · kişisel odak raporu ({len(liste)} kayıtlı)"
    with st.expander(baslik, expanded=ss.get("kayit_acik", False)):
        st.caption(
            "Yalnızca **açık rıza veren** öğrenciler kaydedilir. Kayıtlı öğrencinin odağı ders sırasında ayrıca "
            "**kendi adına** ölçülür ve raporunu **yalnızca kendisi** şifresiyle görür. Kayıtlı olmayan herkes "
            "tanınmaz; yalnızca anonim sınıf ortalamasına katılır. Fotoğraf saklanmaz, yalnızca geri döndürülemez "
            "bir yüz izi (128 sayı) tutulur ve tek tıkla silinebilir.")

        if ss.get("son_sifre"):
            ad, sifre = ss.son_sifre
            st.success(f"**{ad}** için şifre:")
            st.markdown(f"<div style='font-size:2rem;font-weight:700;letter-spacing:.15em;"
                        f"font-variant-numeric:tabular-nums'>{sifre}</div>", unsafe_allow_html=True)
            st.caption("Bu şifreyi öğrenciye verin. Güvenlik için yalnızca şimdi gösterilir; unutulursa listeden "
                       "“Yeni şifre” ile yenileyebilirsiniz.")
            if st.button("Tamam, şifreyi verdim"):
                ss.pop("son_sifre", None)
                st.rerun()
            st.divider()

        # --- Kayıtlı öğrenciler ---
        if liste:
            st.markdown("**Kayıtlı öğrenciler**")
            for o in liste:
                c1, c2, c3 = st.columns([3, 1.2, 1])
                c1.markdown(f"**{html.escape(o['ad'])}**  \n<span style='color:#6B7385;font-size:.85rem'>rıza: "
                            f"{o['riza_zamani'][:16].replace('T', ' ')} · {o['iz_sayisi']} yüz örneği"
                            f"{' · 🔒 şifreli' if o.get('sifreli') else ''}</span>",
                            unsafe_allow_html=True)
                if c2.button("🔑 Yeni şifre", key=f"sifre_{o['id']}", width="stretch"):
                    ss.son_sifre = (o["ad"], ogrenci_db.sifre_yenile(o["id"]))
                    ss.kayit_acik = True
                    st.rerun()
                if c3.button("🗑 Sil", key=f"sil_{o['id']}", width="stretch",
                             help="Öğrenciyi, yüz izini ve bütün kişisel odak verisini kalıcı olarak siler."):
                    ogrenci_db.ogrenci_sil(o["id"])
                    ss.kayit_acik = True
                    st.toast(f"{o['ad']} ve tüm verileri silindi.")
                    st.rerun()
            st.divider()

        # --- Yeni öğrenci ---
        st.markdown("**Yeni öğrenci ekle**")
        n = ss.get("kayit_sayac", 0)
        ad = st.text_input("Öğrencinin adı", key=f"kayit_ad_{n}", placeholder="Örn. Ayşe Yılmaz")
        riza = st.checkbox(
            "Öğrenci (18 yaşından küçükse velisi), ders sırasında yüzünün tanınarak kişisel odak raporu "
            "oluşturulmasına **açık rıza** verdi.", key=f"kayit_riza_{n}")

        ornekler = ss.get("kayit_ornekler", [])
        if len(ornekler) < EN_COK_ORNEK:
            # Tarayıcı kamerası yalnızca istenince açılır: açık kalırsa ders kaydı kameraya erişemez
            kamera_acik = st.toggle("📷 Tarayıcı kamerasını aç", key=f"kayit_kamera_acik_{n}",
                                    help="Fotoğraflar bitince kapatın. Kamera burada açıkken ders kaydı kamerayı "
                                         "kullanamaz.")
            foto = (st.camera_input(f"Yüz örneği çek ({len(ornekler)}/{EN_COK_ORNEK}; en az {EN_AZ_ORNEK}, ideali 3-4)",
                                    key=f"kayit_kamera_{n}_{len(ornekler)}") if kamera_acik else None)
            if foto is not None:
                ss.kayit_acik = True
                _ornek_ekle(_coz(foto))
                st.rerun()
            yuklenen = st.file_uploader("…ya da fotoğraf yükle", type=["jpg", "jpeg", "png"],
                                        accept_multiple_files=True, key=f"kayit_yukle_{n}_{len(ornekler)}")
            if yuklenen:
                ss.kayit_acik = True
                for f in yuklenen[: EN_COK_ORNEK - len(ornekler)]:
                    _ornek_ekle(_coz(f))
                st.rerun()

        if ss.get("kayit_mesaj"):
            tur, metin = ss.kayit_mesaj
            getattr(st, tur)(metin)
        if ornekler:
            st.image([o[:, :, ::-1].copy() for o in ornekler], width=110)  # yalnızca bu ekranda, bellekte

        c1, c2 = st.columns([1.4, 1])
        hazir = bool(ad.strip()) and riza and len(ornekler) >= EN_AZ_ORNEK
        if c1.button("✓ Kaydı tamamla ve şifre üret", type="primary", disabled=not hazir, width="stretch"):
            izler, uyarilar = _kimlik().kayit_izleri(ornekler)
            if len(izler) < EN_AZ_ORNEK:
                st.error("Yeterli yüz örneği çıkarılamadı. " + " ".join(uyarilar))
            else:
                _, sifre = ogrenci_db.ogrenci_ekle(ad.strip(), izler)
                ss.son_sifre = (ad.strip(), sifre)
                ss.kayit_acik = True
                _sifirla()  # fotoğraflar bellekten de silinir
                st.rerun()
        if c2.button("Vazgeç / temizle", width="stretch", disabled=not (ornekler or ad)):
            _sifirla()
            st.rerun()
        if not hazir:
            eksikler = [m for k, m in ((ad.strip(), "ad"), (riza, "rıza onayı"),
                                       (len(ornekler) >= EN_AZ_ORNEK, f"en az {EN_AZ_ORNEK} yüz örneği")) if not k]
            st.caption("Kaydı tamamlamak için gerekenler: " + ", ".join(eksikler))
