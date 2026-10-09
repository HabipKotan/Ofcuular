# 🎓 Multimodal Kişiselleştirilmiş Ders Asistanı

> **Eğitim Teknolojileri Hackathonu MVP Projesi**  
> Eğitmen anlatımını gerçek zamanlı ders notuna dönüştüren, uçta (Edge AI) çalışan sıfır depolamalı kamera analiziyle öğrencilerin odak kaybettiği anları yakalayıp kişiselleştirilmiş **"Eksik Tamamlama Kartları"** üreten multimodal eğitim platformu.

---

## 🚀 Öne Çıkan Özellikler

### 1. 👨‍🏫 Öğretmen Tarafı (Akıllı Ders Notları)
- **Speech-to-Text & Segmentasyon:** Eğitmenin ses akışı gerçek zamanlı transkribe edilir ve konu başlıklarına ayrılır.
- **Pedagojik Not Çıkarımı:** Dağınık konuşma dili temizlenir; ders özeti, alt bölümler ve tahta çözümleri tek tıkla onaylanıp `.md` olarak indirilebilir.

### 2. 👩‍🎓 Öğrenci Tarafı (Kişiselleştirilmiş Öğrenme & Kesişim Motoru)
- **Zaman Serisi Korelasyon Motoru (`TimeSeriesMatcher`):** Odak skorunun eşik altına düştüğü zaman aralıkları, ses akışındaki konu başlıklarıyla dinamik olarak kesiştirilir.
- **Eksik Tamamlama Kartları:** Sınıfın veya öğrencinin koptuğu her konu için ~2 dakikalık hap özet ve anında geri bildirim veren 2 adet interaktif pekiştirme sorusu sunulur.

### 3. 🛡️ Privacy by Design (KVKK ve Mahremiyet Standartları)
- **Zero-Storage Kamera Akışı:** Görüntüler yalnızca yerel bellekte (RAM) işlenir; diske asla fotoğraf/video kaydedilmez ve sunucuya ham görüntü gönderilmez.
- **Bulanıklaştırma & Anonimleştirme:** Yüz tanıma veya kimlik tespiti yapılmaz; kamera önizlemesinde yüzler varsayılan olarak bulanıklaştırılır (`GaussianBlur`).
- **Uçta Analiz (Edge AI):** 468 yüz landmark'ı üzerinden yalnızca baş açısı (Head Pose), göz açıklığı (EAR) ve esneme tespiti yapılarak 0-100 arasında soyut bir metrik üretilir ve kare anında yok edilir.
- **Geçici Ses Analizi:** Ses metne döküldükten sonra geçici ses verisi bellekten kalıcı olarak silinir.
- **Merkezi Gözetim Veritabanı Yok:** Öğrenci verisi paylaşılan önbellekte (`st.cache_data`) değil, yalnızca tarayıcı oturumunda (`st.session_state`) tutulur.

---

## 📂 Proje Mimarisi

```text
multimodal-lecture-assistant/
│
├── core/
│   ├── config.py              # Eşikler, pencere boyutları ve merkezi ayarlar
│   └── schemas.py             # Pydantic v1 & v2 uyumlu veri modelleri (Data Contracts)
│
├── engine/
│   └── matcher.py             # Zaman serisi yumuşatma, kopma tespiti ve kesişim motoru
│
├── llm/
│   ├── client.py              # Canlı LLM ve jüri önünde çökmeyen akıllı Mock servis
│   └── prompts.py             # Pedagojik özet ve sınav sorusu istem şablonları
│
├── sensing/
│   ├── focus/
│   │   ├── base.py            # Odak kaynağı sözleşmesi (FocusSource)
│   │   ├── simulated.py       # Yorgunluk/göz kırpma artefaktlı sentetik odak üreteci
│   │   ├── edge_mediapipe.py  # Bireysel öğrenci webcam analiz modülü (Head Pose + EAR)
│   │   └── classroom_focus.py # Çoklu yüz / sınıf geneli dikkat ölçüm modülü
│   └── speech/
│       ├── base.py            # Ses kaynağı sözleşmesi (SpeechSource)
│       ├── simulated.py       # 11. Sınıf Türev Dersi sentetik transkript akışı
│       └── whisper_source.py  # Faster-Whisper yerel STT modülü
│
├── ui/
│   ├── components.py          # Plotly interaktif grafikler, ısı haritası ve quiz kartları
│   └── pipeline.py            # Uçtan uca veri pipeline bağlayıcısı
│
├── data/demo/
│   └── turev_dersi.json       # Demo senaryosu (Türevin Limit Tanımı & Çarpım Kuralı)
│
├── app.py                     # Streamlit kullanıcı arayüzü (Öğretmen & Öğrenci Paneli)
├── requirements.txt           # Bağımlılıklar
└── .env.example               # Örnek ortam değişkenleri
```

