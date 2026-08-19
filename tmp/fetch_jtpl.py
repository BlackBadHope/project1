from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Any

import requests

VIDEO_ID = "jTPLlKbqTuM"
VIDEO_URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"
OUT = Path("out")
OUT.mkdir(parents=True, exist_ok=True)


def dump(name: str, value: Any) -> None:
    (OUT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def normalize_snippet(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return {
            "text": item.get("text", ""),
            "start": item.get("start"),
            "duration": item.get("duration"),
        }
    return {
        "text": getattr(item, "text", ""),
        "start": getattr(item, "start", None),
        "duration": getattr(item, "duration", None),
    }


errors: list[dict[str, str]] = []

# 1. Official caption-track access through youtube-transcript-api.
try:
    from youtube_transcript_api import YouTubeTranscriptApi

    if hasattr(YouTubeTranscriptApi, "list_transcripts"):
        transcript_list = YouTubeTranscriptApi.list_transcripts(VIDEO_ID)
    else:
        transcript_list = YouTubeTranscriptApi().list(VIDEO_ID)

    index: list[dict[str, Any]] = []
    for n, track in enumerate(transcript_list):
        code = getattr(track, "language_code", f"track{n}")
        generated = bool(getattr(track, "is_generated", False))
        entry = {
            "language": getattr(track, "language", None),
            "language_code": code,
            "is_generated": generated,
            "is_translatable": bool(getattr(track, "is_translatable", False)),
            "translation_languages": getattr(track, "translation_languages", None),
        }
        try:
            snippets = track.fetch()
            normalized = [normalize_snippet(x) for x in snippets]
            filename = f"youtube_transcript_api_{n}_{code}_{'asr' if generated else 'manual'}.json"
            dump(filename, normalized)
            entry["file"] = filename
            entry["segments"] = len(normalized)
        except Exception as exc:
            entry["fetch_error"] = f"{type(exc).__name__}: {exc}"
        index.append(entry)
    dump("youtube_transcript_api_index.json", index)
except Exception as exc:
    errors.append(
        {
            "source": "youtube_transcript_api",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }
    )

# 2. Public transcript endpoints as independent fallbacks.
endpoints = [
    ("getvideotranscript", "https://getvideotranscript.com/api/youtube", {"video_id": VIDEO_ID}),
    ("tubetext_timestamps", "https://tubetext.vercel.app/youtube/transcript-with-timestamps", {"video_id": VIDEO_ID}),
    ("tubetext_plain", "https://tubetext.vercel.app/youtube/transcript", {"video_id": VIDEO_ID}),
    ("youtube_oembed", "https://www.youtube.com/oembed", {"url": VIDEO_URL, "format": "json"}),
    ("youtube_timedtext_tracks", "https://www.youtube.com/api/timedtext", {"type": "list", "v": VIDEO_ID}),
]

headers = {"User-Agent": "Mozilla/5.0 transcript-research/1.0"}
for name, url, params in endpoints:
    try:
        response = requests.get(url, params=params, headers=headers, timeout=60)
        record = {
            "url": response.url,
            "status": response.status_code,
            "headers": dict(response.headers),
            "text": response.text,
        }
        dump(f"endpoint_{name}.json", record)
    except Exception as exc:
        errors.append(
            {
                "source": name,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }
        )

dump("errors.json", errors)
print(json.dumps({"video_id": VIDEO_ID, "files": sorted(p.name for p in OUT.iterdir())}, ensure_ascii=False))
