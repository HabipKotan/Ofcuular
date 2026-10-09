"""
Mikrofon testi: hangi mikrofon sesimizi duyuyor?

    python mikrofon_testi.py            -> mikrofonları listeler, varsayılanı 5 sn kaydeder
    python mikrofon_testi.py 3          -> 3 numaralı mikrofonu 5 sn kaydeder

Kayıt sırasında normal sesle konuşun. Sonunda ses seviyesi yazılır ve
mikrofon_testi_<numara>.wav dosyası kaydedilir (çift tıklayıp dinleyebilirsiniz).

Doğru mikrofonu bulunca .env dosyasına ekleyin:
    MIKROFON=3
"""

import sys
import time
import wave

import numpy as np
import sounddevice as sd

SURE = 5

print("\n=== Bilgisayardaki mikrofonlar (giriş cihazları) ===")
varsayilan = sd.default.device[0]
for i, c in enumerate(sd.query_devices()):
    if c["max_input_channels"] > 0:
        isaret = "  <-- VARSAYILAN" if i == varsayilan else ""
        print(f"  [{i}] {c['name']}  ({int(c['default_samplerate'])} Hz){isaret}")

cihaz = int(sys.argv[1]) if len(sys.argv) > 1 else varsayilan
bilgi = sd.query_devices(cihaz)
oran = int(bilgi["default_samplerate"])
print(f"\nTest edilen: [{cihaz}] {bilgi['name']}")
print(f">>> {SURE} saniye boyunca KONUŞUN (ör. 'bir, iki, üç, deneme')...")
time.sleep(0.5)

ses = sd.rec(int(SURE * oran), samplerate=oran, channels=1, dtype="int16", device=cihaz)
for kalan in range(SURE, 0, -1):
    print(f"   {kalan}...", flush=True)
    time.sleep(1)
sd.wait()

a = ses.astype(np.float32).ravel() / 32768.0
pencere = max(1, oran // 10)
parcalar = [a[i:i + pencere] for i in range(0, len(a), pencere)]
seviyeler = [float(np.sqrt(np.mean(p * p))) for p in parcalar if len(p)]
tepe = max(seviyeler) if seviyeler else 0.0
ort = float(np.mean(seviyeler)) if seviyeler else 0.0

dosya = f"mikrofon_testi_{cihaz}.wav"
with wave.open(dosya, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(oran)
    w.writeframes(ses.tobytes())

print(f"\nEn yüksek seviye: {tepe:.4f}   ortalama: {ort:.4f}")
if tepe < 0.003:
    print("SONUÇ: Neredeyse HİÇ SES YOK. Bu mikrofon sizi duymuyor (ya kapalı/sessize alınmış ya da yanlış cihaz).")
    print("       Listedeki başka bir numarayı deneyin:  python mikrofon_testi.py <numara>")
elif tepe < 0.02:
    print("SONUÇ: Ses var ama ÇOK KISIK. Mikrofona yaklaşın ya da Windows'ta mikrofon seviyesini artırın.")
else:
    print("SONUÇ: Ses iyi geliyor. Bu mikrofonu kullanabilirsiniz.")
    if cihaz != varsayilan:
        print(f"       Kayıt sisteminin bunu kullanması için .env dosyasına ekleyin:  MIKROFON={cihaz}")
print(f"Kayıt dosyası: {dosya} (çift tıklayıp dinleyin)\n")
