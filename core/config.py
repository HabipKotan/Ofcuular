"""
Merkezi ayarlar. Değerler .env dosyasından ya da ortam değişkenlerinden okunur;
yoksa aşağıdaki makul varsayılanlar kullanılır.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv opsiyonel
    pass


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class FocusConfig:
    # Odak skoru bu değerin altına inerse "dikkat düşük" sayılır
    threshold: float = _env_float("FOCUS_THRESHOLD", 50.0)
    # Hareketli ortalama penceresi (sn) — göz kırpma gibi anlık gürültüyü bastırır
    smoothing_window_s: float = _env_float("FOCUS_SMOOTHING_WINDOW", 5.0)
    # Bu süreden kısa düşüşler önemsenmez (sn)
    min_gap_duration_s: float = _env_float("FOCUS_MIN_GAP", 15.0)
    # Aralarında bu kadar ya da daha az boşluk olan iki düşüş birleştirilir (sn)
    merge_gap_s: float = _env_float("FOCUS_MERGE_GAP", 8.0)
    # Bir segmentin bu orandan azı kaçırıldıysa kart üretilmez
    min_segment_coverage: float = _env_float("FOCUS_MIN_COVERAGE", 0.15)
    # Örnekleme sıklığı (Hz) — sentetik üretici ve MediaPipe için
    sample_rate_hz: float = _env_float("FOCUS_SAMPLE_RATE", 1.0)


@dataclass(frozen=True)
class LLMConfig:
    provider: str = os.getenv("LLM_PROVIDER", "anthropic")  # anthropic | mock
    model: str = os.getenv("LLM_MODEL", "claude-sonnet-5-5")
    api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
    max_tokens: int = int(os.getenv("LLM_MAX_TOKENS", "2000"))

    @property
    def use_mock(self) -> bool:
        return self.provider == "mock" or not self.api_key


@dataclass(frozen=True)
class STTConfig:
    model_size: str = os.getenv("WHISPER_MODEL", "small")  # tiny | base | small | medium
    language: str = os.getenv("WHISPER_LANGUAGE", "tr")
    device: str = os.getenv("WHISPER_DEVICE", "cpu")


@dataclass(frozen=True)
class AppConfig:
    focus: FocusConfig = field(default_factory=FocusConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    stt: STTConfig = field(default_factory=STTConfig)


settings = AppConfig()