---

## ⚙️ Kurulum ve Çalıştırma

### 1. Depoyu Klonlayın ve Sanal Ortam Oluşturun
```bash
git clone https://github.com/KULLANICI_ADINIZ/multimodal-lecture-assistant.git
cd multimodal-lecture-assistant

python -m venv .venv
# Windows:
.\.venv\Scripts\activate
# Linux / macOS:
source .venv/bin/activate
```

### 2. Bağımlılıkları Yükleyin
```bash
python -m pip install -r requirements.txt
```

*(Canlı kamera ve mikrofon modüllerini test etmek isterseniz: `pip install opencv-python mediapipe faster-whisper`)*

### 3. Uygulamayı Başlatın
```bash
python -m streamlit run app.py
```
Tarayıcınızda `http://localhost:8501` adresine giderek demoyu inceleyebilirsiniz.

---

## 🏆 Jüri Demosu Senaryoları
1. **Garantili Çevrimdışı Simülasyon:** Donanım veya internet bağımlılığı olmadan 11. Sınıf Türev Dersi senaryosunda eşik kaydırıcı ile canlı olarak 318-383 sn (Limit Tanımı) ve 613-647 sn (Çarpım Kuralı) aralıklarının yakalanıp soru kartlarına dönüştürülmesini gösterin.
2. **Canlı Sınıf / Jüri Modu:** `classroom_focus.py` modülüyle kamerayı açıp jüri masasını eşzamanlı anonim olarak puanlayın ve yüzlerin otomatik bulanıklaştırıldığını gösterin.

---

## 🎙️ Gerçek Ders Modu (ses + görüntü + Gemini entegrasyonu)

Arayüz artık hazır demo verisinin yanında **gerçek bir dersin** çıktılarını da gösterebilir.
Öğretmen arayüzünün kenar çubuğundaki **"Gösterilen ders"** seçiminden **"Son ders kaydı"** seçilir; demo modu yedek olarak durur.

### 1. Gemini anahtarı
`.env.example` dosyasını `.env` adıyla kopyalayın ve anahtarı yazın:
```
LLM_PROVIDER=gemini
GEMINI_API_KEY=buraya_anahtar
```
Kurulum: `python -m pip install -r requirements.txt` (google-genai eklendi).
Anahtar yoksa sistem eskisi gibi mock moda düşer, demo çökmez.

### 2. Ders dosyalarını proje klasörüne koyun (app.py'nin yanına)
| Dosya | Üreten |
|---|---|
| `transkript.json` | `transkript.py` (Whisper) |
| `notlar.json` | `notlar.py` (Gemini; notlar + odak serisi + öğretmene öneri) |
| `kayitlar/dikkat_*.csv` | `dikkat_olcer.py` (görüntü işleme) — notlar.json'da odak serisi yoksa buradan okunur |

Başka bir klasör kullanmak için `.env` içine `GERCEK_VERI_KLASORU=...` yazın.

### 3. Çalıştırın
```
python -m streamlit run app.py
```
Yeni bir ders işlendiğinde kenar çubuğundaki **"🔄 Son kaydı yeniden yükle"** butonuna basın.

### Değişen / eklenen dosyalar
- `ui/gercek_veri.py` (yeni): gerçek ders dosyalarını Lecture / LectureNotes / FocusSample yapılarına çevirir
- `ui/pipeline.py`: veri kaynağı (demo / gerçek) desteği
- `app.py`: veri kaynağı seçimi, yeniden yükleme, öğretmene öneri kutusu
- `llm/client.py`, `core/config.py`: Gemini desteği (model yoksa yedek modele geçer)
- `llm/prompts.py`: üçlü tırnak yazım hatası düzeltildi (canlı LLM modunda uygulamayı çökertiyordu)

---

## 👥 İki ayrı arayüz: öğretmen ve öğrenci

