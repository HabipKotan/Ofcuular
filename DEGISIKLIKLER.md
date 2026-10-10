# v5 = bizim v4 + arkadaşımızın görüntü işleme iyileştirmeleri

## Arkadaşımızın görüntü işleme iyileştirmeleri (v3 üzerinden yapılmıştı, v4 ile birleştirildi)

| Değişiklik | Açıklama |
|---|---|
| Uzak yüz modu (varsayılan) | YuNet tüm kareyi tarar, her yüz kırpılıp büyütülerek ölçülür: arka sıralar da görülür. `KAMERA_ALGILAMA=yakin` eski yönteme döner |
| Kamera 1280×720 (MJPG) | `KAMERA_GENISLIK`, `KAMERA_YUKSEKLIK`; kamera desteklemezse uyarır |
| Esneme cezası | `jawOpen` 0,5'i geçince skor kademeli düşer (tam esnemede 35); `--esneme-cezasi-yok` ile kapanır |
| Olay nedeni | Uzun düşüşlerde "esneme / uyku hali" de neden olarak yazılır |
| Küçük yüzler | 30 pikselin altındaki yüzlerde göz/ağız okunmaz, yalnızca baş yönü sayılır; günlükte fps ve küçük yüz oranı |
| `tests/test_dikkat_esneme.py` | Kamera gerektirmeyen 6 birim testi (`python -m pytest tests/`) |

Birleştirmede yapılan uyarlamalar:

- Uzak moddaki modeller (MediaPipe, YuNet) de **bellekten** yükleniyor; özgün hali yoldan yüklediği için "Masaüstü" klasöründe aynı `Unable to open file` hatasını verecekti. YuNet indirmesi yarım kalmıyor.
- Özgün kodda `vision` / `mp_python` adları, v4'te kaldırılan içe aktarmalara dayanıyordu; birleşince uzak mod ilk karede çökecekti. Sınıf artık kendi içe aktarmalarını yapıyor.
- Uzak mod kurulamazsa ölçüm durmuyor, yakın moda geçiyor; o da olmazsa ders yalnızca sesle sürüyor.
- Yakın moddaki MediaPipe dedektörü artık yalnızca yakın modda oluşturuluyor (uzak modda boşuna bellek tutmuyor).
- Küçük önizleme penceresi kameranın en-boy oranına uyuyor (16:9).

## Bizim v4 değişikliklerimiz

| Dosya | Değişiklik |
|---|---|
| `core/model_yukle.py` (yeni) | Modelleri bellekten yükleme, İngilizce karakterli önbellek, güvenli (yarım kalmayan) indirme |
| `sensing/focus/classroom_focus.py` | MediaPipe modeli bellekten; model kamera açılmadan önce yüklenir; küçük önizleme penceresi |
| `ders_kaydi.py` | Kamera / görüntü modeli hata verirse ders yalnızca sesle sürer; `KAMERA_ONIZLEME` ayarı |
| `sensing/focus/yuz_kimligi.py` | YuNet / SFace bellekten; güvenli indirme |
| `ses_hatti/konusmaci.py` | Konuşmacı modeli bellekten |
| `ses_hatti/transkript.py`, `sensing/speech/whisper_source.py` | Whisper için güvenli model klasörü; PyAV'ye dosya nesnesi |
| `sensing/focus/edge_mediapipe.py` | Kaldırılan `mp.solutions` yerine Tasks API |
| `ui/tahta/index.html` | Tam ekran, belge ekleme / sürükle-bırak, PDF çizimi, belgeler paneli, sunum kumandası, uyarı şeridi, iki adımlı "Dersi bitir" |
| `ui/tahta/pdfjs/` (yeni) | Gömülü pdf.js 5.4.296 (Apache-2.0), internetsiz PDF |
| `ui/tahta_bileseni.py` | Tam ekran katmanı ve tahtadan gelen yeni olaylar (bitir, tam ekran, belge dönüştür) |
| `core/belge_donustur.py` (yeni) | PowerPoint / Word -> PDF (Office ya da LibreOffice) |
| `ui/ders_kontrol.py` | Kamera / mikrofon uyarıları tam ekran tahtaya iletilir |
| `.streamlit/config.toml` | `maxMessageSize` 50 -> 100 MB (slaytlı tahta ve sunumlar için) |
| `baslat.bat` | Proje OneDrive klasöründeyse uyarı |
| `README.md` | Yeni bölümler; yüz tanıma / veritabanı / EAR tutarsızlıkları düzeltildi |

Test edilenler (Linux + Chromium, proje `Masaüstü/ders (7)/` klasöründeyken): ders başlayınca tam ekran, PDF ve
PowerPoint ekleme (LibreOffice ile), sürükle-bırak, sayfa çakışmaması, silginin slaytı silmemesi, PageDown,
Küçült / Tam ekran, uyarı şeridi, "Dersi bitir" -> durdurma + tahta arşivi, görüntü modeli hatasında sesle devam.
Windows'a özgü PowerPoint/Word dönüştürmesi bu ortamda denenemedi.
