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
- **Bulanıklaştırma & Anonimleştirme:** Varsayılan olarak yüz tanıma yapılmaz; yalnızca açık rıza veren ve öğretmenin kaydettiği öğrenci tanınır (bkz. "Rızalı kişisel odak raporu"). Kamera önizlemesinde yüzler varsayılan olarak bulanıklaştırılır (`GaussianBlur`).
- **Uçta Analiz (Edge AI):** MediaPipe Face Landmarker'ın 478 yüz noktası ve yüz ifadesi katsayıları (`eyeBlink`, `jawOpen`) üzerinden yalnızca baş açısı (Head Pose), göz kapalılığı ve esneme ölçülerek 0-100 arasında soyut bir metrik üretilir ve kare anında yok edilir.
- **Geçici Ses Analizi:** Ses metne döküldükten sonra geçici ses verisi bellekten kalıcı olarak silinir.
- **Merkezi Gözetim Veritabanı Yok:** Öğrenci verisi paylaşılan önbellekte (`st.cache_data`) değil, tarayıcı oturumunda (`st.session_state`) tutulur. Rızalı öğrencilerin yüz izleri yalnızca bu bilgisayardaki yerel, şifreli veritabanında (`ogrenciler.db`) durur; sunucuya gönderilmez.

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

**Arka sıralar (uzak yüz modu, varsayılan):** MediaPipe'ın kendi yüz bulucusu kareyi 128 piksele küçültür ve yalnızca
kare genişliğinin ~%12'sinden büyük yüzleri bulur; tipik bir webcam'de bu ~1.3 metre demektir. Bu yüzden önce **YuNet**
tüm kareyi kendi çözünürlüğünde tarar, bulduğu her yüz kırpılıp büyütülerek ayrıca ölçülür. Kırpıntılar yalnızca
bellekte yaşar. Kamera 1280×720 istenir (OpenCV varsayılanı 640×480). Çok küçük yüzlerde (30 pikselin altı) göz ve
ağız okunamadığı için yalnızca baş yönü sayılır. Eski hızlı yönteme dönmek için `KAMERA_ALGILAMA=yakin`.

**Esneme dikkat kaybı sayılır:** ağız açıklığı (MediaPipe `jawOpen`) 0.5'i geçince öğrencinin skoru kademeli düşer;
tam esnemede tahtaya baksa bile 35'e iner. Konuşurken ağız açıklığı genelde 0.4'ün altında kaldığı için konuşan
öğrenci ceza almaz. Uzun düşüşlerde olay nedeni "esneme / uyku hali" olarak yazılır.

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

## 🖊️ Ders tahtası: tam ekran, PDF ve sunumlar

