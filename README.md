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
Kenar çubuğundaki **"Veri kaynağı"** seçiminden **"Gerçek ders (son kayıt)"** seçilir; demo modu yedek olarak durur.

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
