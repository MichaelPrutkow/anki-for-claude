import asyncio
from typing import Annotated

from mcp.server import MCPServer
from pydantic import Field

from anki_mcp.sources.youtube import (
    TimeInterval,
    YouTubeVideoData,
    extract_full_transcript,
    extract_outline,
    extract_segments,
    get_youtube_data,
)
from anki_mcp.tools.annotations import WEB_READ

MAX_TRANSCRIPT_CHARS = 8000
MAX_CACHED_VIDEOS = 8

_videos: dict[tuple[str, str], YouTubeVideoData] = {}


async def youtube_transcript(
    url: str,
    intervals: Annotated[list[TimeInterval] | None, Field(max_length=30)] = None,
    language: Annotated[
        str, Field(min_length=2, description="Transcript language code, e.g. 'de'")
    ] = "en",
) -> str:
    """Read the transcript of a YouTube video. Long videos return a timestamped outline; call again with 'intervals' to read the parts that matter."""
    key = (url, language)
    video = _videos.get(key)
    if video is None:
        video = await asyncio.to_thread(get_youtube_data, url, language)
        if len(_videos) >= MAX_CACHED_VIDEOS:
            _videos.pop(next(iter(_videos)))
        _videos[key] = video

    if intervals:
        return extract_segments(video, intervals)
    full = extract_full_transcript(video)
    if len(full) <= MAX_TRANSCRIPT_CHARS:
        return full
    return (
        "Transcript too long. Call again with 'intervals' picked from this outline:\n\n"
        + extract_outline(video)
    )


def register(mcp: MCPServer) -> None:
    mcp.add_tool(
        youtube_transcript,
        title="YouTube transcript",
        annotations=WEB_READ,
        structured_output=False,
    )
