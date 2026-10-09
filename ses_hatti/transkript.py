"""
Ders ses kaydını zaman damgalı Türkçe metne çevirir.

Kullanım:
    python transkript.py ders.m4a
    python transkript.py ders.wav --konu "Matematik: kesirler, pay, payda"   (isteğe bağlı ipucu)

Çıktı:
    transkript.json  ->  [{"baslangic": 0.0, "bitis": 4.2, "metin": "..."}, ...]
    transkript.txt   ->  okunabilir hali (dakika:saniye  metin)

Kurulum (bir kez):
    pip install faster-whisper
"""

import json
import sys
import time

import av
import numpy as np
from faster_whisper import WhisperModel

# "small" Türkçe için iyi denge. Çok yavaş kalırsa "base" yap, internet çok yavaşsa da "base" daha küçük iner.
MODEL_BOYUTU = "small"

import os

MODEL_BOYUTU = os.environ.get("WHISPER_MODEL", MODEL_BOYUTU)


def konu_ipucu():
    """--konu ile verilen ders konusu/terimleri; Whisper bu kelimeleri daha doğru yazar."""
    if "--konu" in sys.argv:
        i = sys.argv.index("--konu")
        if i + 1 < len(sys.argv) and sys.argv[i + 1].strip():
            return f"Ders konusu: {sys.argv[i + 1].strip()}."
    return None


def sesi_oku(yol: str) -> np.ndarray:
    """Ses dosyasını 16 kHz mono float32 diziye çevirir (PyAV sürüm uyumsuzluğunu atlar)."""
    kap = av.open(yol)
    donusturucu = av.AudioResampler(format="s16", layout="mono", rate=16000)
    parcalar = []
    for kare in kap.decode(audio=0):
        for k in donusturucu.resample(kare):
            parcalar.append(k.to_ndarray().reshape(-1))
    for k in donusturucu.resample(None):  # kalanları boşalt
        parcalar.append(k.to_ndarray().reshape(-1))
    kap.close()
    return np.concatenate(parcalar).astype(np.float32) / 32768.0


def dk_sn(saniye: float) -> str:
    return f"{int(saniye // 60):02d}:{int(saniye % 60):02d}"


def main():
    if len(sys.argv) < 2:
        print("Kullanım: python transkript.py <ses_dosyasi>")
        sys.exit(1)

    ses_dosyasi = sys.argv[1]
    print(f"Model yükleniyor ({MODEL_BOYUTU})... İlk çalıştırmada model indirilir, biraz sürebilir.")
    model = WhisperModel(MODEL_BOYUTU, device="cpu", compute_type="int8")

    print(f"'{ses_dosyasi}' metne çevriliyor...")
    t0 = time.time()
    ses = sesi_oku(ses_dosyasi)
    segmentler, bilgi = model.transcribe(
        ses,
        language="tr",
        vad_filter=True,  # sessiz kısımları atlar
        initial_prompt=konu_ipucu(),
        beam_size=5,
        condition_on_previous_text=False,  # bir hatanın sonraki cümlelere yayılmasını / tekrar uydurmayı azaltır
    )

    sonuc = []
    for s in segmentler:
        parca = {
            "baslangic": round(s.start, 1),
            "bitis": round(s.end, 1),
            "metin": s.text.strip(),
        }
        sonuc.append(parca)
        print(f"[{dk_sn(s.start)}] {parca['metin']}")

    with open("transkript.json", "w", encoding="utf-8") as f:
        json.dump(sonuc, f, ensure_ascii=False, indent=2)

    with open("transkript.txt", "w", encoding="utf-8") as f:
        for p in sonuc:
            f.write(f"[{dk_sn(p['baslangic'])}] {p['metin']}\n")

    print(f"\nBitti ({time.time() - t0:.0f} sn). {len(sonuc)} parça.")
    print("Kaydedildi: transkript.json, transkript.txt")


if __name__ == "__main__":
    main()