Uygulama açılınca rol sorulur; her rol yalnızca kendi ekranını görür (adres çubuğunda `?rol=ogretmen` / `?rol=ogrenci`).

- **Öğretmen:** dersi başlatır/bitirir, ders sonu özetini (öğrenci sayısı, sınıf odağı, ses bilgisi) görür,
  notları düzenler ve **"Onayla ve öğrencilerle paylaş"** der.
- **Öğrenci:** yalnızca öğretmenin paylaştığı dersi görür: ders notları, kendi odak grafiği ve eksik tamamlama
  kartları, ders sonu mini quiz. Öğretmen yeni bir ders paylaşınca sayfa kendiliğinden güncellenir.
- Onay `paylasim.json` dosyasında tutulur; öğrenci başka bir tarayıcı ya da cihazdan açsa da aynı dersi görür.
- Öğretmen arayüzüne şifre koymak için `.env` içine `OGRETMEN_SIFRESI=...` yazın (boşsa şifre sorulmaz).
- Öğrencilerin kendi cihazlarından bağlanabilmesi için `.streamlit/config.toml` içindeki `address = "localhost"`
  satırını `address = "0.0.0.0"` yapın; öğrenciler `http://<öğretmen bilgisayarının IP adresi>:8501/?rol=ogrenci`
  adresini açar. (Varsayılan ayar yalnızca bu bilgisayardan erişime izin verir.)

## 🎬 Dersi Başlat / Bitir (canlı kayıt)

Öğretmen arayüzünün en üstündeki **"Ders kaydı"** kutusu:

1. **Ders adı zorunludur** (ör. `Matematik 9-A: kesirler, pay, payda`). Boşsa kayıt başlamaz. Ad, notların başlığı
   olur; içine yazılan konu ve terimler sesin metne daha doğru çevrilmesini sağlar.
2. **🔴 Dersi Başlat**'a basınca iki soru sorulur (en az biri açık olmalı):
   - **Ses dinlenip metne çevrilsin mi?** Kapalıysa mikrofon hiç açılmaz, not üretilmez.
   - **Sınıfın odak ortalaması izlensin mi?** Kapalıysa kamera hiç açılmaz.
3. **⏹ Dersi Bitir** → kayıt durur ve seçilenler otomatik işlenir. Ham ses dosyası metne çevrilince silinir.
4. Bitince **Ders özeti** tablosu çıkar: ders adı, süre, **derse katılan öğrenci sayısı**, sınıf odak ortalaması,
   odağın düştüğü bölümler ve ses bilgisi.

**Öğrenci sayısı** kameranın ders boyunca aynı anda gördüğü yüz sayısından hesaplanır (kimlik tespiti yoktur, yalnızca
sayılır). Kameraya yüzü dönük olmayan ya da kadraj dışında kalan öğrenciler sayılmaz. Büyük sınıflar için `.env`
içinde `KAMERA_MAX_YUZ` değerini artırın (varsayılan 30).

Elle çalıştırma: `python ders_kaydi.py --konu "Matematik: kesirler" [--ses-yok | --odak-yok]`
(kamera penceresinde `q` ile biter; kamera kapalıysa paneldeki "Dersi Bitir" ile).

## 🎙️ Öğretmen sesi ve metne çevirme

**Yalnızca öğretmenin sesi metne çevrilir** (`ses_hatti/konusmaci.py`):

- Kayıttaki her konuşma parçasından bir "ses izi" çıkarılır, benzer izler gruplanır; **ders boyunca toplam konuşma
  süresi en uzun olan kişi öğretmen sayılır**. Öğretmene benzemeyen bölümler metne çevrilmeden **önce** susturulur.
- Her şey bu bilgisayarda çalışır; ses izleri diske yazılmaz, kimlik eşleştirmesi yapılmaz.
- Emin olunamayan yerlerde ses korunur (öğretmenin sözünü silmektense bir öğrenci cümlesinin kalması yeğlenir).
  Öğretmenden hemen sonra söylenen çok kısa sözler ("evet", "tamam") bu yüzden metne geçebilir.
- Sınırlar: öğretmen dersin çoğunda konuşmuyorsa (uzun tartışma, grup çalışması) baskın ses bulunamaz ve ayrım
  yapılmaz; 8 saniyeden az konuşma olan kayıtlarda da yapılmaz. Sonuç ders özetindeki "Ses" satırında yazar.
