"""
Sentetik transkript kaynağı: data/demo altındaki hazır ders senaryosunu
canlı bir STT akışıymış gibi segment segment sunar.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from core.schemas import Lecture, TranscriptSegment
from sensing.speech.base import SpeechSource

DEMO_DIR = Path(__file__).resolve().parents[2] / "data" / "demo"
DEFAULT_SCENARIO = DEMO_DIR / "turev_dersi.json"


class SimulatedSpeechSource(SpeechSource):
    def __init__(self, scenario_path: Path | str = DEFAULT_SCENARIO):
        raw = json.loads(Path(scenario_path).read_text(encoding="utf-8"))
        self._lecture = Lecture.model_validate(raw)

    def stream(self) -> Iterator[TranscriptSegment]:
        yield from self._lecture.segments

    def lecture(self) -> Lecture:
        return self._lecture
