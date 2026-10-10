"""
Tahta defteri (arkadaşımızın ders_defteri.html'i) arayüzün içinde.

ÖĞRETMEN PANELİNDE (ders_tahtasi): "Dersi Başlat" ile kayıt başlayınca tahta TAM EKRAN açılır, her ders BOŞ bir
sayfayla başlar. Tahtaya PDF / PowerPoint / Word / resim sürüklenip bırakılabilir; sayfaların üzerine yazılır. Tahta yazıldıkça birkaç saniyede bir otomatik kaydedilir; ders bitince son hali yazılır ve
tahta kaybolur. Kaydedilen sayfalar arayüzde gösterilmez; defter sayfaları gibi klasörde birikir:
    <kalıcı klasör veya proje>/tahtalar/<tarih_saat>_<ders>.png / .json

ui/tahta/index.html bir Streamlit bileşeni olarak açılır. Defterdeki
"Dersi başlat" / "Dersi bitir" butonları arayüze olay gönderir:
    {"olay": "basladi", "zaman", "ders"}
    {"olay": "bitti",   "zaman", "ders", "veri": <defter JSON'u>, "png": "data:image/png;base64,..."}

Her ders bitince tahta arşive YENİ bir kayıt olarak eklenir; yeni ders boş tahtayla başlar:
    tahtalar/<tarih_saat>_<ders>.json   (her çizginin yazıldığı saatle birlikte)
    tahtalar/<tarih_saat>_<ders>.png    (tahtanın tamamı)
"""

from __future__ import annotations

import base64
import json
import re
import time
from datetime import datetime
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from core.dosya import guvenli_yaz
from ui import ders_kontrol, gercek_veri

_bilesen = components.declare_component("tahta_defteri", path=str(Path(__file__).parent / "tahta"))


def goster(yukseklik: int = 760):
    """Tahtayı çizer; son olayı (ya da None) döndürür."""
    return _bilesen(yukseklik=yukseklik, key="tahta_defteri", default=None)


def _dosya_adi(ders: str) -> str:
    cevir = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    kok = re.sub(r"[^a-z0-9]+", "-", (ders or "").translate(cevir).lower()).strip("-")[:40] or "ders"
    return f"{datetime.now():%Y%m%d_%H%M%S}_{kok}"


def _kaydet(olay: dict) -> Path:
    """Tahtayı arşive YENİ bir kayıt olarak ekler (önceki dersler silinmez)."""
    gercek_veri.TAHTALAR.mkdir(parents=True, exist_ok=True)
    kok = gercek_veri.TAHTALAR / _dosya_adi(olay.get("ders", ""))
    veri = olay.get("veri") or {}
    kok.with_suffix(".json").write_text(json.dumps(veri, ensure_ascii=False), encoding="utf-8")
    png = olay.get("png") or ""
    if not png.startswith("data:image/png;base64,"):
        raise ValueError("tahta resmi gelmedi")
    kok.with_suffix(".png").write_bytes(base64.b64decode(png.split(",", 1)[1]))
    return kok.with_suffix(".png")


def olay_isle(olay, tek_tus: bool) -> None:
    """Tahtadan gelen olayı bir kez işler (aynı olay her yeniden çizimde tekrar gelir)."""
    ss = st.session_state
    if not isinstance(olay, dict) or ss.get("tahta_son_olay") == olay.get("zaman"):
        return
    ss.tahta_son_olay = olay.get("zaman")
    d = ders_kontrol.durum_oku() or {}
    aktif = ders_kontrol.kayit_aktif(d)  # nabzı kesilmiş (çökmüş) eski bir kayıt yeni dersi engellemesin
    kayit_suruyor = aktif and d.get("durum") in ("baslatiliyor", "kayit")

    if olay.get("olay") == "basladi":
        if tek_tus and not aktif:
            ders_kontrol._baslat(olay.get("ders", ""), ss.get("kayit_sesi_sakla", False))
            st.toast("🔴 Ders başladı: tahta, kamera ve mikrofon kaydı açık.")
        else:
            st.toast("🖊️ Tahta dersi başladı.")

    elif olay.get("olay") == "bitti":
        try:
            _kaydet(olay)
            st.toast("💾 Tahta bu dersin kaydı olarak arşivlendi.")
        except Exception as e:
            st.error(f"Tahta kaydedilemedi: {e}")
        if tek_tus and kayit_suruyor:
            ders_kontrol.DURDUR.touch()
            st.toast("⏹ Kayıt durduruluyor; notlar hazırlanacak.")


