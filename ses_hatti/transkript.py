"""
Ders ses kaydını zaman damgalı Türkçe metne çevirir.

Kullanım:
    python transkript.py ders.m4a
    python transkript.py ders.wav --konu "Matematik: kesirler, pay, payda"   (konu ve terimler: doğruluğu artırır)
    python transkript.py ders.wav --tum-sesler      (öğretmen sesi ayrımı yapma; herkesin konuşmasını çevir)

Adımlar:
    1) Ses 16 kHz tek kanala çevrilir; kısık kayıtlar yükseltilir.
    2) Öğretmenin sesi ayrılır (konusmaci.py): ders boyunca en çok konuşan kişi öğretmen sayılır,
       başka seslere ait bölümler metne çevrilmeden önce susturulur.
    3) Whisper ile metne çevrilir (konu/terimler her bölümde ipucu olarak verilir).
    4) Whisper'ın sessizlikte uydurduğu kalıp cümleler ("Altyazı M.K." gibi) ve tekrarlar ayıklanır.

Çıktı:
    transkript.json        ->  [{"baslangic": 0.0, "bitis": 4.2, "metin": "..."}, ...]
    transkript.txt         ->  okunabilir hali (dakika:saniye  metin)
    transkript_bilgi.json  ->  model, süre, öğretmen sesi ayrımı özeti

Kurulum (bir kez):
    pip install faster-whisper
"""

import json
import os
import re
import sys
import time

