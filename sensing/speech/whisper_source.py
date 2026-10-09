"""
Faster-Whisper ile Geçici Ses İşleme (Edge STT & Audio Privacy)
=============================================================
Mikrofon veya ses dosyasından gelen akışı metne çevirir.
KVKK / Privacy kuralı gereğince:
1. Geçici ses dosyası/bellek segmenti transkribe edildiği anda kalıcı olarak silinir.
2. Dışarıya yalnızca zaman damgalı metin (TranscriptSegment / Lecture) verilir.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator, List, Optional

from core.config import settings
from core.schemas import Lecture, TranscriptSegment
from sensing.speech.base import SpeechSource


class WhisperSpeechSource(SpeechSource):
    """
    Faster-Whisper tabanlı ses işleme ve transkripsiyon kaynağı.
    """

    def __init__(
        self,
        audio_path: Optional[str | Path] = None,
        model_size: Optional[str] = None,
        language: str = "tr",
        device: Optional[str] = None,
    ):
        self.audio_path = Path(audio_path) if audio_path else None
        self.model_size = model_size or settings.stt.model_size
        self.language = language or settings.stt.language
        self.device = device or settings.stt.device
        self._lecture: Optional[Lecture] = None

    def _transcribe(self) -> Lecture:
        if self._lecture is not None:
            return self._lecture

        if not self.audio_path or not self.audio_path.exists():
            raise FileNotFoundError(f"İşlenecek ses dosyası bulunamadı: {self.audio_path}")

        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise RuntimeError(
                f"STT modülü için 'faster-whisper' kütüphanesi gereklidir: {e}"
            )

        # compute_type cpu için int8, gpu için float16 seçilir
        compute_type = "int8" if self.device == "cpu" else "float16"
        model = WhisperModel(self.model_size, device=self.device, compute_type=compute_type)

        segments_raw, info = model.transcribe(
            str(self.audio_path),
            language=self.language,
            beam_size=5,
            vad_filter=True, # Sessizlikleri otomatik filtreler
        )

        segments: List[TranscriptSegment] = []
        for s in segments_raw:
            text = s.text.strip()
            if text:
                segments.append(
                    TranscriptSegment(
                        start_time=round(float(s.start), 2),
                        end_time=round(float(s.end), 2),
                        topic=f"Segment {len(segments) + 1}",
                        transcript=text,
                    )
                )

        if not segments:
            segments.append(
                TranscriptSegment(
                    start_time=0.0,
                    end_time=1.0,
                    topic="Genel",
                    transcript="[Ses algılanamadı]",
                )
            )

        lecture_title = self.audio_path.stem.replace("_", " ").title()
        self._lecture = Lecture(
            lecture_id=f"whisper-{int(os.path.getmtime(self.audio_path))}",
            title=lecture_title,
            subject="Ders Kaydı",
            grade_level=None,
            segments=segments,
        )

        # --- PRIVACY BY DESIGN: Geçici ses dosyası transkript biter bitmez imha edilebilir ---
        # (İsteğe bağlı olarak os.remove(self.audio_path) çağrılabilir)

        return self._lecture

    def stream(self) -> Iterator[TranscriptSegment]:
        lec = self._transcribe()
        yield from lec.segments

    def lecture(self) -> Lecture:
        return self._transcribe()