"""
Zaman Serisi ve Korelasyon Motoru (TimeSeriesMatcher)
===================================================
Akış B (Odak/Görüntü) sinyalini gürültüden arındırır, eşik altındaki düşüş pencerelerini
tespit eder ve Akış A (Ses/Transkript) segmentleriyle kesiştirerek GapWindow listesi üretir.
"""

from __future__ import annotations

from typing import List, Tuple
import numpy as np

from core.config import FocusConfig, settings
from core.schemas import FocusSample, GapWindow, Lecture, TranscriptSegment


class TimeSeriesMatcher:
    def __init__(self, config: FocusConfig | None = None):
        self.config = config or settings.focus

    def smooth_focus_samples(self, samples: List[FocusSample]) -> List[FocusSample]:
        if not samples:
            return []

        timestamps = np.array([s.timestamp for s in samples])
        scores = np.array([s.focus_score for s in samples])

        if len(samples) == 1:
            return [FocusSample(timestamp=timestamps[0], focus_score=scores[0])]

        dt = float(np.median(np.diff(timestamps)))
        if dt <= 0:
            dt = 1.0

        window_size = max(1, int(round(self.config.smoothing_window_s / dt)))
        
        kernel = np.ones(window_size) / window_size
        pad_size = window_size // 2
        # np.pad mode="edge" ile kenarlarda sıfır yerine kenar değerini uzatıyoruz
        padded_scores = np.pad(scores, (pad_size, window_size - 1 - pad_size), mode="edge")
        smoothed_scores = np.convolve(padded_scores, kernel, mode="valid")
        smoothed_scores = np.clip(smoothed_scores, 0.0, 100.0)

        return [
            FocusSample(timestamp=round(float(ts), 2), focus_score=round(float(sc), 1))
            for ts, sc in zip(timestamps, smoothed_scores)
        ]

    def detect_low_focus_intervals(
        self, smoothed_samples: List[FocusSample]
    ) -> List[Tuple[float, float, float, float]]:
        if not smoothed_samples:
            return []

        threshold = self.config.threshold
        raw_intervals: List[List[float]] = []
        current_interval: List[float] | None = None

        for s in smoothed_samples:
            if s.focus_score < threshold:
                if current_interval is None:
                    current_interval = [s.timestamp, s.timestamp, s.focus_score, 1, s.focus_score]
                else:
                    current_interval[1] = s.timestamp
                    current_interval[2] += s.focus_score
                    current_interval[3] += 1
                    current_interval[4] = min(current_interval[4], s.focus_score)
            else:
                if current_interval is not None:
                    raw_intervals.append(current_interval)
                    current_interval = None

        if current_interval is not None:
            raw_intervals.append(current_interval)

        if not raw_intervals:
            return []

        # 1. Aşama: Birbirine çok yakın düşüşleri birleştir (merge_gap_s)
        merged: List[List[float]] = []
        for interval in raw_intervals:
            if not merged:
                merged.append(interval)
            else:
                prev = merged[-1]
                gap_between = interval[0] - prev[1]
                if gap_between <= self.config.merge_gap_s:
                    prev[1] = interval[1]
                    prev[2] += interval[2]
                    prev[3] += interval[3]
                    prev[4] = min(prev[4], interval[4])
                else:
                    merged.append(interval)

        # 2. Aşama: Minimum süre filtresi (min_gap_duration_s)
        valid_intervals: List[Tuple[float, float, float, float]] = []
        for item in merged:
            start, end, sum_score, count, min_sc = item[0], item[1], item[2], item[3], item[4]
            duration = end - start
            if duration >= self.config.min_gap_duration_s:
                mean_sc = sum_score / max(1, count)
                valid_intervals.append((round(start, 2), round(end, 2), round(mean_sc, 1), round(min_sc, 1)))

        return valid_intervals

    def match_with_lecture(
        self, focus_samples: List[FocusSample], lecture: Lecture
    ) -> List[GapWindow]:
        smoothed = self.smooth_focus_samples(focus_samples)
        intervals = self.detect_low_focus_intervals(smoothed)

        gap_windows: List[GapWindow] = []

        for int_start, int_end, mean_focus, min_focus in intervals:
            for idx, seg in enumerate(lecture.segments):
                overlap_start = max(int_start, seg.start_time)
                overlap_end = min(int_end, seg.end_time)

                if overlap_end > overlap_start:
                    overlap_duration = overlap_end - overlap_start
                    seg_duration = seg.duration
                    coverage = overlap_duration / seg_duration if seg_duration > 0 else 0.0

                    if coverage >= self.config.min_segment_coverage or overlap_duration >= self.config.min_gap_duration_s:
                        missed_text = self._extract_approx_missed_transcript(
                            seg, overlap_start, overlap_end
                        )

                        gap_windows.append(
                            GapWindow(
                                start_time=round(overlap_start, 2),
                                end_time=round(overlap_end, 2),
                                topic=seg.topic,
                                segment_index=idx,
                                mean_focus=mean_focus,
                                min_focus=min_focus,
                                coverage=round(min(1.0, coverage), 2),
                                missed_transcript=missed_text,
                            )
                        )

        return gap_windows

    def _extract_approx_missed_transcript(
        self, segment: TranscriptSegment, start: float, end: float
    ) -> str:
        total_dur = segment.duration
        if total_dur <= 0 or not segment.transcript:
            return segment.transcript

        words = segment.transcript.split()
        if not words:
            return segment.transcript

        frac_start = max(0.0, (start - segment.start_time) / total_dur)
        frac_end = min(1.0, (end - segment.start_time) / total_dur)

        idx_start = int(np.floor(frac_start * len(words)))
        idx_end = int(np.ceil(frac_end * len(words)))

        idx_end = max(idx_end, idx_start + 1)
        sub_words = words[idx_start:idx_end]
        
        if len(sub_words) < 5:
            return segment.transcript

        return " ".join(sub_words)
