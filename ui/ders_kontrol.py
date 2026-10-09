"""
Öğretmen paneli: "🔴 Dersi Başlat / ⏹ Dersi Bitir" kontrolleri.

Kayıt ve işleme ders_kaydi.py adlı ayrı bir süreçte çalışır (Streamlit donmasın diye).
İki taraf yalnızca dosyalarla konuşur:
    kayit_durumu.json   <- süreç yazar, panel okur (durum, mesaj, adım, nabız)
    kayit_durdur.flag   <- panel oluşturur, süreç görünce kaydı bitirir
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import streamlit as st

from ui import gercek_veri

PROJE = gercek_veri.PROJE_KLASORU
DURUM = gercek_veri.VERI_KLASORU / "kayit_durumu.json"
DURDUR = gercek_veri.VERI_KLASORU / "kayit_durdur.flag"
GUNLUK = gercek_veri.VERI_KLASORU / "kayit_gunlugu.txt"
AKTIF = ("baslatiliyor", "kayit", "isleniyor")
NABIZ_ZAMAN_ASIMI = 20  # sn: süreç bu kadar sessiz kalırsa çökmüş sayılır
ADIMLAR = 4


def durum_oku() -> dict | None:
    try:
        return json.loads(DURUM.read_text(encoding="utf-8"))
    except Exception:
        return None


def _sure(saniye: float) -> str:
    s = max(0, int(saniye))
    return f"{s // 60:02d}:{s % 60:02d}"


def _surec_baslat(ek_argumanlar: list[str], ilk_durum: dict) -> None:
    DURDUR.unlink(missing_ok=True)
    DURUM.write_text(json.dumps({**ilk_durum, "guncelleme": time.time()}, ensure_ascii=False), encoding="utf-8")
    komut = [sys.executable, "-u", str(PROJE / "ders_kaydi.py")] + ek_argumanlar
    # Ayrı terminal penceresi YOK: tüm çıktı ve hatalar günlük dosyasına yazılır, panel son satırları gösterir.
    # (Kamera önizleme penceresi yine açılır.)
    gunluk = open(GUNLUK, "w", encoding="utf-8")
    ortam = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    bayrak = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen(komut, cwd=str(PROJE), stdout=gunluk, stderr=subprocess.STDOUT, env=ortam, creationflags=bayrak)
    gunluk.close()  # alt süreç kendi kopyasını tutar


def _gunluk_goster(acik: bool = False, satir: int = 30) -> None:
    try:
        metin = GUNLUK.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return
    if metin:
        with st.expander("📄 Kayıt günlüğü (son satırlar)", expanded=acik):
            st.code("\n".join(metin[-satir:]), language=None)


def _baslat(konu: str, sesi_sakla: bool = False) -> None:
    arg = ["--konu", konu.strip()] if konu.strip() else []
    if sesi_sakla:
        arg.append("--sesi-sakla")
    _surec_baslat(arg, {"durum": "baslatiliyor", "mesaj": "Kayıt başlatılıyor…"})


def _notlar_yarim_kaldi() -> bool:
    """Transkript var ama notlar ondan eski/yoksa: not adımı yarıda kalmıştır."""
    t, n = gercek_veri.TRANSKRIPT, gercek_veri.NOTLAR
    return t.exists() and (not n.exists() or n.stat().st_mtime < t.stat().st_mtime)


def _yeni_ders_geldi(d: dict) -> bool:
    """İşleme bu sayfa açıkken yeni bittiyse bir kez True döner."""
    ss = st.session_state
    imza = d.get("bitis") if d.get("durum") == "bitti" else None
    if "son_islenen_ders" not in ss:
        # Sayfa ilk açıldığında (kayıt sürerken bile) mevcut durumu "görülmüş" say
        ss.son_islenen_ders = imza
        return False
    if imza and imza != ss.son_islenen_ders:
        ss.son_islenen_ders = imza
        return True
    return False


@st.fragment(run_every=2)
def render_ders_kaydi() -> None:
    d = durum_oku()
    durum = (d or {}).get("durum")
    sessiz = time.time() - (d or {}).get("guncelleme", 0)

    if _yeni_ders_geldi(d or {}):
        st.cache_data.clear()
        st.session_state.kaynaga_gec = True  # app.py veri kaynağını "Gerçek ders"e çevirir
        st.rerun(scope="app")

    with st.container(border=True):
        st.markdown("#### 🎬 Ders kaydı")

        if durum in AKTIF and sessiz > NABIZ_ZAMAN_ASIMI:
            st.warning("Kayıt süreci yanıt vermiyor (kapanmış olabilir). Aşağıdaki günlükte sebebi görünür; "
                       "sonra sıfırlayıp yeniden başlatabilirsiniz.")
            _gunluk_goster(acik=True)
            if st.button("↺ Kaydı sıfırla"):
                DURUM.unlink(missing_ok=True)
                DURDUR.unlink(missing_ok=True)
                st.rerun()
            return

        if durum == "baslatiliyor":
            st.info("⏳ Kamera ve mikrofon hazırlanıyor… (ilk seferde birkaç saniye sürebilir)")
            return

        if durum == "kayit":
            gecen = time.time() - (d.get("baslangic") or time.time())
            c1, c2 = st.columns([2, 1])
            c1.markdown(f"<span style='color:#E5484D;font-weight:700;font-size:1.1rem'>● Kayıt sürüyor</span>"
                        f"&nbsp;&nbsp;<span style='font-variant-numeric:tabular-nums;font-size:1.1rem'>"
                        f"{_sure(gecen)}</span>"
                        + (f"<br><span style='color:#6B7385'>{d.get('konu')}</span>" if d.get("konu") else ""),
                        unsafe_allow_html=True)
            if DURDUR.exists():
                c2.button("Durduruluyor…", disabled=True, width="stretch")
            elif c2.button("⏹ Dersi Bitir", type="primary", width="stretch"):
                DURDUR.touch()
                st.rerun()
            seviye = float(d.get("ses_seviyesi") or 0)
            st.progress(min(1.0, seviye * 8), text=f"🎙️ Mikrofon: {d.get('mikrofon', '?')}")
            if gecen > 6 and seviye < 0.004:
                st.warning("Ses çok düşük: mikrofon sizi duymuyor olabilir. Konuşurken çubuk dolmalı. "
                           "Windows ses ayarlarından varsayılan mikrofonu kontrol edin ve mikrofona yaklaşın.")
            st.caption("Kamera görüntüsü yalnızca bellekte işlenir; ekranda bulanık önizleme açıktır.")
            return

        if durum == "isleniyor":
            adim = int(d.get("adim") or 1)
            st.progress(min(adim, ADIMLAR) / ADIMLAR, text=f"⚙️ {d.get('mesaj', 'İşleniyor…')}")
            st.caption("Ses metne çevriliyor, notlar ve odak analizi hazırlanıyor. Bitince sayfa kendiliğinden yenilenecek.")
            _gunluk_goster()
            return

        if durum == "hata":
            st.error(f"Son kayıt tamamlanamadı: {d.get('mesaj', 'bilinmeyen hata')}")
            _gunluk_goster(acik=True)
            if _notlar_yarim_kaldi():
                st.caption("Ders kaydı ve metni kaybolmadı; yalnızca not adımı yarıda kaldı.")
                if st.button("🔁 Notları yeniden üret", type="primary"):
                    _surec_baslat(["--sadece-notlar"], {"durum": "isleniyor", "adim": 3,
                                                        "mesaj": "Notlar yeniden hazırlanıyor…"})
                    st.rerun()
                st.divider()

        konu = st.text_input("Ders konusu (isteğe bağlı)", key="kayit_konu",
                             placeholder="Örn. Matematik: kesirler, pay, payda",
                             help="Konu ve terimleri yazmak, sesin metne daha doğru çevrilmesine yardım eder.")
        sakla = st.checkbox("Ses kaydını sakla (test için)", key="kayit_sesi_sakla",
                            help="İşaretlenirse ders.wav silinmez; kaydı dinleyip mikrofonu kontrol edebilirsiniz. "
                                 "Normalde ses, metne çevrilir çevrilmez silinir (KVKK).")
        if st.button("🔴 Dersi Başlat", type="primary"):
            _baslat(konu, sakla)
            st.rerun()
        if durum == "bitti":
            st.caption(f"Son ders işlendi: {time.strftime('%H:%M', time.localtime(d.get('bitis', 0)))}")
