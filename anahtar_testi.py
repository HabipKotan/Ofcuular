"""
Gemini API anahtarı testi: .env'deki her anahtarı tek tek dener.

    python anahtar_testi.py

Her anahtar için şunu yazar:  ÇALIŞIYOR / GEÇERSİZ (401-403) / KOTA DOLDU (429) / başka hata
Anahtarın tamamı ekrana yazılmaz, yalnızca başı ve sonu (ör. AIza…x7Qk).
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ENV = Path(__file__).resolve().parent / ".env"
try:
    from dotenv import load_dotenv
    load_dotenv(ENV, override=True)
except ImportError:
    pass

from llm import gemini_havuzu as h  # noqa: E402

print(f"\n.env dosyası: {ENV}  ({'VAR' if ENV.exists() else 'YOK!'})")
for ad in ("GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_API_KEY"):
    if os.environ.get(ad):
        print(f"  Not: bilgisayarda {ad} ortam değişkeni tanımlı (program bunu kullanmaz, sorun değil).")

anahtarlar = h.anahtarlar()
if not anahtarlar:
    sys.exit("Hiç anahtar bulunamadı. .env içine GEMINI_API_KEY=... satırını yazıp kaydedin.")

from google import genai  # noqa: E402

model = h.modeller()[-1]  # en hafif model: kotayı az harcar
print(f"Test modeli: {model}\n")
calisan = 0
for no, k in enumerate(anahtarlar, 1):
    etiket = h.anahtar_etiketi(k)
    tur = "AIza (klasik)" if k.startswith("AIza") else ("AQ. (yeni tip)" if k.startswith("AQ.") else "tanınmayan biçim!")
    try:
        y = genai.Client(api_key=k, vertexai=False).models.generate_content(model=model, contents="Sadece 'tamam' yaz.")
        print(f"  anahtar {no} [{etiket}] {tur}, {len(k)} karakter:  ÇALIŞIYOR  ({(y.text or '').strip()[:20]})")
        calisan += 1
    except Exception as e:
        m = str(e)
        if h._kota_doldu(m) or "429" in m:
            sonuc = "KOTA DOLDU (bugünlük; anahtar sağlam)"
            calisan += 1
        elif h._yetki_hatasi(m):
            sonuc = "GEÇERSİZ / yetkisiz -> anahtarı AI Studio'dan yeniden kopyalayın ya da yeni anahtar oluşturun"
        else:
            sonuc = f"HATA: {m[:150]}"
        print(f"  anahtar {no} [{etiket}] {tur}, {len(k)} karakter:  {sonuc}")

print("\nSonuç:", "en az bir anahtar sağlam." if calisan else "hiçbir anahtar çalışmıyor!")
