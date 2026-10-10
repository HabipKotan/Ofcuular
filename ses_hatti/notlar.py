"""
Transkripti (transkript.json) yapay zekâ ile ders notlarına çevirir.
Odak verisi varsa, odağın en çok düştüğü konuyu bulup o bölümü güçlendirir.

Kullanım:
    python notlar.py                                  (odak verisini kendisi bulur, aşağıya bak)
    python notlar.py --odak kayitlar/dikkat_xxx.csv   (belirli bir odak dosyası)
    python notlar.py --odak-yok                       (bu derste odak izlenmedi: eski ölçüm dosyalarına bakma)
    python notlar.py --ses-yok --konu "Matematik"     (bu derste ses kaydedilmedi: yalnızca odak özeti yaz)
    python notlar.py --konu "Matematik: kesirler"     (ders adı: başlık ve transkript düzeltmesi için)
    python notlar.py --sahte-odak                     (test için sahte odak verisi üretir)

Odak verisini şu sırayla arar:
    1) --odak ile verilen dosya
    2) klasördeki odak.csv            (saniye,odak_skoru  biçimi)
    3) kayitlar/ klasöründeki en yeni dikkat_*.csv  (dikkat_olcer.py çıktısı)

Kurulum (bir kez):
    pip install google-genai

API anahtarı: aistudio.google.com -> "Get API key" -> anahtarı proje klasöründeki .env dosyasına yazın:
    GEMINI_API_KEY=...

Çıktı:
    notlar.json  ->  arayüzün kullanacağı TEK dosya (notlar + quiz + odak serisi)
    notlar.md    ->  okunabilir hali (kontrol için)

Tüm odak skorları 0-100 ölçeğindedir.
"""

import csv
from pathlib import Path
import difflib
import glob
import json
import math
import os
import re
import sys
import time

from google import genai
from google.genai import types

try:  # arayüz projesindeki .env dosyasından GEMINI_API_KEY'i al
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"), override=True)
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from llm import gemini_havuzu  # noqa: E402  (birden çok anahtar + yedek modeller)

API_ANAHTARI = (os.environ.get("GEMINI_API_KEY") or "").strip()

# Sırayla denenir; biri çalışmazsa (model yok / kota / yoğunluk) sonrakine geçilir.
# .env içindeki LLM_MODEL varsa en başa alınır.
MODELLER = list(dict.fromkeys(
    m for m in [os.environ.get("LLM_MODEL", "").strip(), "gemini-3.5-flash", "gemini-3.8-flash",
                "gemini-3.5-flash-lite", "gemini-2.5-flash"] if m))
GECICI_HATA = ("503", "429", "500", "unavailable", "overloaded", "high demand", "resource_exhausted",
               "deadline", "timeout", "timed out", "connection")

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


def json_ayikla(metin) -> dict:
    """Model yanıtından JSON nesnesini çıkarır (```json ... ``` çiti ya da baştaki/sondaki yazı olsa bile)."""
    metin = (metin or "").strip()
    try:
        veri = json.loads(metin)
    except ValueError:
        eslesme = re.search(r"\{.*\}", metin, re.DOTALL)
        if not eslesme:
            raise ValueError("Model yanıtında JSON bulunamadı")
        veri = json.loads(eslesme.group(0))
    if not isinstance(veri, dict):
        raise ValueError("Model yanıtı bir JSON nesnesi değil")
    return veri


def yapay_zekaya_sor(istemci, istem: str) -> dict:
    """Anahtar + model havuzu üzerinden (llm/gemini_havuzu.py): kota dolan anahtar/model atlanır, yedeğe geçilir."""
    try:
        metin, _ = gemini_havuzu.uret(istem, log=print)
    except RuntimeError as e:
        raise SystemExit(str(e))
    return json_ayikla(metin)

