from typing import Any

from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    query: str
    total_found: int
    note_ids: list[int]
    notes: list[dict[str, Any]] = []


class NoteInput(BaseModel):
    fields: dict[str, str] = Field(
        description="Keys must match the note type's field names exactly"
    )
    tags: list[str] = Field(default=[], description="Extra tags for this note only")


class AddResult(BaseModel):
    batch_id: str | None
    note_count: int
    note_ids: list[int] = []
    failed_indices: list[int] = []


class TranscriptSegment(BaseModel):
    start_time: float
    end_time: float
    text: str


class OutlineSegment(BaseModel):
    timestamp_seconds: float
    formatted_time: str
    text_snippet: str


class YouTubeVideoData(BaseModel):
    video_id: str
    langauge: str
    is_translated: bool
    total_length_seconds: float
    outline: list[OutlineSegment]
    transcript: list[TranscriptSegment]


class TimeInterval(BaseModel):
    start_sec: int = Field(description="Start Time in Seconds")
    end_sec: int = Field(description="End Time in Seconds")
