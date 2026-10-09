import asyncio
import re
from dataclasses import dataclass
from typing import Annotated

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field
from youtube_transcript_api import NoTranscriptFound, TranscriptsDisabled, YouTubeTranscriptApi

from anki_mcp.server import WEB_READ, tool

MAX_TRANSCRIPT_CHARS = 8000
MAX_CACHED_VIDEOS = 8
OUTLINE_STEP_SECONDS = 90


@dataclass
class Video:
    segments: list[tuple[float, float, str]]  # (start, end, text)
    translated: bool


class TimeInterval(BaseModel):
    start_sec: int = Field(description="Start time in seconds")
    end_sec: int = Field(description="End time in seconds")


_videos: dict[tuple[str, str], Video] = {}


def _timestamp(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _fetch(url: str, language: str) -> Video:
    match = re.search(r"(?:v=|/)([0-9A-Za-z_-]{11})", url)
    if not match:
        raise ToolError(f"Invalid YouTube URL: {url}")
    try:
        transcripts = YouTubeTranscriptApi().list(match.group(1))
    except TranscriptsDisabled:
        raise ToolError("Transcripts are disabled for this video.") from None

    translated = False
    try:
        transcript = transcripts.find_transcript([language])
    except NoTranscriptFound:
        available = list(transcripts)
        if not available:
            raise ToolError("This video has no transcripts.") from None
        if not available[0].is_translatable:
            raise ToolError(f"The {available[0].language} transcript cannot be translated.") from None
        transcript, translated = available[0].translate(language), True

    snippets = transcript.fetch().snippets
    return Video([(s.start, s.start + s.duration, s.text.strip()) for s in snippets], translated)


def _outline(video: Video) -> str:
    lines, bucket = [], -1
    for i, (start, _, _) in enumerate(video.segments):
        if int(start // OUTLINE_STEP_SECONDS) == bucket:
            continue
        bucket = int(start // OUTLINE_STEP_SECONDS)
        words = " ".join(t for _, _, t in video.segments[i : i + 15]).split()[:25]
        lines.append(f"[{_timestamp(start)}] {' '.join(words)}")
    return "\n".join(lines)


@tool("YouTube transcript", WEB_READ)
async def youtube_transcript(
    url: str,
    intervals: Annotated[list[TimeInterval] | None, Field(max_length=30)] = None,
    language: Annotated[str, Field(min_length=2, description="Transcript language code, e.g. 'de'")] = "en",
) -> str:
    """Read the transcript of a YouTube video. Long videos return a timestamped outline; call again with 'intervals' to read the parts that matter."""
    key = (url, language)
    if key not in _videos:
        if len(_videos) >= MAX_CACHED_VIDEOS:
            _videos.pop(next(iter(_videos)))
        _videos[key] = await asyncio.to_thread(_fetch, url, language)
    video = _videos[key]
    note = "\n\n(machine-translated)" if video.translated else ""

    if intervals:
        blocks = []
        for iv in intervals:
            text = " ".join(t for start, end, t in video.segments if start <= iv.end_sec and end >= iv.start_sec)
            if text:
                blocks.append(f"[{_timestamp(iv.start_sec)}-{_timestamp(iv.end_sec)}]\n{text}")
        return ("\n\n".join(blocks) or "No text in these intervals.") + note

    full = " ".join(t for _, _, t in video.segments)
    if len(full) <= MAX_TRANSCRIPT_CHARS:
        return full + note
    return "Transcript too long. Call again with 'intervals' picked from this outline:\n\n" + _outline(video) + note