**Dersi Başlat** ile kayıt başlayınca tahta **tam ekran** açılır (Streamlit'in başlığı ve yan paneli gizlenir).
Tahtaya ilk dokunuşta tarayıcı da gerçek tam ekrana geçer (tarayıcılar bunu bir dokunuş/tıklama olmadan izin vermez).

- Üst çubuk: **Belge ekle**, **Küçült / Tam ekran** ve iki adımlı onaylı **Dersi bitir**. Tam ekranken paneldeki
  kamera / mikrofon uyarıları tahtanın üst çubuğunda kırmızı bir şerit olarak görünür.
- **Sürükle-bırak:** PDF, resim (PNG, JPG, GIF, WebP, SVG), PowerPoint (`.pptx .ppt .ppsx .pps .potx .odp .key`) ve
  Word (`.docx .doc .odt .rtf`) dosyaları tahtaya bırakılabilir. Sayfalar bırakılan yere, mevcut sayfalarla
  çakışmayacak şekilde eklenir; **üzerine kalemle yazılır**, silgiler slaytı silmez. Panelin **Belgeler** bölümünden
  belgeye gidilir ya da belge kaldırılır (geri alınabilir).
- **Sunum kumandası:** PageDown / PageUp (ya da sağ / sol ok) sonraki / önceki sayfanın başına geçer.
- PDF'ler tarayıcıda, projeye gömülü **pdf.js** ile çizilir (`ui/tahta/pdfjs/`, internet gerekmez).
- PowerPoint / Word dosyaları önce bu bilgisayarda PDF'e çevrilir (`core/belge_donustur.py`):
  Windows'ta yüklüyse **Microsoft PowerPoint / Word**, yoksa **LibreOffice**. Hiçbiri yoksa öğretmene dosyayı
  PDF olarak kaydetmesi söylenir. Dosya geçici klasörde işlenir ve silinir; internete gönderilmez. Sınır: 30 MB.
- Ders bitince tahtanın son hali (slaytlar ve üzerine yazılanlarla) `tahtalar/` klasörüne PNG + JSON olarak yazılır.
- Kamera önizleme penceresi artık küçük açılır ve sol alt köşeye yerleşir (`.env`: `KAMERA_ONIZLEME=kucuk|normal|kapali`).

## 🛠️ Türkçe karakterli klasörler ve dayanıklılık

Windows'ta proje yolunda ya da kullanıcı adında Türkçe karakter varsa (ör. `C:\Users\acer\OneDrive\Masaüstü\...`)
C++ tabanlı kütüphaneler dosyayı açamıyordu (`Unable to open file at ...face_landmarker.task`). Düzeltmeler
(`core/model_yukle.py`):

- **MediaPipe** (odak ölçümü), **OpenCV YuNet/SFace** (rızalı yüz kaydı) ve **ONNX** (öğretmen sesi ayrımı) modelleri
  artık yoldan değil **bellekten** yüklenir. Desteklemeyen eski sürümlerde model, İngilizce karakterli bir önbellek
  klasörüne kopyalanıp oradan açılır.
- **Whisper** modeli, kullanıcı klasörünün adında Türkçe karakter varsa İngilizce karakterli bir klasöre iner;
  ses dosyası PyAV'ye dosya nesnesi olarak verilir.
- Model indirmeleri önce geçici dosyaya yapılır: yarım kalan indirme bozuk model bırakmaz.
- **Görüntü tarafı çökerse ders kaybolmaz:** kamera açılamazsa ya da görüntü modeli hata verirse ders yalnızca sesle
  sürer ve notlar yine hazırlanır (önceden bütün kayıt "hata" ile bitiyordu). Ders ortasında çökerse o ana kadarki
  odak ölçümü korunur.
- `edge_mediapipe.py`, MediaPipe 0.10.3x'te kaldırılan `mp.solutions` yerine Tasks API'sine taşındı.
- `baslat.bat`, proje OneDrive klasöründeyse uyarır: senkronizasyon kayıt dosyalarını kilitleyebilir; sorun yaşarsanız
  klasörü `C:\DersAsistani` gibi bir yere taşıyın.

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

---

## 🙋 Rızalı kişisel odak raporu (yüz tanıma yalnızca kayıtlı öğrenciye)

**Model:** Sınıftaki herkes anonim sınıf ortalamasına katılır. Yalnızca **açık rıza veren ve öğretmenin kaydettiği**
öğrenci kamerada tanınır; onun odağı ayrıca kendi adına ölçülür ve raporunu **yalnızca kendisi** görür.

1. **Kayıt (öğretmen):** Öğretmen arayüzü → **"👥 Rızalı öğrenci kaydı"** → ad + rıza onayı + kameradan 3-4 yüz örneği
   → **"Kaydı tamamla ve şifre üret"**. Her öğrenciye **farklı** bir şifre üretilir (ör. `7KQ-M3P`); öğrenciye verilir.
   Şifre yalnızca bir kez gösterilir; unutulursa listeden **"🔑 Yeni şifre"**.
2. **Ders:** Kamera herkesin odağını ölçer (sınıf ortalaması). Saniyede bir karedeki yüzlerin "yüz izi" kayıtlı izlerle
   karşılaştırılır: eşleşen öğrencinin skoru ayrıca kaydedilir (önizlemede adı yazar); eşleşmeyenlerin izi **anında atılır**.
3. **Öğrenci:** `?rol=ogrenci` → kendi şifresiyle girer → **kendi** odak grafiği ve **kendi** kopma anlarına göre kartlar.
   Kamera onu tanımadıysa sınıf ortalaması gösterilir. Yan panelden yüz izini ve tüm kişisel verisini kalıcı olarak silebilir.

**Gizlilik:** Fotoğraf saklanmaz; yalnızca geri döndürülemez yüz izi (128 sayı) `ogrenciler.db` (SQLite) içinde tutulur.
Şifrelerin kendisi değil, gizli anahtarlı özeti saklanır. Yanlış eşleşmeye karşı sıkı benzerlik eşiği (0,42) ve
art arda tutarlı tanıma şartı vardır; bir öğrenci aynı anda yalnızca tek bir yüze atanabilir.

**Dosyalar:** `core/ogrenci_db.py`, `sensing/focus/yuz_kimligi.py`, `ui/ogrenci_kayit.py`,
modeller `sensing/focus/modeller/yuz_tespit_yunet.onnx` + `yuz_izi_sface.onnx` (OpenCV; ek kurulum gerekmez).

---

## 🔑 Gemini kotası (ücretsiz katman)

Ücretsiz katmanda kota **anahtar (proje) ve model başınadır** (ör. günde 20 istek). `llm/gemini_havuzu.py` bir model/anahtar
dolunca otomatik olarak sıradakine geçer: `gemini-3.5-flash → 3.5-flash-lite → 3.1-flash-lite → 2.5-flash → 2.5-flash-lite`,
her biri için `.env`'deki bütün anahtarlar (`GEMINI_API_KEY`, `GEMINI_API_KEY_2`, `GEMINI_API_KEY_3`). Başka Google
hesaplarından alınan anahtarları eklemek kotayı katlar.

### Öğrenci girişi, katılım ve kalıcı kayıtlar
- **Kayıtlı öğrenci:** şifreyle girer → **kendi** odak raporu. Derste kamerada hiç görülmediyse odak puanı **0** gösterilir;
  ders notları ve mini quiz yine açıktır. Öğretmen yalnızca "N kayıtlı öğrenciden M'si derste tanındı" özetini görür.
- **Kayıtsız öğrenci:** şifresiz "Kayıtsız öğrenci olarak devam et" → notlar + sınıf ortalamasına göre kartlar + quiz.
- **Kayıtlar kalıcıdır:** öğrenci veritabanı ve yüz modeli proje klasöründe değil, `<kullanıcı klasörü>\DersAsistani\`
  içinde tutulur. Yeni bir sürümü başka klasöre kursanız da öğrencileri yeniden kaydetmeniz gerekmez (eski klasördeki
  `ogrenciler.db` ilk açılışta otomatik taşınır). Klasörü değiştirmek için `.env`: `DERS_ASISTANI_VERI=...`
