"""
Veri sozlesmeleri (Data Contracts)
Pydantic v1 & v2 tam uyumlu
"""
from __future__ import annotations
from typing import List, Optional
import pydantic

PYDANTIC_V2 = int(pydantic.__version__.split('.')[0]) >= 2

if PYDANTIC_V2:
    from pydantic import BaseModel, Field, field_validator, model_validator

    class TranscriptSegment(BaseModel):
        start_time: float = Field(..., ge=0)
        end_time: float = Field(..., gt=0)
        topic: str = Field(..., min_length=1)
        transcript: str = Field(..., min_length=1)

        @model_validator(mode="after")
        def _check_interval(self) -> TranscriptSegment:
            if self.end_time <= self.start_time:
                raise ValueError("end_time start_time'dan buyuk olmali")
            return self

        @property
        def duration(self) -> float:
            return self.end_time - self.start_time

    class Lecture(BaseModel):
        lecture_id: str
        title: str
        subject: str
        grade_level: Optional[str] = None
        segments: List[TranscriptSegment]

        @field_validator("segments")
        @classmethod
        def _check_ordering(cls, segs: List[TranscriptSegment]) -> List[TranscriptSegment]:
            if not segs:
                raise ValueError("En az bir segment olmali")
            for prev, curr in zip(segs, segs[1:]):
                if curr.start_time < prev.end_time:
                    raise ValueError(f"Segmentler cakısıyor: {prev.topic} ile {curr.topic}")
            return segs

        @property
        def duration(self) -> float:
            return self.segments[-1].end_time

        @property
        def full_transcript(self) -> str:
            lines = [f"[{s.topic}]\n{s.transcript}" for s in self.segments]
            return "\n\n".join(lines)

    class FocusSample(BaseModel):
        timestamp: float = Field(..., ge=0)
        focus_score: float = Field(..., ge=0, le=100)

    class GapWindow(BaseModel):
        start_time: float
        end_time: float
        topic: str
        segment_index: int
        mean_focus: float = Field(..., ge=0, le=100)
        min_focus: float = Field(..., ge=0, le=100)
        coverage: float = Field(..., ge=0, le=1)
        missed_transcript: str

        @property
        def duration(self) -> float:
            return self.end_time - self.start_time

    class QuizQuestion(BaseModel):
        question: str
        options: List[str] = Field(..., min_length=2, max_length=5)
        correct_index: int = Field(..., ge=0)
        explanation: str

        @model_validator(mode="after")
        def _check_answer(self) -> QuizQuestion:
            if self.correct_index >= len(self.options):
                raise ValueError("correct_index secenek sayisini asiyor")
            return self

    class RecoveryCard(BaseModel):
        topic: str
        gap_start: float
        gap_end: float
        summary: str
        key_points: List[str] = Field(default_factory=list)
        questions: List[QuizQuestion] = Field(..., min_length=2, max_length=2)

    class NoteSection(BaseModel):
        topic: str
        content: str
        key_terms: List[str] = Field(default_factory=list)

    class LectureNotes(BaseModel):
        title: str
        summary: str
        sections: List[NoteSection]
        board_solutions: List[str] = Field(default_factory=list)
        approved: bool = False

else:
    from pydantic import BaseModel, Field, root_validator, validator

    class TranscriptSegment(BaseModel):
        start_time: float = Field(..., ge=0)
        end_time: float = Field(..., gt=0)
        topic: str = Field(..., min_length=1)
        transcript: str = Field(..., min_length=1)

        @root_validator
        def _check_interval(cls, values):
            st = values.get("start_time")
            et = values.get("end_time")
            if st is not None and et is not None and et <= st:
                raise ValueError("end_time start_time'dan buyuk olmali")
            return values

        @property
        def duration(self) -> float:
            return self.end_time - self.start_time

    class Lecture(BaseModel):
        lecture_id: str
        title: str
        subject: str
        grade_level: Optional[str] = None
        segments: List[TranscriptSegment]

        @validator("segments")
        def _check_ordering(cls, segs: List[TranscriptSegment]):
            if not segs:
                raise ValueError("En az bir segment olmali")
            for prev, curr in zip(segs, segs[1:]):
                if curr.start_time < prev.end_time:
                    raise ValueError(f"Segmentler cakısıyor: {prev.topic} ile {curr.topic}")
            return segs

        @property
        def duration(self) -> float:
            return self.segments[-1].end_time

        @property
        def full_transcript(self) -> str:
            lines = [f"[{s.topic}]\n{s.transcript}" for s in self.segments]
            return "\n\n".join(lines)

    class FocusSample(BaseModel):
        timestamp: float = Field(..., ge=0)
        focus_score: float = Field(..., ge=0, le=100)

    class GapWindow(BaseModel):
        start_time: float
        end_time: float
        topic: str
        segment_index: int
        mean_focus: float = Field(..., ge=0, le=100)
        min_focus: float = Field(..., ge=0, le=100)
        coverage: float = Field(..., ge=0, le=1)
        missed_transcript: str

        @property
        def duration(self) -> float:
            return self.end_time - self.start_time

    class QuizQuestion(BaseModel):
        question: str
        options: List[str] = Field(..., min_items=2, max_items=5)
        correct_index: int = Field(..., ge=0)
        explanation: str

        @root_validator
        def _check_answer(cls, values):
            opts = values.get("options") or []
            c_idx = values.get("correct_index", 0)
            if c_idx >= len(opts):
                raise ValueError("correct_index secenek sayisini asiyor")
            return values

    class RecoveryCard(BaseModel):
        topic: str
        gap_start: float
        gap_end: float
        summary: str
        key_points: List[str] = Field(default_factory=list)
        questions: List[QuizQuestion] = Field(..., min_items=2, max_items=2)

    class NoteSection(BaseModel):
        topic: str
        content: str
        key_terms: List[str] = Field(default_factory=list)

    class LectureNotes(BaseModel):
        title: str
        summary: str
        sections: List[NoteSection]
        board_solutions: List[str] = Field(default_factory=list)
        approved: bool = False


# Pydantic v1 / v2 uyumluluk helper'i
if not PYDANTIC_V2:
    for cls in [TranscriptSegment, Lecture, FocusSample, GapWindow, QuizQuestion, RecoveryCard, NoteSection, LectureNotes]:
        cls.model_validate = classmethod(lambda c, obj: c.parse_obj(obj))
        cls.model_dump = lambda self, **kwargs: self.dict(**kwargs)
        cls.model_dump_json = lambda self, **kwargs: self.json(**kwargs)
