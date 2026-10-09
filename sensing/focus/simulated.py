"""
Sentetik odak üreteci
=====================
Gerçekçi bir öğrenci dikkat eğrisi üretir:

* Taban seviye: ders başında yüksek, zamanla hafifçe azalan (yorgunluk eğrisi)
* Gürültü: küçük rastgele dalgalanmalar
* Göz kırpma artefaktları: tek örneklik ani düşüşler (smoothing bunları elemeli)
* Planlı dikkat düşüşleri: demo senaryosunu belirleyen gerçek "kopma" anları

`seed` sabit tutulduğu için demo her çalıştırmada aynı sonucu verir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, List

import numpy as np

from core.schemas import FocusSample
from sensing.focus.base import FocusSource


@dataclass(frozen=True)
class FocusDip:
    """Planlı bir dikkat düşüşü. Kenarları yumuşak geçişlidir (gerçekçi kopma/dönüş)."""

    start: float          # sn
    end: float            # sn
    depth: float          # düşüşün ulaştığı odak seviyesi (0-100)
    ramp: float = 6.0     # düşüşe giriş/çıkış süresi (sn)


# Demo senaryosu: türev dersinde öğrencinin kaçırdığı anlar
DEMO_DIPS: List[FocusDip] = [
    # 'Türevin Limit Tanımı' bölümünün ortasında uzun bir kopma (sınavlık kısım!)
    FocusDip(start=315, end=385, depth=22),
    # 'Toplam ve Çarpım Kuralı' içinde kısa ama derin düşüş
    FocusDip(start=610, end=650, depth=28),
    # Kapanışa doğru 10 sn'lik kısa dalgınlık: eşik altına iner ama
    # min_gap_duration (15 sn) nedeniyle kart üretmemeli
    FocusDip(start=760, end=770, depth=40, ramp=2.0),
]


@dataclass
class SimulatedFocusSource(FocusSource):
    duration: float
    sample_rate_hz: float = 1.0
    dips: List[FocusDip] = field(default_factory=lambda: list(DEMO_DIPS))
    baseline_start: float = 82.0
    baseline_end: float = 68.0
    noise_std: float = 4.0
    blink_probability: float = 0.04
    seed: int = 42

    def _baseline(self, t: np.ndarray) -> np.ndarray:
        frac = t / max(self.duration, 1.0)
        # Doğrusal yorgunluk + hafif periyodik dalgalanma
        return (
            self.baseline_start
            + (self.baseline_end - self.baseline_start) * frac
            + 3.0 * np.sin(2 * np.pi * t / 180.0)
        )

    def _apply_dips(self, t: np.ndarray, scores: np.ndarray) -> np.ndarray:
        for dip in self.dips:
            # 0..1 arası "düşüş yoğunluğu": rampalarla yumuşak giriş/çıkış
            rise = np.clip((t - dip.start) / dip.ramp, 0, 1)
            fall = np.clip((dip.end - t) / dip.ramp, 0, 1)
            weight = np.minimum(rise, fall)
            scores = scores * (1 - weight) + dip.depth * weight
        return scores

    def stream(self) -> Iterator[FocusSample]:
        rng = np.random.default_rng(self.seed)
        step = 1.0 / self.sample_rate_hz
        t = np.arange(0.0, self.duration + 1e-9, step)

        scores = self._baseline(t)
        scores = self._apply_dips(t, scores)
        scores = scores + rng.normal(0, self.noise_std, size=t.shape)

        # Göz kırpma: tek örneklik ani ve sahte düşüşler
        blinks = rng.random(t.shape) < self.blink_probability
        scores[blinks] = rng.uniform(10, 35, size=blinks.sum())

        scores = np.clip(scores, 0, 100)
        for ts, sc in zip(t, scores):
            yield FocusSample(timestamp=round(float(ts), 2), focus_score=round(float(sc), 1))
