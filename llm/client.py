"""
LLM İstemci Katmanı (LLMClient & MockProvider)
==============================================
API anahtarı varsa Anthropic Claude API çağrısı yapar.
API anahtarı yoksa veya provider='mock' ise hackathon jürisi önünde
çökmeyen, deterministik, yüksek kaliteli hazır pedagojik senaryolar üreten Mock LLM devreye girer.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict

from core.config import settings
from core.schemas import GapWindow, Lecture, LectureNotes, NoteSection, QuizQuestion, RecoveryCard

logger = logging.getLogger(__name__)


class MockLLMService:
    """İnternetsiz veya API anahtarsız ortamlarda jüri sunumu için çalışan mock servis."""

    @staticmethod
    def generate_recovery_card(gap: GapWindow) -> RecoveryCard:
        topic_lower = gap.topic.lower()

        if "limit tanımı" in topic_lower or "limit" in topic_lower:
            summary_text = (
                "Türev, bir fonksiyonun anlık değişim hızını ve eğriye çizilen teğetin eğimini ifade eder. "
                "Teğet eğimine ulaşmak için eğri üzerindeki iki nokta arasındaki mesafe olan h sıfıra yaklaştırılır. "
                "Bu yaklaşım türevin temel limit formülünü oluşturur: f'(x) = lim_{h -> 0} [f(x + h) - f(x)] / h.\n\n"
                "Örnek İspat: f(x) = x² için f(x + h) = (x + h)² = x² + 2xh + h² açılımı yapılır. "
                "Pay kısmı: [x² + 2xh + h²] - x² = 2xh + h² olur. İfade h parantezine alınıp sadeleştirildiğinde "
                "2x + h kalır. h sıfıra giderken limit 2x çıkar. Böylece x²'nin türevinin neden 2x olduğu tanımdan kanıtlanmış olur."
            )
            return RecoveryCard(
                topic=gap.topic,
                gap_start=gap.start_time,
                gap_end=gap.end_time,
                summary=summary_text,
                key_points=[
                    "Temel Limit Tanımı: f'(x) = lim_{h -> 0} [f(x + h) - f(x)] / h",
                    "Geometrik Anlam: Kesen doğrusunun h -> 0 durumundaki teğet doğrusuna dönüşmesi ve eğimi.",
                    "İspat Adımı: f(x) = x² için pay (2xh + h²) olup h ile sadeleştiğinde 2x sonucunu verir.",
                ],
                questions=[
                    QuizQuestion(
                        question="Türevin limit tanımında 'h' parametresi geometrik olarak neyi temsil eder ve neden sıfıra yaklaşır?",
                        options=[
                            "A) Teğet doğrusunun y-eksenini kestiği noktadır; eğimi sabit tutmak için sıfıra yaklaşır.",
                            "B) Eğri üzerindeki iki nokta arasındaki apsis farkıdır; keseni teğet doğrusuna dönüştürmek için sıfıra yaklaşır.",
                            "C) Fonksiyonun alabileceği en büyük yerel ekstremum değeridir.",
                            "D) Eğrinin x ekseniyle yaptığı açının radyan cinsinden değeridir.",
                        ],
                        correct_index=1,
                        explanation="h, iki nokta arasındaki mesafedir. h sıfıra yaklaştıkça kesen doğru dönerek tek bir noktada değen teğet doğruya dönüşür ve anlık eğimi verir.",
                    ),
                    QuizQuestion(
                        question="f(x) = x² fonksiyonunun limit tanımı f'(x) = lim_{h->0} [f(x+h) - f(x)]/h uygulandığında pay kısmındaki sadeleşme adımı nedir?",
                        options=[
                            "A) (x² + h²) - x² = h²",
                            "B) (x² + 2xh + h²) - x² = 2xh + h²",
                            "C) (x² + xh) - x² = xh",
                            "D) 2x + h - x²",
                        ],
                        correct_index=1,
                        explanation="(x + h)² tam karesi x² + 2xh + h² açılır. - x² çıkarıldığında geriye 2xh + h² kalır; bu da h ile sadeleşerek 2x + h verir.",
                    ),
                ],
            )
        elif "çarpım" in topic_lower or "toplam" in topic_lower:
            summary_text = (
                "Toplamın türevinde kurallar oldukça sadedir: [f(x) + g(x)]' = f'(x) + g'(x). "
                "Ancak matematikte ve sınavlarda öğrencilerin en çok aldandığı yer ÇARPIMIN TÜREVİDİR: "
                "Çarpımın türevi ASLA türevlerin çarpımı değildir [yani (f·g)' ≠ f'·g'].\n\n"
                "Doğru Kural: (f · g)' = f' · g + f · g' (Birincinin türevi × İkinci + Birinci × İkincinin türevi).\n"
                "Örnek: f(x) = x² · (x + 1) fonksiyonunda u = x² ve v = (x + 1) dersek; "
                "u' = 2x ve v' = 1 olur. Kuralı uygularsak: (2x)(x + 1) + (x²)(1) = 2x² + 2x + x² = 3x² + 2x bulunur. "
                "Parantezi önce dağıtıp (x³ + x²) türev aldığımızda da aynı 3x² + 2x sonucuna ulaşarak kuralı doğrularız."
            )
            return RecoveryCard(
                topic=gap.topic,
                gap_start=gap.start_time,
                gap_end=gap.end_time,
                summary=summary_text,
                key_points=[
                    "Toplam Kuralı: [f(x) + g(x)]' = f'(x) + g'(x)",
                    "Çarpım Kuralı: [f(x) · g(x)]' = f'(x)·g(x) + f(x)·g'(x)",
                    "Önemli Uyarı: (f · g)' ≠ f' · g' — bu en yaygın işlem hatasıdır!",
                    "Kontrol Yöntemi: Polinom çarpımlarında ifadeyi önce açıp sonra kuvvet kuralıyla sağlamasını yapabilirsiniz.",
                ],
                questions=[
                    QuizQuestion(
                        question="İki türevlenebilir fonksiyon f(x) ve g(x) için çarpımın türev kuralı hangisidir?",
                        options=[
                            "A) (f · g)' = f' · g'",
                            "B) (f · g)' = f' · g + f · g'",
                            "C) (f · g)' = f' · g - f · g'",
                            "D) (f · g)' = (f' + g') · (f + g)",
                        ],
                        correct_index=1,
                        explanation="Çarpımın türevi simetrik toplam kuralına uyar: Birincinin türevi çarpı ikinci artı birinci çarpı ikincinin türevi.",
                    ),
                    QuizQuestion(
                        question="f(x) = x² · (x + 1) fonksiyonunun türevi çarpım kuralı ile hesaplandığında sonuç nedir?",
                        options=[
                            "A) 2x",
                            "B) 3x² + 1",
                            "C) 3x² + 2x",
                            "D) 2x² + 2x",
                        ],
                        correct_index=2,
                        explanation="f'(x) = [d/dx(x²)]·(x+1) + x²·[d/dx(x+1)] = 2x(x+1) + x²(1) = 2x² + 2x + x² = 3x² + 2x.",
                    ),
                ],
            )
        elif "tahta" in topic_lower or "kapanış" in topic_lower:
            summary_text = (
                "Dersin kapanış bölümünde çok terimli (polinom) fonksiyonların türevi ve teğet eğimi hesabı pekiştirilmiştir. "
                "İncelenen soru: f(x) = 3x⁴ - 2x² + 7x - 5 fonksiyonunun x = 1 noktasındaki teğetinin eğimi kaçtır?\n\n"
                "Çözüm Adımları:\n"
                "1. Kuvvet kuralı ve sabit türevi uygulanarak türev fonksiyonu bulunur: f'(x) = 12x³ - 4x + 7.\n"
                "2. Teğet eğimi fonksiyonun o noktadaki türevine eşit olduğundan x = 1 konur: "
                "f'(1) = 12(1)³ - 4(1) + 7 = 12 - 4 + 7 = 15 bulunur.\n"
                "Pedagojik Not: Bölüm ve zincir kuralları gelecek haftanın konusu olarak duyurulmuş ve kitaptaki ilk 10 soru ödev verilmiştir."
            )
            return RecoveryCard(
                topic=gap.topic,
                gap_start=gap.start_time,
                gap_end=gap.end_time,
                summary=summary_text,
                key_points=[
                    "Polinom Türevi: f(x) = 3x⁴ - 2x² + 7x - 5 => f'(x) = 12x³ - 4x + 7",
                    "Teğet Eğimi Hesabı: m = f'(x_0) kuralı gereği x=1 için eğim 15'tir.",
                    "Ödev ve Gelecek Hafta: İlk 10 soru çözülecek; haftaya Bölüm ve Zincir kuralları işlenecektir.",
                ],
                questions=[
                    QuizQuestion(
                        question="f(x) = 3x⁴ - 2x² + 7x - 5 fonksiyonunun x = 1 noktasındaki teğet doğrusunun eğimi kaçtır?",
                        options=[
                            "A) 11",
                            "B) 15",
                            "C) 19",
                            "D) 7",
                        ],
                        correct_index=1,
                        explanation="f'(x) = 12x³ - 4x + 7 fonksiyonunda x yerine 1 yazıldığında f'(1) = 12 - 4 + 7 = 15 elde edilir.",
                    ),
                    QuizQuestion(
                        question="Öğretmen ders sonunda gelecek hafta hangi konulara geçileceğini belirtmiştir?",
                        options=[
                            "A) İntegral ve Alan Hesabı",
                            "B) Bölüm Kuralı ve Zincir Kuralı",
                            "C) Trigonometrik Fonksiyonların Grafikleri",
                            "D) Matrisler ve Determinant",
                        ],
                        correct_index=1,
                        explanation="Dersin kapanışında açıkça 'Haftaya bölüm kuralı ve zincir kuralına geçeceğiz' ifadesi kullanılmıştır.",
                    ),
                ],
            )
        else:
            return RecoveryCard(
                topic=gap.topic,
                gap_start=gap.start_time,
                gap_end=gap.end_time,
                summary=(
                    f"'{gap.topic}' konusu anlatılırken dikkat dağınıklığı tespit edildi. "
                    f"Bu bölümde öğretmen konunun ana prensiplerini ve temel kurallarını aktarmıştır: "
                    f"{gap.missed_transcript[:250]}..."
                ),
                key_points=[
                    f"{gap.topic} temel tanım ve kurallarının kavranması.",
                    "Derste çözülen adımların ve işlem önceliklerinin pekiştirilmesi.",
                ],
                questions=[
                    QuizQuestion(
                        question=f"'{gap.topic}' bölümünde vurgulanan temel ilke nedir?",
                        options=[
                            "A) Temel kural ve formüllerin sırayla ve dikkatle uygulanması",
                            "B) Sabit terimlerin katsayı gibi türeve dahil edilmesi",
                            "C) Grafiğin x-keseninin doğrudan türev kabul edilmesi",
                        ],
                        correct_index=0,
                        explanation="Ders anlatımında kural adımlarının sistematik takibi vurgulanmıştır.",
                    ),
                    QuizQuestion(
                        question=f"Bu kural hangi tip fonksiyonel problemlerde uygulanır?",
                        options=[
                            "A) Yalnızca trigonometrik denklemlerde",
                            "B) Fonksiyonun anlık değişim oranını ve teğet eğimini analitik yolla bulmak için",
                            "C) Sadece grafik çizimlerinde eksen belirlemek için",
                        ],
                        correct_index=1,
                        explanation="Türev kuralları anlık değişim hızını ve teğet eğimini analitik olarak bulmamızı sağlar.",
                    ),
                ],
            )

    @staticmethod
    def generate_lecture_notes(lecture: Lecture) -> LectureNotes:
        sections = [
            NoteSection(
                topic="Giriş ve Limit Hatırlatması",
                content=(
                    "Türev kavramının temeli limit kavramına dayanır. Fonksiyonun bir noktadaki davranışı incelenirken, "
                    "x bağımsız değişkeni bir a değerine yaklaşırken f(x)'in yöneldiği değer fonksiyona ait limiti verir. "
                    "Türev, bu limit yaklaşımının anlık değişim hızına uyarlanmış halidir."
                ),
                key_terms=["Limit", "Yaklaşım", "Süreklilik", "Anlık Değer"],
            ),
            NoteSection(
                topic="Ortalama Değişim Hızı ve Teğet Eğimi",
                content=(
                    "Bir hareketlinin belirli bir zaman aralığındaki ortalama hızı, toplam yer değiştirmenin geçen süreye bölünmesiyle bulunur: "
                    "Ortalama Hız = [f(b) - f(a)] / (b - a). Bu oran geometrik olarak eğriyi (a, f(a)) ve (b, f(b)) noktalarında "
                    "kesen doğrunun eğimidir. İkinci nokta birinciye yaklaştıkça kesen doğru teğet doğruya dönüşür."
                ),
                key_terms=["Ortalama Değişim Hızı", "Kesen Doğru", "Teğet Doğru", "Teğet Eğimi"],
            ),
            NoteSection(
                topic="Türevin Limit Tanımı",
                content=(
                    "Türev, fonksiyonun teğet doğrusunun eğimidir ve limit tanımı şu şekildedir:\n"
                    "f'(x) = lim_{h -> 0} [f(x + h) - f(x)] / h\n"
                    "Burada h iki apsis noktası arasındaki farktır. h sıfıra yaklaştığında anlık değişim oranı (türev) elde edilir. "
                    "Örneğin f(x) = x² için yapılan limit hesabı sonucunda f'(x) = 2x bulunur."
                ),
                key_terms=["Türev Tanımı", "Limit", "h Artımı", "Teğet Eğimi"],
            ),
            NoteSection(
                topic="Kuvvet Kuralı",
                content=(
                    "Her türev işleminde limit tanımını kullanmak yerine pratik kurallar uygulanır:\n"
                    "1. Kuvvet Kuralı: d/dx(x^n) = n · x^(n - 1). (Üs başa katsayı olarak iner ve üs 1 azaltılır).\n"
                    "2. Sabit Fonksiyon Türevi: c bir reel sayı olmak üzere d/dx(c) = 0.\n"
                    "3. Sabit Çarpan Kuralı: d/dx[c · f(x)] = c · f'(x)."
                ),
                key_terms=["Kuvvet Kuralı", "Sabit Fonksiyon Türevi", "Sabit Çarpan", "Üs Azaltma"],
            ),
            NoteSection(
                topic="Toplam ve Çarpım Kuralı",
                content=(
                    "1. Toplamın Türevi: [f(x) + g(x)]' = f'(x) + g'(x).\n"
                    "2. Çarpımın Türevi: [f(x) · g(x)]' = f'(x)·g(x) + f(x)·g'(x).\n"
                    "Önemli pedagojik uyarı: Çarpımın türevi türevlerin çarpımına eşit değildir! "
                    "Örnek: f(x) = x² · (x + 1) türevi 2x(x + 1) + x²(1) = 3x² + 2x olarak bulunur."
                ),
                key_terms=["Toplam Kuralı", "Çarpım Kuralı", "Simetrik Dağılım"],
            ),
            NoteSection(
                topic="Tahta Çözümü ve Kapanış",
                content=(
                    "Ders sonunda tahtada çözülen polinom probleminde kuvvet, sabit katsayı ve toplam kuralları birlikte uygulandı. "
                    "f(x) = 3x⁴ - 2x² + 7x - 5 fonksiyonunun x = 1 noktasındaki teğet eğimi 15 olarak hesaplandı.\n"
                    "Gelecek Ders Planı: Bölüm Kuralı ve Zincir Kuralı konularına geçilecektir."
                ),
                key_terms=["Polinom Türevi", "Teğet Eğimi Hesabı", "Bölüm Kuralı (Haftaya)", "Zincir Kuralı (Haftaya)"],
            ),
        ]

        board_solutions = [
            "1. Limit Tanımı İspatı: f(x) = x² => f'(x) = lim_{h->0} [(x+h)² - x²]/h = lim_{h->0} [2xh + h²]/h = 2x",
            "2. Kuvvet & Katsayı Örneği: d/dx(5x³) = 5 · (3x²) = 15x²",
            "3. Çarpım Kuralı Örneği: d/dx[x² · (x+1)] = (2x)(x+1) + (x²)(1) = 2x² + 2x + x² = 3x² + 2x",
            "4. Kapanış Uygulama Sorusu: f(x) = 3x⁴ - 2x² + 7x - 5 ise f'(1) = ?\n"
            "   Adım 1: f'(x) = 12x³ - 4x + 7\n"
            "   Adım 2: f'(1) = 12(1)³ - 4(1) + 7 = 12 - 4 + 7 = 15 (x=1 noktasındaki teğetin eğimi)",
        ]

        return LectureNotes(
            title=lecture.title,
            summary=(
                "Bu derste türevin limit temelli tanımı ve geometrik yorumu (teğet eğimi) incelenmiş; "
                "kuvvet kuralı, sabit fonksiyon türevi, toplam ve çarpım kuralları ispat ve örneklerle ele alınmıştır. "
                "Bölüm ve zincir kuralları gelecek haftanın konusu olarak planlanmıştır."
            ),
            sections=sections,
            board_solutions=board_solutions,
            approved=False,
        )


class LLMService:
    """Gemini ya da Claude ile çalışır; anahtar yoksa / çağrı başarısızsa Mock'a düşer."""

    # Gemini için sırayla denenecek modeller (ilki yoksa ya da kota dolduysa sonraki)
    GEMINI_YEDEK_MODELLER = ["gemini-3.5-flash", "gemini-2.5-flash"]

    def __init__(self):
        self.config = settings.llm
        self.client = None
        self.active_model = None
        if self.config.use_mock:
            return
        try:
            if self.config.provider == "gemini":
                from google import genai
                self.client = genai.Client(api_key=self.config.api_key)
            elif self.config.provider == "anthropic":
                import anthropic
                self.client = anthropic.Anthropic(api_key=self.config.api_key)
            else:
                logger.warning(f"Bilinmeyen LLM_PROVIDER: {self.config.provider}, mock moda geçiliyor.")
        except Exception as e:
            logger.warning(f"{self.config.provider} istemcisi başlatılamadı, mock moda geçiliyor: {e}")
            self.client = None

    # ------------------------------------------------------------------ ortak çağrı
    def _ask(self, system: str, user: str) -> str:
        """Modelden ham metin yanıtı döndürür. Hata olursa exception fırlatır."""
        if self.config.provider == "gemini":
            from google.genai import types
            modeller = [self.config.model] + [m for m in self.GEMINI_YEDEK_MODELLER if m != self.config.model]
            son_hata = None
            for model in modeller:
                try:
                    yanit = self.client.models.generate_content(
                        model=model,
                        contents=user,
                        config=types.GenerateContentConfig(
                            system_instruction=system,
                            response_mime_type="application/json",
                            temperature=0.3,
                        ),
                    )
                    self.active_model = model
                    return yanit.text
                except Exception as e:  # model yok / kota doldu -> sıradakini dene
                    logger.warning(f"Gemini modeli {model} çalışmadı: {e}")
                    son_hata = e
            raise RuntimeError(f"Hiçbir Gemini modeli yanıt vermedi: {son_hata}")

        response = self.client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        self.active_model = self.config.model
        return response.content[0].text

    @staticmethod
    def _json(raw_text: str):
        json_match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        return json.loads(json_match.group(0)) if json_match else None

    # ------------------------------------------------------------------ öğrenci kartı
    def generate_recovery_card(self, gap: GapWindow) -> RecoveryCard:
        if self.config.use_mock or not self.client:
            return MockLLMService.generate_recovery_card(gap)

        from llm.prompts import RECOVERY_CARD_SYSTEM_PROMPT, RECOVERY_CARD_USER_PROMPT

        user_content = RECOVERY_CARD_USER_PROMPT.format(
            topic=gap.topic,
            gap_start=gap.start_time,
            gap_end=gap.end_time,
            missed_transcript=gap.missed_transcript,
        )

        try:
            data = self._json(self._ask(RECOVERY_CARD_SYSTEM_PROMPT, user_content))
            if data:
                # Zaman ve konu bilgisini modelden değil, ölçümden al
                data.update(topic=gap.topic, gap_start=gap.start_time, gap_end=gap.end_time)
                data["questions"] = (data.get("questions") or [])[:2]
                return RecoveryCard.model_validate(data)
            return MockLLMService.generate_recovery_card(gap)
        except Exception as e:
            logger.error(f"LLM çağrısı başarısız oldu, mock fallback kullanılıyor: {e}")
            return MockLLMService.generate_recovery_card(gap)

    # ------------------------------------------------------------------ ders notu
    def generate_lecture_notes(self, lecture: Lecture) -> LectureNotes:
        if self.config.use_mock or not self.client:
            return MockLLMService.generate_lecture_notes(lecture)

        from llm.prompts import LECTURE_NOTES_SYSTEM_PROMPT, LECTURE_NOTES_USER_PROMPT

        user_content = LECTURE_NOTES_USER_PROMPT.format(
            title=lecture.title,
            subject=lecture.subject,
            grade_level=lecture.grade_level or "",
            full_transcript=lecture.full_transcript,
        )

        try:
            data = self._json(self._ask(LECTURE_NOTES_SYSTEM_PROMPT, user_content))
            if data:
                return LectureNotes.model_validate(data)
            return MockLLMService.generate_lecture_notes(lecture)
        except Exception as e:
            logger.error(f"Ders notu LLM çağrısı başarısız, mock fallback devrede: {e}")
            return MockLLMService.generate_lecture_notes(lecture)
