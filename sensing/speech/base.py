"""
Ses/transkript kaynağı arayüzü. Sentetik kaynak ve Whisper modülü bu sözleşmeye uyar.

Mahremiyet sözleşmesi: Bir SpeechSource dışarıya YALNIZCA TranscriptSegment
döndürür. Ham ses verisi bu sınırı geçmez ve işlendiği anda silinir.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator

from core.schemas import Lecture, TranscriptSegment


class SpeechSource(ABC):
    @abstractmethod
    def stream(self) -> Iterator[TranscriptSegment]:
        """Segmentleri anlatıldıkları sırayla üretir (canlı transkript akışı)."""

    @abstractmethod
    def lecture(self) -> Lecture:
        """Ders bitiminde tüm segmentleri içeren Lecture nesnesi."""