def _f(v, varsayilan=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return varsayilan


def _liste(v) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def notlari_duzelt(notlar: dict, toplam_sure: float) -> dict:
    """Modelin eksik/yanlış tipte döndürebildiği alanları güvenli hale getirir (sonraki adımlar çökmesin)."""
    bolumler = []
    for b in _liste(notlar.get("bolumler")):
        if not isinstance(b, dict):
            continue
        b["baslik"] = str(b.get("baslik") or f"Bölüm {len(bolumler) + 1}")
        b["baslangic_saniye"] = _f(b.get("baslangic_saniye"))
        b["bitis_saniye"] = _f(b.get("bitis_saniye"))
        b["notlar"] = [str(m) for m in _liste(b.get("notlar")) if m]
        b["ornekler"] = [str(o) for o in _liste(b.get("ornekler")) if o]
        b["anahtar_kavramlar"] = [
            {"kavram": str(k.get("kavram") or ""), "tanim": str(k.get("tanim") or "")}
            for k in _liste(b.get("anahtar_kavramlar")) if isinstance(k, dict) and k.get("kavram")]
        bolumler.append(b)
    # Zamanlar: eksik başlangıç = önceki bölümün bitişi; eksik/ters bitiş = sonraki başlangıç ya da ders sonu
    for i, b in enumerate(bolumler):
        if b["baslangic_saniye"] is None:
            b["baslangic_saniye"] = bolumler[i - 1]["bitis_saniye"] if i else 0.0
        sonraki = bolumler[i + 1]["baslangic_saniye"] if i + 1 < len(bolumler) else None
        if b["bitis_saniye"] is None or b["bitis_saniye"] <= b["baslangic_saniye"]:
            b["bitis_saniye"] = sonraki if sonraki and sonraki > b["baslangic_saniye"] else max(toplam_sure, b["baslangic_saniye"] + 1)
    notlar["bolumler"] = bolumler

    quiz = []
    for q in _liste(notlar.get("quiz")):
        if not isinstance(q, dict) or not q.get("soru"):
            continue
        secenekler = [str(x) for x in _liste(q.get("secenekler"))]
        dogru = _f(q.get("dogru_cevap"))
        if len(secenekler) < 2 or dogru is None or not 0 <= int(dogru) < len(secenekler):
            continue
        quiz.append({"soru": str(q["soru"]), "secenekler": secenekler, "dogru_cevap": int(dogru),
                     "aciklama": str(q.get("aciklama") or "")})
    notlar["quiz"] = quiz
    notlar["ders_basligi"] = str(notlar.get("ders_basligi") or "Ders Notları")
    notlar["ders_ozeti"] = str(notlar.get("ders_ozeti") or "")
    return notlar


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
    if "--odak-yok" in sys.argv:  # bu derste odak izlenmedi: önceki derslerin ölçümleri karışmasın
        return None
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


def ogrenci_sayisi_bul(yol):
    """Kameranın derste gördüğü kişi sayısı: 5 sn'lik dönemlerdeki ortalama yüz sayısının üst ucu
    (%95'lik değer; tek tük yanlış algılamalar sayıyı şişirmesin). Ölçüm yoksa None."""
    yuzler = []
    try:
        with open(yol, encoding="utf-8") as f:
            for s in csv.DictReader(f):
                if s.get("guvenilir") == "0":
                    continue
                v = _sayi(s.get("ortalama_yuz"))
                if v is not None and v > 0:
                    yuzler.append(v)
    except Exception:
        return None
    if not yuzler:
        return None
    yuzler.sort()
    return max(1, int(round(yuzler[min(len(yuzler) - 1, math.ceil(0.95 * len(yuzler)) - 1)])))


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
                    "saniye": _sayi(s.get("ders_saniye")), "skor": skor,
                    "yana": _sayi(s.get("yana_bakan_orani")),
                    "egik": _sayi(s.get("basi_egik_orani")),
                    "kapali": _sayi(s.get("gozu_kapali_orani")),
                })
            else:  # basit biçim
                skor = _sayi(s.get("odak_skoru"))
                if skor is None:
                    continue
                veri.append({"saniye": _sayi(s.get("saniye")), "skor": skor,
                             "yana": None, "egik": None, "kapali": None})
    veri = [v for v in veri if v["saniye"] is not None]  # zamanı okunamayan satırlar atlanır
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


# ---------------------------------------------------------------- transkript düzeltme

