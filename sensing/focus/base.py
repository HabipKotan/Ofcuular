"""
Odak kaynağı arayüzü. Sentetik üretici ve gerçek MediaPipe modülü
bu sözleşmeye uyar; geri kalan sistem hangisinin çalıştığını bilmez.

Mahremiyet sözleşmesi: Bir FocusSource dışarıya YALNIZCA FocusSample
döndürür. Kare, landmark, yüz verisi gibi hiçbir ham veri bu sınırı geçmez.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator, List

from core.schemas import FocusSample


class FocusSource(ABC):
    @abstractmethod
    def stream(self) -> Iterator[FocusSample]:
        """Odak örneklerini zaman sırasıyla üretir."""

    def collect(self) -> List[FocusSample]:
        return list(self.stream())