# ---------------------------------------------------------------------------
# Öğretmen paneli: ders boyunca açık, otomatik kaydedilen tahta
# ---------------------------------------------------------------------------
_ESLESME = ".eslesme.json"   # ders kimliği -> sayfa adı (aynı ders hep AYNI sayfanın üzerine yazılır)


def _sayfa_koku(kimlik: str, ders: str) -> Path:
    yol = gercek_veri.TAHTALAR / _ESLESME
    try:
        eslesme = json.loads(yol.read_text(encoding="utf-8"))
    except Exception:
        eslesme = {}
    if kimlik not in eslesme:
        eslesme[kimlik] = _dosya_adi(ders)
        guvenli_yaz(yol, json.dumps(eslesme, ensure_ascii=False, indent=1))
    return gercek_veri.TAHTALAR / eslesme[kimlik]


def sayfa_kaydet(olay: dict) -> Path:
    """Tahtanın son halini bu dersin sayfasına yazar (aynı ders içinde üzerine yazar)."""
    png = olay.get("png") or ""
    if not png.startswith("data:image/png;base64,"):
        raise ValueError("tahta resmi gelmedi")
    gercek_veri.TAHTALAR.mkdir(parents=True, exist_ok=True)
    kok = _sayfa_koku(str(olay.get("kimlik")), olay.get("ders", ""))
    resim = kok.with_name(kok.name + ".png")
    guvenli_yaz(kok.with_name(kok.name + ".json"), json.dumps(olay.get("veri") or {}, ensure_ascii=False))
    gecici = resim.with_name(resim.name + ".yaziliyor")
    gecici.write_bytes(base64.b64decode(png.split(",", 1)[1]))
    for _ in range(25):  # Windows: dosya o an açıksa kısa bekleyip tekrar dene
        try:
            gecici.replace(resim)
            break
        except PermissionError:
            time.sleep(0.08)
    return resim


# Ders sürerken tahta bütün pencereyi kaplar. Streamlit'in kendi başlığı ve yan paneli gizlenir; tahtanın
# "Küçült" düğmesi bu kuralları kaldırır. (Tarayıcının gerçek tam ekranını tahta, ilk dokunuşta kendisi ister.)
_TAM_EKRAN_CSS = """<style>
.st-key-tahta_kutu iframe {
    position: fixed !important; inset: 0 !important; width: 100vw !important; height: 100vh !important;
    height: 100dvh !important; max-width: none !important; z-index: 1000100 !important; border: 0 !important;
    background: #f1efe9; opacity: 1 !important; transition: none !important;
}
.st-key-tahta_kutu, .st-key-tahta_kutu * { opacity: 1 !important; }
header[data-testid="stHeader"], [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"],
[data-testid="stToolbar"], [data-testid="stDecoration"] { display: none !important; }
@media (prefers-color-scheme: dark) { .st-key-tahta_kutu iframe { background: #111110; } }
</style>"""
_NORMAL_CSS = "<style>.st-key-tahta_kutu iframe { border: 0; }</style>"


def _belge_donustur(olay: dict) -> dict:
    """Tahtaya bırakılan PowerPoint / Word dosyasını PDF'e çevirir; yanıt tahtaya args.belge ile gider."""
    from core import belge_donustur

    istek = str(olay.get("istek") or "")
    ad = str(olay.get("ad") or "belge")
    try:
        veri = base64.b64decode(olay.get("veri") or "")
        pdf = belge_donustur.pdfe_cevir(veri, ad)
        return {"istek": istek, "ad": ad, "pdf": base64.b64encode(pdf).decode("ascii")}
    except belge_donustur.DonusturmeHatasi as e:
        return {"istek": istek, "hata": str(e)}
    except Exception as e:  # beklenmeyen hata da tahtaya anlaşılır biçimde dönsün
        return {"istek": istek, "hata": f"Dosya PDF'e çevrilemedi ({e}). {belge_donustur.PDF_OLARAK_KAYDET}"}


