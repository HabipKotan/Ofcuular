"""
Transkripti (transkript.json) yapay zekâ ile ders notlarına çevirir.
Odak verisi varsa, odağın en çok düştüğü konuyu bulup o bölümü güçlendirir.

Kullanım:
    python notlar.py                                  (odak verisini kendisi bulur, aşağıya bak)
    python notlar.py --odak kayitlar/dikkat_xxx.csv   (belirli bir odak dosyası)
    python notlar.py --sahte-odak                     (test için sahte odak verisi üretir)

Odak verisini şu sırayla arar:
    1) --odak ile verilen dosya
    2) klasördeki odak.csv            (saniye,odak_skoru  biçimi)
    3) kayitlar/ klasöründeki en yeni dikkat_*.csv  (dikkat_olcer.py çıktısı)

Kurulum (bir kez):
    pip install google-genai

API anahtarı: aistudio.google.com -> "Get API key" -> anahtarı aşağıdaki API_ANAHTARI satırına yapıştır.

Çıktı:
    notlar.json  ->  arayüzün kullanacağı TEK dosya (notlar + quiz + odak serisi)
    notlar.md    ->  okunabilir hali (kontrol için)

Tüm odak skorları 0-100 ölçeğindedir.
"""

import csv
import glob
import json
import os
import sys

from google import genai
from google.genai import types

try:  # arayüz projesindeki .env dosyasından GEMINI_API_KEY'i al
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))
    load_dotenv()
except ImportError:
    pass

API_ANAHTARI = os.environ.get("GEMINI_API_KEY", "BURAYA_API_ANAHTARINI_YAPISTIR")

# Sırayla denenir; ilki çalışmazsa ikincisine geçer.
MODELLER = ["gemini-3.5-flash", "gemini-2.5-flash"]

ODAK_ESIGI = 60  # bir bölümün ortalama odağı (0-100) bunun altındaysa "zorlanılan konu" sayılır

NEDEN_METNI = {
    "yana": "öğrencilerin önemli bir kısmı yana bakıyordu (dikkat dağınıklığı)",
    "egik": "öğrencilerin önemli bir kısmının başı eğikti (telefon ya da kopma olabilir)",
    "kapali": "gözü kapalı / yorgun görünen öğrenci oranı yüksekti",
}


# ---------------------------------------------------------------- yardımcılar

def dk_sn(saniye: float) -> str:
    return f"{int(saniye // 60):02d}:{int(saniye % 60):02d}"


def arguman(ad: str):
    """--ad deger  biçimindeki argümanı döndürür."""
    if ad in sys.argv:
        i = sys.argv.index(ad)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


def yapay_zekaya_sor(istemci, istem: str) -> dict:
    son_hata = None
    for model in MODELLER:
        try:
            yanit = istemci.models.generate_content(
                model=model,
                contents=istem,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.3,
                ),
            )
            return json.loads(yanit.text)
        except Exception as e:  # model yoksa / kota dolduysa bir sonrakini dene
            print(f"  ({model} çalışmadı: {str(e)[:120]})")
            son_hata = e
    raise SystemExit(f"Hiçbir model yanıt vermedi. Son hata: {son_hata}")


# ---------------------------------------------------------------- odak verisi

def sahte_odak_uret(toplam_saniye: float):
    """Test için: ders boyunca ~80 odak, 100-170. saniyeler arası belirgin düşüş."""
    import random
    random.seed(42)
    with open("odak.csv", "w", newline="", encoding="utf-8") as f:
        y = csv.writer(f)
        y.writerow(["saniye", "odak_skoru"])
        for s in range(int(toplam_saniye) + 1):
            taban = 40 if 100 <= s <= 170 else 80
            y.writerow([s, round(min(100, max(0, taban + random.uniform(-8, 8))))])
    print("Sahte odak.csv üretildi (100-170. saniyeler arasında düşüş var).")


def odak_dosyasi_bul():
    if arguman("--odak"):
        return arguman("--odak")
    if os.path.exists("odak.csv"):
        return "odak.csv"
    adaylar = [d for d in glob.glob(os.path.join("kayitlar", "dikkat_*.csv"))
               if not d.endswith("_olaylar.csv")]
    return max(adaylar, key=os.path.getmtime) if adaylar else None