import av
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(1, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from core import model_yukle  # noqa: E402  (Türkçe karakterli yollara karşı korumalı model yükleme)

try:  # arayüz projesindeki .env dosyasından WHISPER_MODEL / WHISPER_LANGUAGE al
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"), override=True)
except ImportError:
    pass

# "small" Türkçe için iyi denge. Çok yavaş kalırsa "base" yap, internet çok yavaşsa da "base" daha küçük iner.
# "medium" daha doğru yazar ama işlemcide dersin süresi kadar (ya da daha uzun) sürebilir.
MODEL_BOYUTU = os.environ.get("WHISPER_MODEL") or "small"
DIL = os.environ.get("WHISPER_LANGUAGE") or "tr"

# Whisper'ın sessizlik / gürültü üzerinde sık uydurduğu kalıplar (YouTube altyazılarından ezberlenmiş).
# Bir parça yalnızca bunlardan birinden oluşuyorsa atılır.
UYDURMA_KALIPLAR = (
    "altyazı m.k", "altyazi m.k", "altyazı mk", "altyazı", "alt yazı m.k",
    "izlediğiniz için teşekkür ederim", "izlediğiniz için teşekkürler", "izlediğiniz için teşekkür ederiz",
    "abone olmayı unutmayın", "abone olmayı ve beğenmeyi unutmayın", "kanalıma abone olmayı unutmayın",
    "bir sonraki videoda görüşmek üzere", "bir sonraki videoda görüşürüz", "sonraki videoda görüşmek üzere",
    "videoyu beğenmeyi unutmayın", "sesli betimleme", "çeviri ve altyazı", "hoşçakalın", "teşekkürler",
    "müzik", "[müzik]", "(müzik)", "alkış", "[alkış]", "thank you", "thanks for watching", "you",
)


def arguman(ad: str):
    """--ad deger biçimindeki argümanı döndürür."""
    if ad in sys.argv:
        i = sys.argv.index(ad)
        if i + 1 < len(sys.argv) and sys.argv[i + 1].strip():
            return sys.argv[i + 1].strip()
    return None


def konu_terimleri(konu: str | None) -> str | None:
    """Ders adındaki kelimeler: Whisper'a HER bölümde ipucu olarak verilir (hotwords)."""
    if not konu:
        return None
    kelimeler = [k for k in re.split(r"[\s,;:./()\-]+", konu) if len(k) > 2]
    return " ".join(dict.fromkeys(kelimeler)) or None


def konu_ipucu(konu: str | None) -> str:
    """İlk bölüm için bağlam cümlesi: dil, üslup ve konu (noktalama ve doğru yazım örneği olur)."""
    temel = "Bu bir Türkçe ders kaydıdır. Öğretmen sınıfta konuyu anlatıyor, örnekler çözüyor."
    return f"{temel} Dersin konusu: {konu}." if konu else temel


def sesi_oku(yol: str) -> np.ndarray:
    """Ses dosyasını 16 kHz mono float32 diziye çevirir (PyAV sürüm uyumsuzluğunu atlar)."""
    # Dosyayı Python açar, PyAV'ye dosya nesnesi verilir: yolda Türkçe karakter olsa da sorun çıkmaz
    dosya = open(yol, "rb")
    kap = av.open(dosya)
    donusturucu = av.AudioResampler(format="s16", layout="mono", rate=16000)
    parcalar = []
    for kare in kap.decode(audio=0):
        for k in donusturucu.resample(kare):
            parcalar.append(k.to_ndarray().reshape(-1))
    for k in donusturucu.resample(None):  # kalanları boşalt
        parcalar.append(k.to_ndarray().reshape(-1))
    kap.close()
    dosya.close()
    if not parcalar:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(parcalar).astype(np.float32) / 32768.0


def sesi_yukselt(ses: np.ndarray) -> np.ndarray:
    """Kısık kayıtları (uzak / Bluetooth mikrofon) konuşma algılayıcının duyabileceği seviyeye çıkarır.
    Yalnızca seviyeyi ölçekler; ses zaten yeterince yüksekse dokunmaz."""
    if ses.size == 0:
        return ses
    ses = ses - float(np.mean(ses))  # mikrofonun sabit kayması (DC) varsa kaldır
    tepe = float(np.percentile(np.abs(ses), 99.9))
    if tepe < 1e-4:  # neredeyse tam sessizlik: yükseltmek yalnızca gürültü üretir
        return ses
    if tepe < 0.5:
        ses = np.clip(ses * min(0.7 / tepe, 30.0), -1.0, 1.0).astype(np.float32)
        print(f"Ses kısık kaydedilmiş (tepe {tepe:.3f}); seviye yükseltildi.")
    return ses.astype(np.float32)


def _sade(metin: str) -> str:
    metin = metin.replace("İ", "i").replace("I", "ı").lower()  # Türkçe büyük/küçük harf (İ->i, I->ı)
    return re.sub(r"[\s.!?…,;:'\"“”‘’\-–—]+", " ", metin).strip()


def uydurma_mi(metin: str, ipucu: str = "") -> bool:
    """Parça, Whisper'ın sessizlikte uydurduğu bilinen bir kalıp mı (ya da verdiğimiz ipucunun tekrarı mı)?"""
    sade = _sade(metin)
    if not sade:
        return True
    if any(sade == _sade(k) for k in UYDURMA_KALIPLAR):
        return True
    if "altyazı" in sade and len(sade) < 40:
        return True
    ipucu_sade = _sade(ipucu)
    return bool(ipucu_sade) and len(sade) > 12 and sade in ipucu_sade


def parcalari_ayikla(parcalar: list[dict], ipucu: str = "") -> tuple[list[dict], int]:
    """Uydurma kalıpları, güvenilmez (sessizlik üstüne yazılmış) parçaları ve art arda tekrarları atar."""
    temiz: list[dict] = []
    atilan = 0
    for p in parcalar:
        metin = p["metin"].strip()
        guvensiz = p.get("sessizlik_olasiligi", 0.0) > 0.6 and p.get("ortalama_logprob", 0.0) < -1.0
        tekrar = len(temiz) >= 2 and _sade(metin) == _sade(temiz[-1]["metin"]) == _sade(temiz[-2]["metin"])
        if uydurma_mi(metin, ipucu) or guvensiz or tekrar:
            atilan += 1
            continue
        temiz.append(p)
    return temiz, atilan


def dk_sn(saniye: float) -> str:
    return f"{int(saniye // 60):02d}:{int(saniye % 60):02d}"


def main():
    if len(sys.argv) < 2:
        print("Kullanım: python transkript.py <ses_dosyasi> [--konu \"...\"] [--tum-sesler]")
        sys.exit(1)

    ses_dosyasi = sys.argv[1]
    konu = arguman("--konu")
    t0 = time.time()
    print(f"'{ses_dosyasi}' okunuyor...")
    ses = sesi_yukselt(sesi_oku(ses_dosyasi))
    bilgi = {"model": MODEL_BOYUTU, "dil": DIL, "sure_saniye": round(len(ses) / 16000, 1), "konu": konu or ""}

    # --- Öğretmenin sesini ayır (başka sesler metne çevrilmez) ---
    ayrim_istendi = "--tum-sesler" not in sys.argv and os.environ.get("OGRETMEN_SESI_AYRIMI", "1") != "0"
    if ayrim_istendi and ses.size >= 16000:
        try:
            import konusmaci

            ses, ayrim = konusmaci.ogretmeni_ayir(ses)
            print(konusmaci.ozet_cumlesi(ayrim))
        except Exception as e:  # ayrım çalışmazsa dersi kaybetme: tüm sesle devam et
            ayrim = {"uygulandi": False, "neden": f"hata: {str(e)[:120]}"}
            print(f"Öğretmen sesi ayrımı yapılamadı ({str(e)[:120]}); tüm sesler çevriliyor.")
        bilgi["ogretmen_ayrimi"] = ayrim
    else:
        bilgi["ogretmen_ayrimi"] = {"uygulandi": False, "neden": "kapalı" if not ayrim_istendi else "kayıt çok kısa"}

    ipucu = konu_ipucu(konu)
    sonuc = []
    if ses.size < 16000:  # 1 saniyeden kısa / boş kayıt
        print("Ses dosyası boş ya da çok kısa; metne çevrilecek bir şey yok.")
    else:
        print(f"Model yükleniyor ({MODEL_BOYUTU})... İlk çalıştırmada model indirilir, biraz sürebilir.")
        # Kullanıcı klasöründe Türkçe karakter varsa (ör. C:/Users/Öğretmen) model İngilizce karakterli klasöre iner
        model = model_yukle.whisper_modeli(MODEL_BOYUTU, device="cpu", compute_type="int8")
        print("Metne çevriliyor...")
        ayarlar = dict(
            language=DIL,
            vad_filter=True,  # sessiz kısımları atlar
            vad_parameters=dict(min_silence_duration_ms=700, speech_pad_ms=300),  # kelime başı/sonu kesilmesin
            initial_prompt=ipucu,                 # ilk bölüm için bağlam
            hotwords=konu_terimleri(konu),        # konu terimleri HER bölümde ipucu olur
            beam_size=5,
            temperature=(0.0, 0.2, 0.4, 0.6),     # emin olamadığı bölümü farklı ayarla yeniden dener
            compression_ratio_threshold=2.4,      # kendini tekrar eden çıktıyı reddeder
            no_speech_threshold=0.6,
            condition_on_previous_text=False,     # bir hatanın sonraki cümlelere yayılmasını / tekrar uydurmayı azaltır
        )
        try:
            segmentler, _ = model.transcribe(ses, **ayarlar)
        except TypeError:  # eski faster-whisper sürümü "hotwords" tanımıyor olabilir
            ayarlar.pop("hotwords", None)
            segmentler, _ = model.transcribe(ses, **ayarlar)
        ham = []
        for s in segmentler:
            metin = (s.text or "").strip()
            if not metin:
                continue
            ham.append({
                "baslangic": round(s.start, 1), "bitis": round(s.end, 1), "metin": metin,
                "sessizlik_olasiligi": float(getattr(s, "no_speech_prob", 0.0) or 0.0),
                "ortalama_logprob": float(getattr(s, "avg_logprob", 0.0) or 0.0),
            })
        temiz, atilan = parcalari_ayikla(ham, ipucu)
        if atilan:
            print(f"{atilan} parça ayıklandı (sessizlik üstüne uydurulmuş kalıp / tekrar).")
        bilgi["ayiklanan_parca"] = atilan
        for p in temiz:
            sonuc.append({"baslangic": p["baslangic"], "bitis": p["bitis"], "metin": p["metin"]})
            print(f"[{dk_sn(p['baslangic'])}] {p['metin']}")

    with open("transkript.json", "w", encoding="utf-8") as f:
        json.dump(sonuc, f, ensure_ascii=False, indent=2)
    with open("transkript.txt", "w", encoding="utf-8") as f:
        for p in sonuc:
            f.write(f"[{dk_sn(p['baslangic'])}] {p['metin']}\n")
    bilgi["parca_sayisi"] = len(sonuc)
    with open("transkript_bilgi.json", "w", encoding="utf-8") as f:
        json.dump(bilgi, f, ensure_ascii=False, indent=2)

    print(f"\nBitti ({time.time() - t0:.0f} sn). {len(sonuc)} parça.")
    print("Kaydedildi: transkript.json, transkript.txt")


if __name__ == "__main__":
    main()