def transkripti_duzelt(istemci, transkript: list, konu: str) -> int:
    """Konuşma tanımanın yanlış yazdığı kelimeleri (terimler, sayılar, "bölük" -> "bölü" gibi) yapay zekâyla düzeltir.

    Güvenlik: satır sayısı ve zamanlar değişmez; bir satır ancak aslına yeterince benziyorsa değiştirilir
    (model cümleyi baştan yazarsa ya da içerik eklerse o düzeltme yok sayılır). Aslı "ham" alanında saklanır.
    Dönüş: düzeltilen satır sayısı.
    """
    degisen = 0
    for bas in range(0, len(transkript), 120):  # uzun derslerde parça parça
        dilim = transkript[bas:bas + 120]
        satirlar = "\n".join(f"{i}: {p['metin']}" for i, p in enumerate(dilim))
        istem = f"""Aşağıda bir dersin otomatik konuşma tanıma (Whisper) çıktısı satır satır verilmiştir ("numara: metin").
{f"Dersin konusu: {konu}." if konu else ""}
Konuşma tanıma bazı kelimeleri yanlış duymuş olabilir (ör. "bölük" yerine "bölü", yanlış yazılmış terimler, özel adlar,
sayılar). Görevin YALNIZCA bu tanıma hatalarını düzeltmek.

Kurallar:
- Cümlenin anlamını, sırasını ve üslubunu değiştirme; cümleyi yeniden yazma, özetleme, yeni bilgi ekleme.
- Emin olmadığın satıra dokunma. Öğretmenin gerçekten söylediği (hatalı olsa bile) bilgiyi değiştirme.
- Sayıları ve işlemleri konuşulduğu gibi bırak; yalnızca yanlış duyulmuş kelimeyi düzelt.
- Yalnızca DEĞİŞTİRDİĞİN satırları döndür. Hiçbir şey değişmiyorsa boş liste döndür.

Yalnızca şu JSON yapısında yanıt ver:
{{"duzeltmeler": [{{"no": satır numarası, "metin": "düzeltilmiş satır"}}]}}

SATIRLAR:
{satirlar}
"""
        yanit = yapay_zekaya_sor(istemci, istem)
        for d in _liste(yanit.get("duzeltmeler")):
            if not isinstance(d, dict):
                continue
            no, yeni = _f(d.get("no")), str(d.get("metin") or "").strip()
            if no is None or not 0 <= int(no) < len(dilim) or not yeni:
                continue
            p = dilim[int(no)]
            eski = p["metin"]
            benzerlik = difflib.SequenceMatcher(None, eski.lower(), yeni.lower()).ratio()
            if yeni == eski or benzerlik < 0.6 or not 0.6 <= len(yeni) / max(1, len(eski)) <= 1.6:
                continue  # aynı ya da aslından fazla uzaklaşmış: kabul etme
            p.setdefault("ham", eski)
            p["metin"] = yeni
            degisen += 1
    return degisen


def transkripti_kaydet(transkript: list) -> None:
    with open("transkript.json", "w", encoding="utf-8") as f:
        json.dump(transkript, f, ensure_ascii=False, indent=2)
    with open("transkript.txt", "w", encoding="utf-8") as f:
        for p in transkript:
            f.write(f"[{dk_sn(_f(p.get('baslangic'), 0.0))}] {p['metin']}\n")


def ses_bilgisi() -> dict:
    """transkript.py'nin bıraktığı özet (model, öğretmen sesi ayrımı); yoksa boş."""
    try:
        with open("transkript_bilgi.json", encoding="utf-8") as f:
            b = json.load(f)
        return b if isinstance(b, dict) else {}
    except Exception:
        return {}


def odagi_ekle(notlar: dict, odak_yol, odak) -> None:
    """Odak serisi, ortalama ve öğrenci sayısını notlara yazar."""
    notlar["odak_izlendi"] = bool(odak)
    if not odak:
        return
    notlar["odak_serisi"] = [{"saniye": v["saniye"], "skor": round(v["skor"])} for v in odak]
    notlar["odak_kaydi"] = Path(odak_yol).stem  # rızalı kişisel odak ölçümleri bu ada bağlıdır
    notlar["ortalama_odak"] = round(sum(v["skor"] for v in odak) / len(odak))
    sayi = ogrenci_sayisi_bul(odak_yol)
    if sayi:
        notlar["ogrenci_sayisi"] = sayi


