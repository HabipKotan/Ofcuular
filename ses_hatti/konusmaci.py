"""
Öğretmenin sesini diğer seslerden ayırır
========================================
Fikir: Ders boyunca en çok konuşan kişi öğretmendir. Kayıttaki konuşma parçalarının her biri için bir
"ses izi" (konuşmacı gömmesi) çıkarılır; birbirine benzeyen parçalar gruplanır; toplam süresi en uzun
olan grup öğretmen sayılır. Öğretmene benzemeyen parçalar (öğrenci soruları, sınıftaki başka sesler)
metne çevrilmeden ÖNCE susturulur, yani başka kimsenin sesi yazıya dökülmez.

Her şey bu bilgisayarda çalışır; ses izleri diske yazılmaz, kimlik eşleştirmesi yapılmaz
(yalnızca "bu kayıttaki baskın ses" bulunur).

Gerekenler: numpy + onnxruntime (faster-whisper ile zaten kurulu) ve küçük bir konuşmacı modeli
(ses_hatti/modeller/konusmaci.onnx, ~26 MB; yoksa ilk kullanımda indirilir).

Tek başına deneme:
    python ses_hatti/konusmaci.py ders.wav          -> hangi aralıkların öğretmene ait sayıldığını yazar
"""

from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path

import numpy as np

ORNEKLEME = 16000
MODEL_YOLU = Path(__file__).resolve().parent / "modeller" / "konusmaci.onnx"
MODEL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
             "wespeaker_en_voxceleb_resnet34.onnx")

# Ayarlar (gerçek konuşma kayıtlarıyla ölçülerek seçildi; bkz. README "Öğretmen sesi")
PENCERE_SN = 1.5        # ses izi çıkarılan pencere; daha kısası güvenilmez
ADIM_SN = 0.5
EN_KISA_SN = 0.6        # bundan kısa konuşma parçasından ses izi çıkarılmaz (komşusuna göre karar verilir)
ESIK = 0.45             # öğretmenin ses izine benzerlik bunun üstündeyse kesin "öğretmen"
ESIK_KISA = 0.40        # 1.5 sn'den kısa pencereler için (kısa parçada benzerlik doğal olarak düşer)
ESIK_DIGER = 0.30       # tam pencerede benzerlik bunun altındaysa kesin "başka biri"
ESIK_BIRLESTIR = 0.45   # iki grubun merkezleri bu kadar benziyorsa aynı kişi sayılır (öğretmenin farklı tonları).
                        # Daha düşük değerler ölçümde benzer sesli öğrencileri öğretmenle birleştirdi.
KOMSU_SN = 1.0          # kararsız pencere, en yakın kesin pencereye bu kadar yakınsa onun kararını alır
EN_AZ_KONUSMA_SN = 8.0  # toplam konuşma bundan azsa ayrım yapılmaz (karar verecek kadar veri yok)

_oturum = None


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------
def model_hazir_mi(indir: bool = True) -> bool:
    if MODEL_YOLU.exists() and MODEL_YOLU.stat().st_size > 1_000_000:
        return True
    if not indir:
        return False
    try:
        MODEL_YOLU.parent.mkdir(parents=True, exist_ok=True)
        print("Konuşmacı modeli indiriliyor (tek seferlik, ~26 MB)...")
        gecici = MODEL_YOLU.with_suffix(".indiriliyor")
        urllib.request.urlretrieve(MODEL_URL, gecici)
        os.replace(gecici, MODEL_YOLU)
        return True
    except Exception as e:
        print(f"Konuşmacı modeli indirilemedi ({str(e)[:120]}).")
        return False


def _model():
    global _oturum
    if _oturum is None:
        import onnxruntime as ort

        secenek = ort.SessionOptions()
        secenek.log_severity_level = 3
        _oturum = ort.InferenceSession(str(MODEL_YOLU), sess_options=secenek, providers=["CPUExecutionProvider"])
    return _oturum


# ---------------------------------------------------------------------------
# Ses izi: Kaldi uyumlu log-mel özellikler + konuşmacı gömmesi
# ---------------------------------------------------------------------------
def _mel(f):
    return 1127.0 * np.log(1.0 + f / 700.0)