def _sayi(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def odak_oku(yol):
    """Her satır: {"saniye", "skor"(0-100), "yana", "egik", "kapali"} (oranlar 0-1 ya da None).

    İki biçimi de okur:
      - basit:          saniye,odak_skoru
      - dikkat_olcer:   ders_saniye,sinif_skoru,...,yana_bakan_orani,basi_egik_orani,gozu_kapali_orani,guvenilir
    """
    veri = []
    with open(yol, encoding="utf-8") as f:
        for s in csv.DictReader(f):
            if "ders_saniye" in s:  # dikkat_olcer.py biçimi (5 sn'lik dönemler)
                if s.get("guvenilir") == "0":
                    continue
                skor = _sayi(s.get("sinif_skoru"))
                if skor is None:
                    continue
                veri.append({
                    "saniye": _sayi(s["ders_saniye"]), "skor": skor,
                    "yana": _sayi(s.get("yana_bakan_orani")),
                    "egik": _sayi(s.get("basi_egik_orani")),
                    "kapali": _sayi(s.get("gozu_kapali_orani")),
                })
            else:  # basit biçim
                skor = _sayi(s.get("odak_skoru"))
                if skor is None:
                    continue
                veri.append({"saniye": _sayi(s["saniye"]), "skor": skor,
                             "yana": None, "egik": None, "kapali": None})
    # 0-1 ölçeğinde yazılmışsa 0-100'e çevir
    if veri and max(v["skor"] for v in veri) <= 1:
        for v in veri:
            v["skor"] *= 100
    return veri


def bolum_odagi(odak, bas, bit):
    degerler = [v["skor"] for v in odak if bas <= v["saniye"] < bit]
    return round(sum(degerler) / len(degerler)) if degerler else None


def bolum_nedeni(odak, bas, bit):
    """Bölümdeki en baskın dikkat dağılma nedeni (veri yoksa None)."""
    satirlar = [v for v in odak if bas <= v["saniye"] < bit]
    toplam = {}
    for ad in ("yana", "egik", "kapali"):
        degerler = [v[ad] for v in satirlar if v[ad] is not None]
        if degerler:
            toplam[ad] = sum(degerler) / len(degerler)
    if not toplam:
        return None
    ad, oran = max(toplam.items(), key=lambda kv: kv[1])
    return {"tur": ad, "oran": round(oran, 2), "aciklama": NEDEN_METNI[ad]} if oran >= 0.15 else None


# ---------------------------------------------------------------- ana akış

def main():
    if API_ANAHTARI.startswith("BURAYA"):
        raise SystemExit("Önce notlar.py içindeki API_ANAHTARI satırına Gemini API anahtarını yapıştır.")

    with open("transkript.json", encoding="utf-8") as f:
        transkript = json.load(f)
    toplam_sure = transkript[-1]["bitis"]

    if "--sahte-odak" in sys.argv:
        sahte_odak_uret(toplam_sure)

    metin = "\n".join(f"[{p['baslangic']}] {p['metin']}" for p in transkript)
    istemci = genai.Client(api_key=API_ANAHTARI)

    # 1) Bölümleme + notlar + quiz
    print("Notlar çıkarılıyor...")
    istem = f"""Aşağıda bir dersin otomatik konuşma tanıma ile çıkarılmış, zaman damgalı (saniye) Türkçe transkripti var.
Konuşma tanıma bazı kelimeleri yanlış yazmış olabilir; bağlamdan doğrusunu çıkar.

Görevin, öğrenciler için kısa ve öz ders notları hazırlamak. Yalnızca şu JSON yapısında yanıt ver:
{{
  "ders_basligi": "kısa başlık",
  "ders_ozeti": "2-3 cümlelik genel özet",
  "bolumler": [
    {{
      "baslik": "alt konu başlığı",
      "baslangic_saniye": sayı,
      "bitis_saniye": sayı,
      "notlar": ["kısa madde", "..."],
      "anahtar_kavramlar": [{{"kavram": "...", "tanim": "..."}}],
      "ornekler": ["derste geçen örnek veya formül"]
    }}
  ],
  "quiz": [
    {{"soru": "...", "secenekler": ["A", "B", "C", "D"], "dogru_cevap": 0, "aciklama": "..."}}
  ]
}}

Kurallar:
- Dersi anlamlı alt konulara böl (genelde 3-6 bölüm). Giriş/kapanış cümlelerini ayrı bölüm yapma.
- Bölüm sınırlarını transkriptteki zaman damgalarına göre ver; bölümler arka arkaya gelsin.
- Sayıları ve formülleri rakam/sembolle yaz (dörtte üç -> 3/4).
- Notlar kısa, net ve öğrenci diliyle olsun.
- Quiz 5 soru olsun, dogru_cevap seçeneğin sıra numarası (0-3).
- Konuşma tanıma bazı kelimeleri yanlış yazmış olabilir. Metin kısmen hatalı olsa bile içinde bir ders
  anlatımı anlaşılabiliyorsa notları hazırla ve hatalı kelimeleri bağlamdan düzelt.
- Yalnızca transkriptte GERÇEKTEN anlatılan konuları yaz; transkriptte geçmeyen konu, örnek ya da bilgi ekleme.
- Transkript hiçbir ders anlatımı içermiyorsa (ör. yalnızca mikrofon denemesi: "bir iki üç deneme, ses geliyor mu",
  ya da birbiriyle ilgisiz anlamsız kelimeler) HİÇBİR alana içerik uydurma ve yalnızca şunu döndür:
  {{"ders_basligi": "Ders anlatımı algılanamadı", "ders_ozeti": "", "bolumler": [], "quiz": []}}

TRANSKRİPT:
{metin}
"""
    notlar = yapay_zekaya_sor(istemci, istem)
    notlar["sure_saniye"] = toplam_sure

    # Güvenlik: model "ders yok" dediyse ya da hiç bölüm çıkaramadıysa, hiçbir alanda uydurma içerik kalmasın
    baslik = (notlar.get("ders_basligi") or "").lower()
    if not notlar.get("bolumler") or "algılanamadı" in baslik or "anlaşılamadı" in baslik:
        notlar = {
            "ders_basligi": "Ders anlatımı algılanamadı",
            "ders_ozeti": ("Kayıtta bir ders anlatımı tespit edilemedi (yalnızca deneme konuşması ya da anlaşılmayan ses). "
                           "Ham transkripte bakabilir, mikrofona yakın ve net konuşarak yeniden kaydedebilirsiniz."),
            "bolumler": [], "quiz": [], "sure_saniye": toplam_sure, "ders_algilanmadi": True,
        }
        print("Kayıtta ders anlatımı algılanamadı; not üretilmedi.")

    # 2) Odak verisiyle birleştir
    odak_yol = "odak.csv" if "--sahte-odak" in sys.argv else odak_dosyasi_bul()
    odak = odak_oku(odak_yol) if odak_yol else None
    if odak:
        print(f"Odak verisi: {odak_yol} ({len(odak)} ölçüm). Bölümlerle eşleştiriliyor...")
        notlar["odak_serisi"] = [{"saniye": v["saniye"], "skor": round(v["skor"])} for v in odak]
        notlar["ortalama_odak"] = round(sum(v["skor"] for v in odak) / len(odak))

        for b in notlar["bolumler"]:
            b["ortalama_odak"] = bolum_odagi(odak, b["baslangic_saniye"], b["bitis_saniye"])

        olculenler = [b for b in notlar["bolumler"] if b["ortalama_odak"] is not None]
        if olculenler:
            en_dusuk = min(olculenler, key=lambda b: b["ortalama_odak"])
            if en_dusuk["ortalama_odak"] < ODAK_ESIGI:
                en_dusuk["zorlanilan_konu"] = True
                neden = bolum_nedeni(odak, en_dusuk["baslangic_saniye"], en_dusuk["bitis_saniye"])
                if neden:
                    en_dusuk["dikkat_nedeni"] = neden
                print(f"En çok kopulan konu: {en_dusuk['baslik']} (odak {en_dusuk['ortalama_odak']})")
                print("Bu konu için ek açıklama hazırlanıyor...")

                ilgili = "\n".join(
                    f"[{p['baslangic']}] {p['metin']}" for p in transkript
                    if en_dusuk["baslangic_saniye"] <= p["baslangic"] < en_dusuk["bitis_saniye"]
                )
                ek = yapay_zekaya_sor(istemci, f"""Derste "{en_dusuk['baslik']}" anlatılırken sınıfın dikkati belirgin şekilde düştü;
öğrencilerin bu konuyu tam anlamamış olması muhtemel. Derste anlatılan kısım:
{ilgili}

Bu konuyu daha basit anlatan ek destek hazırla. Yalnızca şu JSON yapısında yanıt ver:
{{
  "basit_anlatim": "konuyu adım adım, çok sade anlatan kısa paragraf",
  "adimlar": ["1. adım", "2. adım", "..."],
  "ek_ornekler": [{{"soru": "...", "cozum": "adım adım çözüm"}}],
  "sik_yapilan_hata": "öğrencilerin bu konuda en sık yaptığı hata ve nasıl kaçınılacağı"
}}
3 ek örnek ver, kolaydan zora sıralı olsun.""")
                en_dusuk["ek_destek"] = ek
                oneri = (f"Sınıfın odağı en çok '{en_dusuk['baslik']}' anlatılırken düştü "
                         f"({dk_sn(en_dusuk['baslangic_saniye'])}-{dk_sn(en_dusuk['bitis_saniye'])}, "
                         f"ortalama {en_dusuk['ortalama_odak']}/100). ")
                if neden:
                    oneri += f"Bu sırada {neden['aciklama']}. "
                oneri += "Bu konuyu bir sonraki derste kısaca tekrar etmek isteyebilirsiniz."
                notlar["ogretmen_onerisi"] = oneri
    else:
        print("Odak verisi bulunamadı; notlar odak olmadan hazırlandı. (Test için: python notlar.py --sahte-odak)")

    # 3) Kaydet
    with open("notlar.json", "w", encoding="utf-8") as f:
        json.dump(notlar, f, ensure_ascii=False, indent=2)
    with open("notlar.md", "w", encoding="utf-8") as f:
        f.write(markdown_yaz(notlar))
    print("\nBitti. Kaydedildi: notlar.json, notlar.md")


def markdown_yaz(n: dict) -> str:
    s = [f"# {n.get('ders_basligi', 'Ders Notları')}\n", f"{n.get('ders_ozeti', '')}\n"]
    if n.get("ortalama_odak") is not None:
        s.append(f"*Ders geneli ortalama odak: {n['ortalama_odak']}/100*\n")
    if n.get("ogretmen_onerisi"):
        s.append(f"> **Öğretmene not:** {n['ogretmen_onerisi']}\n")
    for b in n.get("bolumler", []):
        yildiz = " ⭐ (zorlanılan konu)" if b.get("zorlanilan_konu") else ""
        odak = f" — odak {b['ortalama_odak']}/100" if b.get("ortalama_odak") is not None else ""
        s.append(f"## {b['baslik']}{yildiz}\n*{dk_sn(b['baslangic_saniye'])}-{dk_sn(b['bitis_saniye'])}{odak}*\n")
        s += [f"- {m}" for m in b.get("notlar", [])]
        for k in b.get("anahtar_kavramlar", []):
            s.append(f"- **{k['kavram']}:** {k['tanim']}")
        for o in b.get("ornekler", []):
            s.append(f"- Örnek: {o}")
        ek = b.get("ek_destek")
        if ek:
            s.append(f"\n### Ek destek\n{ek.get('basit_anlatim', '')}\n")
            s += [f"{a}" for a in ek.get("adimlar", [])]
            for i, o in enumerate(ek.get("ek_ornekler", []), 1):
                s.append(f"\n**Ek örnek {i}:** {o['soru']}\n\n*Çözüm:* {o['cozum']}")
            if ek.get("sik_yapilan_hata"):
                s.append(f"\n**Sık yapılan hata:** {ek['sik_yapilan_hata']}")
        s.append("")
    s.append("## Mini Quiz\n")
    for i, q in enumerate(n.get("quiz", []), 1):
        s.append(f"**{i}. {q['soru']}**")
        for j, sec in enumerate(q["secenekler"]):
            s.append(f"   {'ABCD'[j]}) {sec}")
        s.append(f"   *Cevap: {'ABCD'[q['dogru_cevap']]} — {q.get('aciklama', '')}*\n")
    return "\n".join(s)


if __name__ == "__main__":
    main()