def yalnizca_odak(konu: str) -> None:
    """Ses kaydedilmeyen ders: transkript ve not yok; yalnızca sınıf odağı özeti yazılır (yapay zekâ çağrısı yok)."""
    odak_yol = odak_dosyasi_bul()
    odak = odak_oku(odak_yol) if odak_yol else None
    if not odak:
        raise SystemExit("Bu derste ne ses ne de odak verisi var; kaydedilecek bir şey bulunamadı.")
    sure = max(v["saniye"] for v in odak)
    notlar = {
        "ders_basligi": konu or "Ders",
        "ders_ozeti": "Bu derste ses kaydı alınmadı; yalnızca sınıfın odak ortalaması izlendi.",
        "bolumler": [], "quiz": [], "sure_saniye": sure, "ses_kaydedilmedi": True, "konu": konu,
    }
    odagi_ekle(notlar, odak_yol, odak)
    transkripti_kaydet([])
    with open("notlar.json", "w", encoding="utf-8") as f:
        json.dump(notlar, f, ensure_ascii=False, indent=2)
    with open("notlar.md", "w", encoding="utf-8") as f:
        f.write(markdown_yaz(notlar))
    print(f"Odak verisi: {odak_yol} ({len(odak)} ölçüm). Ses kaydı yok; yalnızca odak özeti kaydedildi.")
    print("\nBitti. Kaydedildi: notlar.json, notlar.md")


# ---------------------------------------------------------------- ana akış