- Kapatmak için `.env` içine `OGRETMEN_SESI_AYRIMI=0` yazın.
- Model: `ses_hatti/modeller/konusmaci.onnx` (WeSpeaker ResNet34, ~26 MB). Dosya yoksa ilk kullanımda indirilir.

**Metne çevirme iyileştirmeleri** (`ses_hatti/transkript.py`, `ses_hatti/notlar.py`):

- Ders adındaki konu ve terimler Whisper'a kaydın **her bölümünde** ipucu olarak verilir (önceden yalnızca ilk 30 sn).
- Kısık kayıtlar yükseltilir; kelime başı/sonu kesilmesin diye konuşma aralıkları biraz geniş tutulur.
- Whisper'ın sessizlikte uydurduğu kalıplar ("Altyazı M.K.", "İzlediğiniz için teşekkürler" vb.) ve art arda
  tekrarlar ayıklanır.
- Notlardan önce transkript Gemini'ye **yalnızca yanlış duyulan kelimeleri düzeltmesi** için verilir
  (ör. "bölük" → "bölü"). Satırı baştan yazan ya da içerik ekleyen düzeltmeler kabul edilmez; asıl metin
  `transkript.json` içinde `ham` alanında saklanır. Kapatmak için `TRANSKRIPT_DUZELT=0`.
- En büyük kazanç model seçimindedir: `.env` içinde `WHISPER_MODEL=medium` (yavaş, daha doğru) ya da
  `large-v3-turbo` deneyebilirsiniz (hızını kendi bilgisayarınızda ölçün; bu projede denenmedi);
  `small` hızlı ama daha çok hata yapar.

Dosyalar: `ders_kaydi.py`, `ui/ders_kontrol.py`, `ses_hatti/transkript.py`, `ses_hatti/konusmaci.py`, `ses_hatti/notlar.py`.
Kayıt sırasında sorun çıkarsa panel hatanın nedenini ve kayıt günlüğünün son satırlarını gösterir.

> **Tahta sekmesi kaldırıldı.** `ui/tahta/` ve `ui/tahta_bileseni.py` dosyaları ile `tahtalar/` arşivi klasörde
> duruyor ama arayüzde kullanılmıyor.

## ▶️ Tek tıkla başlatma

Windows'ta proje klasöründeki **`baslat.bat`** dosyasına çift tıklayın (macOS / Linux: `./baslat.sh`).
İlk çalıştırmada sanal ortamı kurar ve paketleri yükler; sonraki açılışlarda doğrudan uygulamayı başlatır
ve tarayıcıda `http://localhost:8501` adresini açar. Python 3.11 ya da 3.12 önerilir.

## 🧰 Sorun giderme

- **Kayıt hata verdi / pencere kapandı:** Öğretmen Görünümü'ndeki "Ders kaydı" kutusu hatanın asıl nedenini ve
  **kayıt günlüğünün son satırlarını** gösterir. Günlüğün tamamı proje klasöründeki `kayit_gunlugu.txt` dosyasındadır.
- **"Hiçbir model yanıt vermedi" (503 / yoğunluk):** Sistem her modeli kısa aralıklarla birkaç kez dener ve sırayla
  yedek modellere geçer. Yine olmazsa ders kaydı ve metni kaybolmaz: "🔁 Notları yeniden üret" butonuna basın.
  Belirli bir model için `.env` içine `LLM_MODEL=...` yazın.
- **"Ders anlatımı algılanamadı":** Kayıt çok kısaysa ya da ses anlaşılmadıysa çıkar. Ham transkript sayfanın altındadır.
  Mikrofonu `python mikrofon_testi.py` ile deneyin; Bluetooth kulaklık mikrofonları genelde kısık ve boğuk kaydeder,
  mümkünse dizüstünün kendi mikrofonunu ya da kablolu bir mikrofonu seçin (`.env` içinde `MIKROFON=<numara>`).
- **Ses metne çevirme çok yavaş:** `.env` içinde `WHISPER_MODEL=medium` işlemcide ders süresi kadar sürebilir;
  demo için `small` çok daha hızlıdır.
- **Paket hatası (cv2 / mediapipe / sounddevice bulunamadı):** `baslat.bat` ile açın ya da
  `python -m pip install -r requirements.txt` çalıştırın.