_MEL_BANKASI = None


def _mel_bankasi(n_mel: int = 80, n_fft: int = 512) -> np.ndarray:
    global _MEL_BANKASI
    if _MEL_BANKASI is None:
        frek = _mel(np.arange(n_fft // 2 + 1) * ORNEKLEME / n_fft)
        sinir = np.linspace(_mel(20.0), _mel(ORNEKLEME / 2), n_mel + 2)
        banka = np.zeros((n_mel, n_fft // 2 + 1), dtype=np.float32)
        for i in range(n_mel):
            sol, orta, sag = sinir[i], sinir[i + 1], sinir[i + 2]
            banka[i] = np.maximum(0.0, np.minimum((frek - sol) / (orta - sol), (sag - frek) / (sag - orta)))
        _MEL_BANKASI = banka
    return _MEL_BANKASI


def fbank(ses: np.ndarray) -> np.ndarray:
    """16 kHz float32 [-1, 1] ses -> [T, 80] log-mel (Kaldi fbank ile aynı: 25 ms pencere, 10 ms adım, hamming)."""
    x = ses.astype(np.float32) * 32768.0
    uz, kay, n_fft = 400, 160, 512
    if len(x) < uz:
        return np.zeros((0, 80), dtype=np.float32)
    t = 1 + (len(x) - uz) // kay
    kareler = x[np.arange(uz)[None, :] + kay * np.arange(t)[:, None]]
    kareler = kareler - kareler.mean(axis=1, keepdims=True)
    kareler = np.concatenate([kareler[:, :1] * 0.03, kareler[:, 1:] - 0.97 * kareler[:, :-1]], axis=1)
    pencere = 0.54 - 0.46 * np.cos(2 * np.pi * np.arange(uz) / (uz - 1))
    guc = np.abs(np.fft.rfft(kareler * pencere, n_fft, axis=1)) ** 2
    return np.log(np.maximum(guc @ _mel_bankasi().T, 1.1920929e-07)).astype(np.float32)


def ses_izleri(parcalar: list[np.ndarray]) -> np.ndarray:
    """Her ses parçası için birim uzunlukta gömme vektörü. Aynı uzunluktaki parçalar topluca işlenir."""
    model = _model()
    sonuc: list[np.ndarray | None] = [None] * len(parcalar)
    gruplar: dict[int, list[int]] = {}
    for i, p in enumerate(parcalar):
        gruplar.setdefault(len(p), []).append(i)
    for _, sira in gruplar.items():
        for b in range(0, len(sira), 32):
            dilim = sira[b:b + 32]
            oz = np.stack([fbank(parcalar[i]) for i in dilim])
            oz = oz - oz.mean(axis=1, keepdims=True)  # kanal etkisini azalt (ortalama çıkarma)
            g = model.run(None, {"feats": oz})[0]
            g = g / np.maximum(np.linalg.norm(g, axis=1, keepdims=True), 1e-9)
            for i, v in zip(dilim, g):
                sonuc[i] = v
    return np.stack(sonuc) if sonuc else np.zeros((0, 256), dtype=np.float32)


# ---------------------------------------------------------------------------
# Konuşma parçaları (VAD) ve pencereler
# ---------------------------------------------------------------------------
def konusma_parcalari(ses: np.ndarray) -> list[tuple[int, int]]:
    """Konuşma içeren aralıklar [(başlangıç, bitiş)] (örnek cinsinden). Silero VAD (faster-whisper içinden)."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    secenek = VadOptions(min_silence_duration_ms=300, speech_pad_ms=120)
    return [(int(p["start"]), int(p["end"])) for p in get_speech_timestamps(ses, secenek)]


def _pencereler(parcalar: list[tuple[int, int]]) -> list[tuple[int, int, int]]:
    """Her konuşma parçasını 1.5 sn'lik kayan pencerelere böler: [(parça no, başlangıç, bitiş)]."""
    n, adim, kisa = int(PENCERE_SN * ORNEKLEME), int(ADIM_SN * ORNEKLEME), int(EN_KISA_SN * ORNEKLEME)
    pencereler = []
    for pi, (a, b) in enumerate(parcalar):
        uz = b - a
        if uz < kisa:
            continue
        if uz <= n:
            pencereler.append((pi, a, b))
            continue
        baslar = list(range(a, b - n + 1, adim))
        if baslar[-1] + n < b:  # son parça da kapsansın
            baslar.append(b - n)
        pencereler += [(pi, s, s + n) for s in baslar]
    return pencereler


# ---------------------------------------------------------------------------
# Baskın konuşmacı = öğretmen
# ---------------------------------------------------------------------------
def _gruplar(izler: np.ndarray, sure: np.ndarray, en_fazla: int = 6) -> list[np.ndarray]:
    """Benzer ses izlerini gruplar; her grubun merkez vektörünü döndürür (en yoğun gruptan başlayarak)."""
    kalan = np.ones(len(izler), dtype=bool)
    merkezler = []
    for _ in range(en_fazla):
        if kalan.sum() < 2:
            break
        alt = np.where(kalan)[0]
        if len(alt) > 1500:  # çok uzun derslerde benzerlik tablosu büyümesin
            alt = alt[np.linspace(0, len(alt) - 1, 1500).astype(int)]
        benzerlik = izler[alt] @ izler[alt].T
        yogunluk = (np.maximum(0.0, benzerlik - 0.25) * sure[alt][None, :]).sum(axis=1)
        merkez = izler[alt[int(np.argmax(yogunluk))]]
        for _ in range(6):  # merkezi, ona benzeyenlerin ortalamasıyla inceltir
            uye = kalan & (izler @ merkez > ESIK - 0.05)
            if not uye.any():
                break
            yeni = (izler[uye] * sure[uye][:, None]).sum(axis=0)
            yeni /= max(np.linalg.norm(yeni), 1e-9)
            if float(yeni @ merkez) > 0.999:
                merkez = yeni
                break
            merkez = yeni
        uye = kalan & (izler @ merkez > ESIK - 0.05)
        if not uye.any():
            break
        merkezler.append(merkez)
        kalan &= ~uye
    return merkezler


def ogretmeni_ayir(ses: np.ndarray, parcalar: list[tuple[int, int]] | None = None) -> tuple[np.ndarray, dict]:
    """Öğretmene (baskın konuşmacıya) ait olmayan konuşmaları susturur.

    Dönüş: (yeni ses, bilgi). bilgi["uygulandi"] False ise ses değiştirilmemiştir ve bilgi["neden"] açıklar.
    Kararsız kalınan her durumda ses KORUNUR: öğretmenin sözünü yanlışlıkla silmek, bir öğrenci cümlesinin
    araya karışmasından daha kötüdür.
    """
    bilgi = {"uygulandi": False, "neden": "", "konusma_sn": 0.0, "ogretmen_sn": 0.0, "atlanan_sn": 0.0,
             "atlanan_parca": 0, "konusmaci_sayisi": 0, "atlanan_araliklar": []}
    if ses.size < ORNEKLEME:
        bilgi["neden"] = "kayıt çok kısa"
        return ses, bilgi
    if not model_hazir_mi():
        bilgi["neden"] = "konuşmacı modeli yok (indirilemedi)"
        return ses, bilgi
    try:
        if parcalar is None:
            parcalar = konusma_parcalari(ses)
    except Exception as e:
        bilgi["neden"] = f"konuşma algılayıcı çalışmadı ({str(e)[:80]})"
        return ses, bilgi

    bilgi["konusma_sn"] = round(sum(b - a for a, b in parcalar) / ORNEKLEME, 1)
    pencereler = _pencereler(parcalar)
    if bilgi["konusma_sn"] < EN_AZ_KONUSMA_SN or len(pencereler) < 6:
        bilgi["neden"] = "ayrım için yeterli konuşma yok"
        return ses, bilgi

    try:
        izler = ses_izleri([ses[a:b] for _, a, b in pencereler])
    except Exception as e:
        bilgi["neden"] = f"ses izi çıkarılamadı ({str(e)[:80]})"
        return ses, bilgi
    sure = np.array([(b - a) / ORNEKLEME for _, a, b in pencereler], dtype=np.float32)
    tam = sure >= PENCERE_SN - 1e-3  # merkezleri yalnızca tam uzunluktaki (güvenilir) pencerelerden kur
    if tam.sum() < 4:
        bilgi["neden"] = "ayrım için yeterli uzun konuşma yok"
        return ses, bilgi

    merkezler = _gruplar(izler[tam], sure[tam])
    if not merkezler:
        bilgi["neden"] = "baskın ses bulunamadı"
        return ses, bilgi
    m = np.stack(merkezler)
    # Aynı kişinin farklı tonları ayrı gruplara düşmüş olabilir: merkezleri birbirine benzeyen grupları birleştir
    kisi = list(range(len(m)))
    for a in range(len(m)):
        for b in range(a + 1, len(m)):
            if float(m[a] @ m[b]) >= ESIK_BIRLESTIR:
                eski, yeni_no = kisi[b], kisi[a]
                kisi = [yeni_no if k == eski else k for k in kisi]
    kisi = np.array(kisi)

    # Her pencere en çok benzediği kişiye yazılır; toplam konuşma süresi en uzun kişi öğretmendir
    tablo_grup = izler @ m.T
    kisiler = sorted(set(kisi.tolist()))
    tablo = np.stack([tablo_grup[:, kisi == k].max(axis=1) for k in kisiler], axis=1)
    en_yakin = tablo.argmax(axis=1)
    esik = np.where(tam, ESIK, ESIK_KISA)
    eslesen = tablo.max(axis=1) >= esik
    kisi_sure = np.array([sure[eslesen & (en_yakin == k)].sum() for k in range(len(kisiler))])
    ogretmen = int(np.argmax(kisi_sure))
    bilgi["konusmaci_sayisi"] = int((kisi_sure >= 2.0).sum())

    # Pencere kararı: +1 kesin öğretmen, -1 kesin başka biri, 0 kararsız
    benz_o = tablo[:, ogretmen]
    baska = np.delete(tablo, ogretmen, axis=1).max(axis=1) if tablo.shape[1] > 1 else np.full(len(tablo), -1.0)
    karar = np.zeros(len(pencereler), dtype=np.int8)
    karar[benz_o >= esik] = 1
    karar[(baska >= ESIK) & (baska >= benz_o + 0.15)] = -1          # başka bir kişiye açıkça daha yakın
    karar[tam & (benz_o < ESIK_DIGER) & (karar == 0)] = -1          # kimseye benzemiyor ama öğretmen de değil
    # Kararsızlar (kısık söz sonları, "evet/peki" gibi kısa sözler): zamanda en yakın kesin pencereye bak
    # Karar, en yakındaki kararsızdan başlayarak zincirleme yayılır (söz sonundaki art arda kısık parçalar için).
    yakin = int(KOMSU_SN * ORNEKLEME)
    bas = np.array([p[1] for p in pencereler])
    bit = np.array([p[2] for p in pencereler])
    while True:
        kararsiz, kesin = np.flatnonzero(karar == 0), np.flatnonzero(karar != 0)
        if not len(kararsiz) or not len(kesin):
            break
        # her kararsız pencerenin her kesin pencereye uzaklığı (aradaki boşluk; çakışıyorsa 0)
        bosluk = np.maximum(0, np.maximum(bas[kararsiz][:, None], bas[kesin][None, :])
                            - np.minimum(bit[kararsiz][:, None], bit[kesin][None, :]))
        bosluk = bosluk - (karar[kesin][None, :] == 1) * 1e-3   # eşit uzaklıkta öğretmen kararı önce gelir
        i, j = np.unravel_index(int(np.argmin(bosluk)), bosluk.shape)
        if bosluk[i, j] > yakin:
            break
        karar[kararsiz[i]] = karar[kesin[j]]
    karar[karar == 0] = 1   # yakınında kesin karar olmayan kararsızlar: koru

    # Örnek düzeyinde karar: bir anı kapsayan pencerelerin oyu (eşitlikte koru)
    oy = np.zeros(len(ses), dtype=np.int16)
    sayi = np.zeros(len(ses), dtype=np.int16)
    for (pi, a, b), k in zip(pencereler, karar):
        oy[a:b] += int(k)
        sayi[a:b] += 1
    koru = np.ones(len(ses), dtype=bool)
    son_karar = True
    son_bitis = -10 * ORNEKLEME
    for pi, (a, b) in enumerate(parcalar):
        if sayi[a:b].max(initial=0) == 0:   # ses izi çıkarılamayacak kadar kısa parça: hemen önceki kararı devral
            koru[a:b] = son_karar if a - son_bitis <= yakin else True
            continue
        dilim_koru = oy[a:b] >= 0
        dilim_koru[sayi[a:b] == 0] = True
        koru[a:b] = dilim_koru
        son_karar, son_bitis = bool(dilim_koru[-1]), b

    # Atlanan aralıklar (konuşma içinde olup korunmayan yerler)
    konusma = np.zeros(len(ses), dtype=bool)
    for a, b in parcalar:
        konusma[a:b] = True
    sil = konusma & ~koru
    degisim = np.flatnonzero(np.diff(np.concatenate([[0], sil.astype(np.int8), [0]])))
    araliklar = [(int(a), int(b)) for a, b in zip(degisim[::2], degisim[1::2]) if b - a >= int(0.3 * ORNEKLEME)]

    bilgi["ogretmen_sn"] = round(float((konusma & koru).sum()) / ORNEKLEME, 1)
    if not araliklar:
        bilgi.update(uygulandi=True, neden="başka konuşmacı bulunmadı")
        return ses, bilgi
    if bilgi["ogretmen_sn"] < 0.4 * bilgi["konusma_sn"]:
        # Baskın bir ses yok (ör. uzun tartışma / grup çalışması): yanlış kişiyi öğretmen sanmaktansa dokunma
        bilgi["neden"] = "baskın bir konuşmacı ayırt edilemedi"
        bilgi["ogretmen_sn"] = 0.0
        return ses, bilgi

    yeni = ses.copy()
    gecis = int(0.03 * ORNEKLEME)
    for a, b in araliklar:
        yeni[a:b] = 0.0
        if a - gecis >= 0:  # tık sesi olmasın diye kısa geçiş
            yeni[a - gecis:a] *= np.linspace(1.0, 0.0, gecis, dtype=np.float32)
        if b + gecis <= len(yeni):
            yeni[b:b + gecis] *= np.linspace(0.0, 1.0, gecis, dtype=np.float32)
    bilgi.update(
        uygulandi=True,
        atlanan_sn=round(sum(b - a for a, b in araliklar) / ORNEKLEME, 1),
        atlanan_parca=len(araliklar),
        atlanan_araliklar=[[round(a / ORNEKLEME, 1), round(b / ORNEKLEME, 1)] for a, b in araliklar],
    )
    return yeni, bilgi


def ozet_cumlesi(bilgi: dict) -> str:
    if not bilgi.get("uygulandi"):
        return f"Öğretmen sesi ayrımı yapılmadı: {bilgi.get('neden') or 'bilinmeyen neden'}."
    if not bilgi.get("atlanan_parca"):
        return f"Öğretmen sesi ayrımı: {bilgi['konusma_sn']:.0f} sn konuşmanın tamamı aynı kişiye ait görünüyor."
    return (f"Öğretmen sesi ayrımı: {bilgi['konusma_sn']:.0f} sn konuşmanın {bilgi['ogretmen_sn']:.0f} sn'si öğretmene ait; "
            f"başka seslere ait {bilgi['atlanan_parca']} parça ({bilgi['atlanan_sn']:.0f} sn) metne çevrilmedi.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Kullanım: python ses_hatti/konusmaci.py <ses_dosyasi>")
        sys.exit(1)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from transkript import sesi_oku  # noqa: E402

    _ses = sesi_oku(sys.argv[1])
    _, _bilgi = ogretmeni_ayir(_ses)
    print(ozet_cumlesi(_bilgi))
    for _a, _b in _bilgi["atlanan_araliklar"]:
        print(f"  atlandı: {_a:7.1f} - {_b:7.1f} sn")