def main():
    konu = (arguman("--konu") or "").strip()
    if "--ses-yok" in sys.argv:
        return yalnizca_odak(konu)
    if not API_ANAHTARI or API_ANAHTARI.upper().startswith("BURAYA"):
        raise SystemExit("Gemini API anahtarı bulunamadı. Proje klasöründeki .env dosyasına GEMINI_API_KEY=... satırını yazın.")

    with open("transkript.json", encoding="utf-8") as f:
        transkript = json.load(f)
    transkript = [p for p in transkript if isinstance(p, dict) and str(p.get("metin") or "").strip()]
    if not transkript:
        raise SystemExit("Transkript boş: kayıtta konuşma algılanamadı. Mikrofonu kontrol edip dersi yeniden kaydedin.")
    toplam_sure = _f(transkript[-1].get("bitis"), 0.0) or _f(transkript[-1].get("baslangic"), 0.0) + 1

    if "--sahte-odak" in sys.argv:
        sahte_odak_uret(toplam_sure)

    istemci = genai.Client(api_key=API_ANAHTARI)

    # 0) Konuşma tanıma hatalarını düzelt (başarısız olursa ham metinle devam edilir)
    duzeltilen = 0
    if os.environ.get("TRANSKRIPT_DUZELT", "1") != "0":
        print("Transkript gözden geçiriliyor (yanlış duyulan kelimeler)...")
        try:
            duzeltilen = transkripti_duzelt(istemci, transkript, konu)
            if duzeltilen:
                transkripti_kaydet(transkript)
            print(f"  {duzeltilen} satır düzeltildi.")
        except (Exception, SystemExit) as e:
            print(f"  Transkript düzeltilemedi, ham metinle devam ediliyor: {str(e)[:150]}")

    metin = "\n".join(f"[{p.get('baslangic', 0)}] {p['metin']}" for p in transkript)

    # 1) Bölümleme + notlar + quiz
    print("Notlar çıkarılıyor...")
    istem = f"""Aşağıda bir dersin otomatik konuşma tanıma ile çıkarılmış, zaman damgalı (saniye) Türkçe transkripti var.
{f"Öğretmenin derse verdiği ad: {konu}." if konu else ""}
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
    notlar = notlari_duzelt(yapay_zekaya_sor(istemci, istem), toplam_sure)
    notlar["sure_saniye"] = toplam_sure
    notlar["konu"] = konu
    ses = ses_bilgisi()
    notlar["ses"] = {"model": ses.get("model"), "duzeltilen_satir": duzeltilen,
                     "ayiklanan_parca": ses.get("ayiklanan_parca", 0),
                     "ogretmen_ayrimi": {k: v for k, v in (ses.get("ogretmen_ayrimi") or {}).items()
                                         if k != "atlanan_araliklar"}}

    # Güvenlik: model "ders yok" dediyse ya da hiç bölüm çıkaramadıysa, hiçbir alanda uydurma içerik kalmasın
    baslik = (notlar.get("ders_basligi") or "").lower()
    if not notlar.get("bolumler") or "algılanamadı" in baslik or "anlaşılamadı" in baslik:
        notlar = {
            "ders_basligi": "Ders anlatımı algılanamadı",
            "ders_ozeti": ("Kayıtta bir ders anlatımı tespit edilemedi (yalnızca deneme konuşması ya da anlaşılmayan ses). "
                           "Ham transkripte bakabilir, mikrofona yakın ve net konuşarak yeniden kaydedebilirsiniz."),
            "bolumler": [], "quiz": [], "sure_saniye": toplam_sure, "ders_algilanmadi": True,
            "konu": konu, "ses": notlar.get("ses"),
        }
        print("Kayıtta ders anlatımı algılanamadı; not üretilmedi.")

    # 2) Odak verisiyle birleştir
    odak_yol = "odak.csv" if "--sahte-odak" in sys.argv else odak_dosyasi_bul()
    odak = odak_oku(odak_yol) if odak_yol else None
    odagi_ekle(notlar, odak_yol, odak)
    if odak:
        print(f"Odak verisi: {odak_yol} ({len(odak)} ölçüm). Bölümlerle eşleştiriliyor...")

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
                    f"[{p.get('baslangic', 0)}] {p['metin']}" for p in transkript
                    if en_dusuk["baslangic_saniye"] <= (_f(p.get("baslangic"), 0.0)) < en_dusuk["bitis_saniye"]
                )
                try:
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
                except (Exception, SystemExit) as e:  # ek destek alınamazsa asıl notlar kaybolmasın
                    print(f"  Ek destek hazırlanamadı, notlar onsuz kaydediliyor: {str(e)[:150]}")
                    ek = None
                if isinstance(ek, dict):
                    ek["adimlar"] = [str(a) for a in _liste(ek.get("adimlar")) if a]
                    ek["ek_ornekler"] = [{"soru": str(o.get("soru") or ""), "cozum": str(o.get("cozum") or "")}
                                         for o in _liste(ek.get("ek_ornekler")) if isinstance(o, dict)]
                    en_dusuk["ek_destek"] = ek
                oneri = (f"Sınıfın odağı en çok '{en_dusuk['baslik']}' anlatılırken düştü "
                         f"({dk_sn(en_dusuk['baslangic_saniye'])}-{dk_sn(en_dusuk['bitis_saniye'])}, "
                         f"ortalama {en_dusuk['ortalama_odak']}/100). ")
                if neden:
                    oneri += f"Bu sırada {neden['aciklama']}. "
                oneri += "Bu konuyu bir sonraki derste kısaca tekrar etmek isteyebilirsiniz."
                notlar["ogretmen_onerisi"] = oneri
    else:
        print("Odak verisi yok; notlar odak olmadan hazırlandı.")

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
    if n.get("ogrenci_sayisi"):
        s.append(f"*Derse katılan öğrenci sayısı (kameranın gördüğü): {n['ogrenci_sayisi']}*\n")
    if n.get("ogretmen_onerisi"):
        s.append(f"> **Öğretmene not:** {n['ogretmen_onerisi']}\n")
    for b in n.get("bolumler", []):
        yildiz = " ⭐ (zorlanılan konu)" if b.get("zorlanilan_konu") else ""
        odak = f" — odak {b['ortalama_odak']}/100" if b.get("ortalama_odak") is not None else ""
        s.append(f"## {b['baslik']}{yildiz}\n*{dk_sn(b['baslangic_saniye'])}-{dk_sn(b['bitis_saniye'])}{odak}*\n")
        s += [f"- {m}" for m in b.get("notlar", [])]
        for k in b.get("anahtar_kavramlar", []):
            s.append(f"- **{k.get('kavram', '')}:** {k.get('tanim', '')}")
        for o in b.get("ornekler", []):
            s.append(f"- Örnek: {o}")
        ek = b.get("ek_destek")
        if ek:
            s.append(f"\n### Ek destek\n{ek.get('basit_anlatim', '')}\n")
            s += [f"{a}" for a in ek.get("adimlar", [])]
            for i, o in enumerate(ek.get("ek_ornekler", []), 1):
                s.append(f"\n**Ek örnek {i}:** {o.get('soru', '')}\n\n*Çözüm:* {o.get('cozum', '')}")
            if ek.get("sik_yapilan_hata"):
                s.append(f"\n**Sık yapılan hata:** {ek['sik_yapilan_hata']}")
        s.append("")
    if n.get("quiz"):
        s.append("## Mini Quiz\n")
    for i, q in enumerate(n.get("quiz", []), 1):
        s.append(f"**{i}. {q['soru']}**")
        for j, sec in enumerate(q["secenekler"]):
            s.append(f"   {'ABCDEFGH'[j % 8]}) {sec}")
        s.append(f"   *Cevap: {'ABCDEFGH'[q['dogru_cevap'] % 8]} — {q.get('aciklama', '')}*\n")
    return "\n".join(s)


if __name__ == "__main__":
    main()
