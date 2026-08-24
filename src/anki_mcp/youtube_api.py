import re

from youtube_transcript_api import (
    FetchedTranscript,
    NoTranscriptFound,
    TranscriptsDisabled,
    YouTubeTranscriptApi,
)

from anki_mcp.models import OutlineSegment, TranscriptSegment, YouTubeVideoData


def extract_video_id(url: str) -> str | None:
    """Extract the YouTube video ID from standart and shortened URLs"""
    pattern = r"(?:v=|\/)([0-9A-Za-z_-]{11}).*"
    match = re.search(pattern, url)
    return match.group(1) if match else None


def format_seconds(seconds: float) -> str:
    """e.g 300Seconds -> 05:00"""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"


def get_youtube_data(url: str, target_language: str = "en") -> YouTubeVideoData | None:
    video_id = extract_video_id(url)
    if not video_id:
        raise ValueError(f"Invalid YouTube URL. ID was not found: {url}")

    ytt_api = YouTubeTranscriptApi()

    try:
        transcript_list = ytt_api.list(video_id)
    except TranscriptsDisabled as e:
        raise Exception(
            "For the given YouTube Video Transcripts are completely disabled"
        ) from e
    except Exception as e:
        raise Exception(f"Error when fetching Transcripts List: {str(e)}") from e

    is_translated = False

    try:
        transcript = transcript_list.find_transcript([target_language])
    except NoTranscriptFound as e:
        available_transcripts = list(transcript_list)
        if not available_transcripts:
            raise Exception("There are no useful Transcripts for this video") from e

        base_transcript = available_transcripts[0]
        if not base_transcript.is_translatable:
            raise Exception(
                f"The Transcript in {base_transcript.language} does not allow API Translation."
            ) from e

        transcript = base_transcript.translate(target_language)
        is_translated = True

    raw_data: FetchedTranscript = transcript.fetch()
    actual_language = transcript.language
    full_transcript: list[TranscriptSegment] = []
    outline: list[OutlineSegment] = []

    interval_seconds = 300  # 5 Minutes
    current_interval = 0

    for snippet in raw_data.snippets:
        start = snippet.start
        end = snippet.start + snippet.duration
        text = snippet.text.strip()

        full_transcript.append(
            TranscriptSegment(start_time=start, end_time=end, text=text)
        )

        if start >= current_interval * interval_seconds:
            outline.append(
                OutlineSegment(
                    timestamp_seconds=start,
                    formatted_time=format_seconds(start),
                    text_snippet=text,
                )
            )
            current_interval += 1

    total_length = full_transcript[-1].end_time if full_transcript else 0.0

    return YouTubeVideoData(
        video_id=video_id,
        langauge=actual_language,
        is_translated=is_translated,
        total_length_seconds=total_length,
        outline=outline,
        transcript=full_transcript,
    )
