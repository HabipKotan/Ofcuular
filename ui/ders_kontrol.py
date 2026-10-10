"""
Öğretmen paneli: "🔴 Dersi Başlat / ⏹ Dersi Bitir" kontrolleri.

Kayıt ve işleme ders_kaydi.py adlı ayrı bir süreçte çalışır (Streamlit donmasın diye).
İki taraf yalnızca dosyalarla konuşur:
    kayit_durumu.json   <- süreç yazar, panel okur (durum, mesaj, adım, nabız)
    kayit_durdur.flag   <- panel oluşturur, süreç görünce kaydı bitirir
    kayit_gunlugu.txt   <- sürecin tüm çıktısı; panel son satırları gösterir

Başlatma akışı:
    1) Ders adı zorunludur (boşsa kayıt başlamaz).
    2) "Dersi Başlat"a basınca iki soru sorulur:
         - Ses dinlenip metne çevrilsin mi?        (hayır -> mikrofon hiç açılmaz, not üretilmez)
         - Sınıfın odak ortalaması izlensin mi?    (hayır -> kamera hiç açılmaz)
       En az biri seçilmelidir.
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


def kayit_aktif(d: dict | None = None) -> bool:
    """Kayıt/işleme süreci gerçekten çalışıyor mu? (Durum aktif görünse de nabız kesildiyse çalışmıyordur.)"""
    d = durum_oku() if d is None else d
    return bool(d) and d.get("durum") in AKTIF and time.time() - d.get("guncelleme", 0) <= NABIZ_ZAMAN_ASIMI


def _sure(saniye: float) -> str:
    s = max(0, int(saniye))
    return f"{s // 60:02d}:{s % 60:02d}"


def _gunluk_goster(acik: bool = False, satir: int = 30) -> None:
    try:
        metin = GUNLUK.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return
    if metin:
        with st.expander("📄 Kayıt günlüğü (son satırlar)", expanded=acik):
            st.code("\n".join(metin[-satir:]), language=None)


def _surec_baslat(ek_argumanlar: list[str], ilk_durum: dict) -> None:
    DURDUR.unlink(missing_ok=True)
    from core.dosya import guvenli_yaz
    guvenli_yaz(DURUM, json.dumps({**ilk_durum, "guncelleme": time.time()}, ensure_ascii=False))
    komut = [sys.executable, "-u", str(PROJE / "ders_kaydi.py")] + ek_argumanlar
    # Ayrı terminal penceresi YOK: tüm çıktı ve hatalar günlük dosyasına yazılır, panel son satırları gösterir.
    # (Odak izleniyorsa kamera önizleme penceresi yine açılır.)
    gunluk = open(GUNLUK, "w", encoding="utf-8")
    ortam = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    bayrak = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen(komut, cwd=str(PROJE), stdout=gunluk, stderr=subprocess.STDOUT, env=ortam, creationflags=bayrak)
    gunluk.close()  # alt süreç kendi kopyasını tutar


def _baslat(konu: str, ses: bool = True, odak: bool = True, sesi_sakla: bool = False) -> None:
    arg = ["--konu", konu.strip()]
    if not ses:
        arg.append("--ses-yok")
    if not odak:
        arg.append("--odak-yok")
    if sesi_sakla and ses:
        arg.append("--sesi-sakla")
    _surec_baslat(arg, {"durum": "baslatiliyor", "mesaj": "Kayıt başlatılıyor…", "konu": konu.strip(),
                        "ses": ses, "odak": odak})


def _notlar_yarim_kaldi() -> bool:
    """Transkript var ama notlar ondan eski/yoksa: not adımı yarıda kalmıştır."""
    t, n = gercek_veri.TRANSKRIPT, gercek_veri.NOTLAR
    try:
        if not t.exists() or not json.loads(t.read_text(encoding="utf-8")):
            return False  # transkript yok ya da boş: yeniden üretilecek not da yok
    except Exception:
        return False
    return not n.exists() or n.stat().st_mtime < t.stat().st_mtime


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


def _asama(d: dict | None) -> str:
    """Sayfanın hangi halde çizileceği. Her geçişte (başlatılıyor -> kayıt -> bitiriliyor -> işleniyor -> boş)
    sayfa baştan çizilir: tahta kayıt başlayınca gelir, ders bitince kaybolur."""
    durum = (d or {}).get("durum")
    if durum not in AKTIF:
        return "bos"
    return durum + ("-bitiyor" if durum == "kayit" and DURDUR.exists() else "")


# ---------------------------------------------------------------------------
# Başlatma penceresi: iki soru
# ---------------------------------------------------------------------------
@st.dialog("Dersi başlat")
def _baslat_penceresi(konu: str, sesi_sakla: bool) -> None:
    st.markdown(f"**Ders:** {konu}")
    st.caption("Bu derste neler çalışsın? En az birini seçin.")
    ses = st.toggle("🎙️ Ses dinlenip metne çevrilsin mi?", value=True, key="soru_ses")
    st.caption("Açıkken: mikrofon dersi dinler, **yalnızca öğretmenin sesi** metne çevrilir ve ders notları hazırlanır. "
               "Kapalıyken mikrofon hiç açılmaz; not üretilmez.")
    odak = st.toggle("👀 Sınıfın odak ortalaması izlensin mi?", value=True, key="soru_odak")
    st.caption("Açıkken: kamera sınıfın anonim odak ortalamasını ve öğrenci sayısını ölçer (görüntü kaydedilmez). "
               "Kapalıyken kamera hiç açılmaz.")
    if not ses and not odak:
        st.error("İkisi de kapalıyken kaydedilecek bir şey yok. En az birini açın.")
    c1, c2 = st.columns(2)
    if c1.button("🔴 Başlat", type="primary", width="stretch", disabled=not (ses or odak)):
        _baslat(konu, ses=ses, odak=odak, sesi_sakla=sesi_sakla)
        st.rerun()
    if c2.button("Vazgeç", width="stretch"):
        st.rerun()


# ---------------------------------------------------------------------------
# Canlı durum (2 sn'de bir yenilenir)
# ---------------------------------------------------------------------------
@st.fragment(run_every=2)
def _canli_durum() -> None:
    d = durum_oku()
    durum = (d or {}).get("durum")
    sessiz = time.time() - (d or {}).get("guncelleme", 0)

    if _yeni_ders_geldi(d or {}):
        st.cache_data.clear()
        st.session_state.kaynaga_gec = True  # app.py veri kaynağını "Gerçek ders"e çevirir
        st.rerun(scope="app")
    if _asama(d) != st.session_state.get("kayit_asamasi"):
        st.rerun(scope="app")  # kayıt başladı / bitti / hata verdi: kutunun tamamı yeniden çizilsin

    if durum not in AKTIF:
        return

    if sessiz > NABIZ_ZAMAN_ASIMI:
        st.warning("Kayıt süreci yanıt vermiyor (kapanmış olabilir). Aşağıdaki günlükte sebebi görünür; "
                   "sonra sıfırlayıp yeniden başlatabilirsiniz.")
        _gunluk_goster(acik=True)
        if st.button("↺ Kaydı sıfırla"):
            DURUM.unlink(missing_ok=True)
            DURDUR.unlink(missing_ok=True)
            st.rerun(scope="app")
        return

    ses, odak = d.get("ses", True), d.get("odak", True)
    neler = " + ".join(x for x, acik in (("ses", ses), ("sınıf odağı", odak)) if acik)

    if durum == "baslatiliyor":
        st.info(f"⏳ {d.get('mesaj') or 'Hazırlanıyor…'} (ilk seferde birkaç saniye sürebilir)")
        return

    if durum == "kayit":
        gecen = time.time() - (d.get("baslangic") or time.time())
        c1, c2 = st.columns([2, 1])
        c1.markdown(f"<span style='color:#E5484D;font-weight:700;font-size:1.1rem'>● Kayıt sürüyor</span>"
                    f"&nbsp;&nbsp;<span style='font-variant-numeric:tabular-nums;font-size:1.1rem'>"
                    f"{_sure(gecen)}</span>"
                    f"<br><span style='color:#6B7385'>{d.get('konu') or ''} · {neler}</span>",
                    unsafe_allow_html=True)
        if DURDUR.exists():
            c2.button("Durduruluyor…", disabled=True, width="stretch")
        elif c2.button("⏹ Dersi Bitir", type="primary", width="stretch"):
            DURDUR.touch()
            st.rerun(scope="app")  # tahta son halini hemen kaydetsin
        if d.get("uyari"):
            st.warning("📷 " + d["uyari"])
        if ses:
            seviye = float(d.get("ses_seviyesi") or 0)
            st.progress(min(1.0, seviye * 8), text=f"🎙️ Mikrofon: {d.get('mikrofon') or '?'}")
            if gecen > 6 and seviye < 0.004:
                st.warning("Ses çok düşük: mikrofon sizi duymuyor olabilir. Konuşurken çubuk dolmalı. "
                           "Windows ses ayarlarından varsayılan mikrofonu kontrol edin ve mikrofona yaklaşın.")
        else:
            st.caption("🎙️ Mikrofon kapalı: bu derste ses dinlenmiyor.")
        st.caption("📷 Kamera görüntüsü yalnızca bellekte işlenir; ekranda bulanık önizleme açıktır." if odak
                   else "📷 Kamera kapalı: bu derste sınıf odağı izlenmiyor.")
        return

    # isleniyor
    adim = int(d.get("adim") or 1)
    st.progress(min(adim, ADIMLAR) / ADIMLAR, text=f"⚙️ {d.get('mesaj', 'İşleniyor…')}")
    st.caption("Ders işleniyor. Bitince sayfa kendiliğinden yenilenecek.")
    _gunluk_goster()


# ---------------------------------------------------------------------------
# Kutu
# ---------------------------------------------------------------------------
def render_ders_kaydi() -> None:
    d = durum_oku()
    durum = (d or {}).get("durum")
    st.session_state.kayit_asamasi = _asama(d)

    with st.container(border=True):
        st.markdown("#### 🎬 Ders kaydı")
        _canli_durum()
        if durum in AKTIF:
            return

        if durum == "hata":
            st.error(f"Son kayıt tamamlanamadı: {d.get('mesaj', 'bilinmeyen hata')}")
            _gunluk_goster(acik=True)
            if _notlar_yarim_kaldi():
                st.caption("Ders kaydı ve metni kaybolmadı; yalnızca not adımı yarıda kaldı.")
                if st.button("🔁 Notları yeniden üret", type="primary"):
                    _surec_baslat(["--sadece-notlar"], {**(d or {}), "durum": "isleniyor", "adim": 3,
                                                        "mesaj": "Notlar yeniden hazırlanıyor…"})
                    st.rerun()
                st.divider()

        konu = st.text_input("Ders adı (zorunlu)", key="kayit_konu",
                             placeholder="Örn. Matematik 9-A: kesirler, pay, payda",
                             help="Ders adı notların başlığı olur. İçine konu ve terimleri de yazarsanız "
                                  "ses metne daha doğru çevrilir.")
        sakla = st.checkbox("Ses kaydını sakla (test için)", key="kayit_sesi_sakla",
                            help="İşaretlenirse ders.wav silinmez; kaydı dinleyip mikrofonu kontrol edebilirsiniz. "
                                 "Normalde ses, metne çevrilir çevrilmez silinir (KVKK).")
        if st.button("🔴 Dersi Başlat", type="primary"):
            if not konu.strip():
                st.session_state.kayit_konu_eksik = True
            else:
                st.session_state.kayit_konu_eksik = False
                _baslat_penceresi(konu.strip(), sakla)
        if st.session_state.get("kayit_konu_eksik") and not konu.strip():
            st.warning("Dersi başlatmak için önce **ders adını** yazın.")
        if durum == "bitti":
            st.caption(f"Son ders işlendi: {time.strftime('%H:%M', time.localtime(d.get('bitis', 0)))}"
                       + (f" · {d.get('konu')}" if d.get("konu") else ""))