def _ders_olayi(olay, kimlik: str) -> None:
    """Tahtadan gelen olayı işler. 'kaydet' sessizce diske yazılır; kontrol olayları (bitir, tam ekran, belge)
    bir kez işlenir, zamanı args.onay ile tahtaya geri bildirilir ve sayfa yeniden çizilir."""
    ss = st.session_state
    if not isinstance(olay, dict) or str(olay.get("kimlik")) != kimlik:
        return
    tur = olay.get("olay")
    if tur == "kaydet":
        if ss.get("tahta_son_kayit") != olay.get("zaman"):
            try:
                sayfa_kaydet(olay)
                ss.tahta_son_kayit = olay.get("zaman")
                ss.tahta_son_kayit_saati = (kimlik, datetime.now().strftime("%H:%M:%S"))
            except Exception as e:
                st.warning(f"Tahta kaydedilemedi: {e}")
        return
    zaman = olay.get("zaman")
    if zaman is None or ss.get("tahta_son_kontrol") == zaman:
        return  # aynı olay her yeniden çizimde tekrar gelir; yalnızca bir kez işlenir
    ss.tahta_son_kontrol = zaman
    if tur == "bitir":
        if olay.get("png"):
            try:
                sayfa_kaydet(olay)  # tahtanın son hali
            except Exception as e:
                st.warning(f"Tahta kaydedilemedi: {e}")
        ders_kontrol.DURDUR.touch()
    elif tur == "tam_ekran":
        ss.setdefault("tahta_tam_ekran", {})[kimlik] = bool(olay.get("acik"))
    elif tur == "belge_donustur":
        ss.tahta_belge = _belge_donustur(olay)
    elif tur == "belge_alindi":
        if (ss.get("tahta_belge") or {}).get("istek") == olay.get("istek"):
            ss.pop("tahta_belge", None)  # büyük PDF yanıtı her yeniden çizimde tekrar gönderilmesin
    st.rerun()


def ders_tahtasi(d: dict, yukseklik: int = 760) -> None:
    """Kayıt sürerken tahtayı gösterir (varsayılan: tam ekran) ve tahtadan gelen olayları işler."""
    ss = st.session_state
    kimlik = f"{d.get('pid') or 0}_{int(d.get('baslangic') or 0)}"
    bitiyor = ders_kontrol.DURDUR.exists()
    tam = ss.setdefault("tahta_tam_ekran", {}).setdefault(kimlik, True)  # her ders tam ekran başlar

    # Öğe sayısı ve sırası iki modda da AYNI kalmalı; yoksa Streamlit tahtayı baştan yükler.
    st.markdown(_TAM_EKRAN_CSS if tam else _NORMAL_CSS, unsafe_allow_html=True)
    st.markdown("#### 🖊️ Tahta")
    with st.container(key="tahta_kutu"):
        olay = _bilesen(yukseklik=yukseklik, kimlik=kimlik, konu=d.get("konu") or "", bitiyor=bitiyor,
                        tam_ekran=tam, onay=ss.get("tahta_son_kontrol"), belge=ss.get("tahta_belge"),
                        uyari=ss.get("tahta_uyari"), key="ders_tahtasi", default=None)
    _ders_olayi(olay, kimlik)
    k, son = ss.get("tahta_son_kayit_saati") or (None, None)
    son = son if k == kimlik else None
    st.caption("Her ders boş bir tahtayla başlar ve yazdıkça otomatik kaydedilir"
               + (f" · son kayıt {son}" if son else "")
               + ". PDF, PowerPoint ya da Word dosyasını tahtaya sürükleyip üzerine yazabilirsiniz. "
                 "Tam ekrana dönmek için tahtadaki **Tam ekran** düğmesine basın.")


def render_tahta_sekmesi() -> None:
    tek_tus = st.toggle(
        "Tahtadaki **Dersi başlat / bitir** kamera ve mikrofon kaydını da yönetsin",
        value=True, key="tahta_tek_tus",
        help="Açıkken hocanın tek yapması gereken tahtadaki butona basmak: kayıt da onunla başlar ve biter.",
    )
    olay = goster()
    olay_isle(olay, tek_tus)
    st.caption("Her ders boş bir tahtayla başlar. Ders bitince tahta arşive eklenir; geçmiş derslerin tahtaları "
               "Öğretmen Görünümü'nde birikir ve öğretmen onayından sonra öğrencilerle paylaşılır.")


def render_tahta_ozeti(ogrenci: bool = False) -> None:
    """Bütün derslerin tahtaları (en yeni üstte): öğretmende her zaman, öğrencide onaydan sonra."""
    liste = gercek_veri.tahta_listesi()
    if not liste:
        return
    st.markdown(f"#### 🖊️ Tahta defterleri ({len(liste)})")
    if ogrenci and not st.session_state.get("notes_approved"):
        st.info("Tahta defterleri öğretmen notları onayladığında burada paylaşılacak.")
        return
    for i, k in enumerate(liste):
        baslik = " · ".join(x for x in (k["ders"] or "Ders", k["zaman"]) if x) + ("  ·  en son" if i == 0 else "")
        with st.expander(baslik, expanded=(i == 0)):
            st.image(str(k["png"]))
            st.download_button("⬇ PNG indir", k["png"].read_bytes(), file_name=k["png"].name, mime="image/png",
                               key=f"tahta_indir_{int(ogrenci)}_{k['png'].name}")
