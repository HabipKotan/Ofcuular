"""
Gemini anahtar + model havuzu (kota dolunca otomatik yedeğe geçer)
==================================================================
Ücretsiz katmanda kota PROJE (anahtar) ve MODEL başınadır (ör. gemini-3.5-flash: günde 20 istek).
Bu modül sırayla şunları dener:
    her model için -> her anahtar   (önce en iyi model, tüm anahtarlarla; sonra bir sonraki model)
- Günlük kotası dolan (anahtar, model) çifti bu süreç boyunca bir daha denenmez (zaman kaybı olmasın).
- Bulunamayan model (404) hiçbir anahtarla tekrar denenmez.
- Anlık yoğunlukta (503 / overloaded) bir kez kısa bekleyip tekrar dener.

.env:
    GEMINI_API_KEY=...        (zorunlu)
    GEMINI_API_KEY_2=...      (isteğe bağlı: başka bir Google hesabı / projesinden)
    GEMINI_API_KEY_3=...
    LLM_MODEL=...             (isteğe bağlı: listenin başına alınır)
"""

from __future__ import annotations

import os
import time
from typing import Optional, Tuple

ANAHTAR_ADLARI = ("GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3", "GEMINI_API_KEY_4")
TEMEL_MODELLER = ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite",
                  "gemini-2.5-flash", "gemini-2.5-flash-lite"]

_istemciler: dict = {}
_bildirildi = False
_kapali: dict = {}        # (anahtar_no, model) -> bu zamana kadar deneme
_olmayan_model: set = set()
_gecersiz_anahtar: dict = {}   # anahtar_no -> neden (401/403: anahtar hiçbir modelde çalışmaz, tekrar denenmez)


def _temizle(k: str) -> str:
    """Kopyalarken gelen boşluk, tırnak, satır sonu vb. temizlenir (yarım/bozuk anahtar 401 verir)."""
    return "".join((k or "").split()).strip("'\"`;,")


def anahtarlar() -> list[str]:
    liste = [_temizle(os.environ.get(a) or "") for a in ANAHTAR_ADLARI]
    return list(dict.fromkeys(k for k in liste if k and not k.upper().startswith("BURAYA")))


def modeller() -> list[str]:
    return list(dict.fromkeys(m for m in [(os.environ.get("LLM_MODEL") or "").strip()] + TEMEL_MODELLER if m))


def _istemci(anahtar: str):
    if anahtar not in _istemciler:
        from google import genai
        _istemciler[anahtar] = genai.Client(api_key=anahtar, vertexai=False)  # Vertex ortam değişkeni karışmasın
    return _istemciler[anahtar]


def _kota_doldu(metin: str) -> bool:
    m = metin.lower()
    return ("429" in m or "resource_exhausted" in m) and ("quota" in m or "perday" in m or "per day" in m)


def _yetki_hatasi(metin: str) -> bool:
    m = metin.lower()
    return any(k in m for k in ("401", "unauthenticated", "api_key_invalid", "api key not valid",
                                "permission_denied", "403", "access_token_type_unsupported",
                                "api_key_service_blocked"))


def anahtar_etiketi(anahtar: str) -> str:
    """Ekranda göstermek için anahtarın yalnızca başı/sonu (ör. AIza…x7Qk)."""
    return f"{anahtar[:4]}…{anahtar[-4:]}" if len(anahtar) > 10 else "(çok kısa)"


def _gecici(metin: str) -> bool:
    m = metin.lower()
    return any(k in m for k in ("503", "500", "unavailable", "overloaded", "high demand", "deadline",
                                "timeout", "timed out", "connection", "429"))


def uret(icerik: str, sistem: Optional[str] = None, sicaklik: float = 0.3, log=print) -> Tuple[str, str]:
    """JSON yanıt üretir. Dönüş: (metin, kullanılan model). Hiçbiri olmazsa RuntimeError."""
    from google.genai import types

    keys = anahtarlar()
    if not keys:
        raise RuntimeError("GEMINI_API_KEY tanımlı değil (.env dosyasına yazın).")
    global _bildirildi
    if not _bildirildi:
        _bildirildi = True
        log("  Gemini anahtarları: " + ", ".join(f"{i} [{anahtar_etiketi(k)}]" for i, k in enumerate(keys, 1)))
    son_hata = None
    for model in modeller():
        if model in _olmayan_model:
            continue
        for no, anahtar in enumerate(keys, 1):
            if no in _gecersiz_anahtar or _kapali.get((no, model), 0) > time.time():
                continue
            for deneme in range(2):
                try:
                    yanit = _istemci(anahtar).models.generate_content(
                        model=model, contents=icerik,
                        config=types.GenerateContentConfig(system_instruction=sistem,
                                                           response_mime_type="application/json",
                                                           temperature=sicaklik))
                    if no > 1 or model != modeller()[0]:
                        log(f"  (yedek kullanıldı: anahtar {no}, model {model})")
                    return yanit.text or "", model
                except Exception as e:
                    son_hata, metin = e, str(e)
                    if "404" in metin or "not found" in metin.lower():
                        _olmayan_model.add(model)
                        log(f"  ({model} bulunamadı, atlanıyor)")
                        break
                    if _yetki_hatasi(metin) and not _kota_doldu(metin):
                        _gecersiz_anahtar[no] = metin[:160]
                        log(f"  (anahtar {no} [{anahtar_etiketi(anahtar)}] GEÇERSİZ / yetkisiz: {metin[:100]})")
                        break
                    if _kota_doldu(metin):
                        _kapali[(no, model)] = time.time() + 1800  # günlük kota: bu süreçte tekrar deneme
                        log(f"  (anahtar {no} / {model}: kota doldu, sıradakine geçiliyor)")
                        break
                    if _gecici(metin) and deneme == 0:
                        time.sleep(2)
                        continue
                    log(f"  (anahtar {no} / {model} çalışmadı: {metin[:120]})")
                    break
            if model in _olmayan_model:
                break
    ozet = []
    for no, anahtar in enumerate(keys, 1):
        if no in _gecersiz_anahtar:
            ozet.append(f"anahtar {no} [{anahtar_etiketi(anahtar)}]: GEÇERSİZ (yeniden kopyalayın / yeni anahtar alın)")
        elif any(_kapali.get((no, m), 0) > time.time() for m in modeller()):
            ozet.append(f"anahtar {no} [{anahtar_etiketi(anahtar)}]: günlük kota doldu")
        else:
            ozet.append(f"anahtar {no} [{anahtar_etiketi(anahtar)}]: yanıt vermedi")
    raise RuntimeError("Hiçbir Gemini anahtarı/modeli yanıt vermedi. " + " | ".join(ozet)
                       + f". Son hata: {str(son_hata)[:200]}")
