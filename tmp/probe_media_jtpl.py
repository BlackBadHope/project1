from __future__ import annotations

import html
import json
import re
import traceback
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests

VIDEO_ID = "jTPLlKbqTuM"
VIDEO_URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"
OUT = Path("out")
OUT.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
    "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
}


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")[:120]


def save_json(name: str, value: Any) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def request_record(name: str, url: str, params: dict[str, str] | None = None) -> tuple[requests.Response | None, Any]:
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=45, allow_redirects=True)
        ctype = r.headers.get("content-type", "")
        body: Any
        if "json" in ctype:
            try:
                body = r.json()
            except Exception:
                body = r.text
        else:
            body = r.text
        save_json(
            f"probe_{safe_name(name)}.json",
            {
                "requested_url": url,
                "final_url": r.url,
                "status": r.status_code,
                "headers": dict(r.headers),
                "body": body,
            },
        )
        return r, body
    except Exception as exc:
        save_json(
            f"probe_{safe_name(name)}.json",
            {"requested_url": url, "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()},
        )
        return None, None


def collect_streams(value: Any, origin: str = "") -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        # Common Piped/Invidious stream containers.
        for key in ("audioStreams", "adaptiveFormats", "formatStreams", "streams"):
            seq = value.get(key)
            if isinstance(seq, list):
                for item in seq:
                    if not isinstance(item, dict):
                        continue
                    url = item.get("url") or item.get("downloadUrl") or item.get("src")
                    mime = str(item.get("mimeType") or item.get("type") or item.get("format") or "")
                    audio_like = (
                        key == "audioStreams"
                        or "audio" in mime.lower()
                        or item.get("audioTrackId") is not None
                        or item.get("audioQuality") is not None
                    )
                    if url and audio_like:
                        found.append({"url": urljoin(origin, str(url)), "origin": origin, "container": key, **item})
        for child in value.values():
            found.extend(collect_streams(child, origin))
    elif isinstance(value, list):
        for child in value:
            found.extend(collect_streams(child, origin))
    return found


def extract_html_media(page: str, origin: str) -> list[dict[str, Any]]:
    page = html.unescape(page)
    candidates: list[str] = []
    patterns = [
        r'<(?:audio|video|source)[^>]+src=["\']([^"\']+)',
        r'<meta[^>]+property=["\']og:(?:audio|video)(?::url)?["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:(?:audio|video)(?::url)?["\']',
        r'"(?:audioUrl|videoUrl|downloadUrl|contentUrl|streamUrl|url)"\s*:\s*"(https?[^"\\]+(?:\\.[^"\\]*)*)"',
    ]
    for pattern in patterns:
        for match in re.findall(pattern, page, flags=re.I):
            candidates.append(match.replace("\\u0026", "&").replace("\\/", "/"))
    out = []
    for candidate in candidates:
        url = urljoin(origin, candidate)
        if any(x in url.lower() for x in (".m4a", ".mp3", ".webm", ".mp4", "googlevideo", "/videoplayback", "/audio")):
            out.append({"url": url, "origin": origin, "container": "html"})
    return out


probes: list[tuple[str, str, dict[str, str] | None]] = []

piped_instances = [
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.tokhmi.xyz",
    "https://pipedapi.moomoo.me",
    "https://pipedapi.syncpundit.io",
    "https://api-piped.mha.fi",
    "https://piped-api.garudalinux.org",
    "https://pipedapi.rivo.lol",
    "https://pipedapi.leptons.xyz",
]
for base in piped_instances:
    probes.append((f"piped_{base}", f"{base}/streams/{VIDEO_ID}", None))

invidious_instances = [
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de",
    "https://yt.chocolatemoo53.com",
    "https://inv.thepixora.com",
    "https://yewtu.be",
    "https://invidious.private.coffee",
    "https://iv.ggtyler.dev",
]
for base in invidious_instances:
    probes.append((f"invidious_{base}", f"{base}/api/v1/videos/{VIDEO_ID}", {"local": "true"}))

other_pages = [
    ("tgch_video", f"https://tgch.nl/ssternenko/video/{VIDEO_ID}"),
    ("qna_center", f"https://video.qna.center/youtube/{VIDEO_ID}"),
    ("summynews_path", f"https://summynews.com/{VIDEO_ID}"),
    ("summynews_query", "https://summynews.com/"),
    ("twooutube", f"https://2outube.com/watch?v={VIDEO_ID}"),
    ("quicktranscript", f"https://quicktranscript.ai/transcript/{VIDEO_ID}"),
]
for name, url in other_pages:
    params = {"v": VIDEO_ID} if name == "summynews_query" else None
    probes.append((name, url, params))

all_streams: list[dict[str, Any]] = []
for name, url, params in probes:
    response, body = request_record(name, url, params)
    if response is None:
        continue
    if isinstance(body, (dict, list)):
        all_streams.extend(collect_streams(body, response.url))
    elif isinstance(body, str):
        all_streams.extend(extract_html_media(body, response.url))

# Dynamic official instance lists, useful if the static candidates are stale.
for name, url in [
    ("invidious_instances", "https://api.invidious.io/instances.json"),
    ("piped_instances", "https://piped.video/api/v1/instances"),
]:
    response, body = request_record(name, url)
    if response is None or not isinstance(body, list):
        continue
    dynamic_bases: list[str] = []
    if name == "invidious_instances":
        for item in body:
            if isinstance(item, list) and len(item) >= 2 and isinstance(item[1], dict):
                uri = item[1].get("uri")
                api = item[1].get("api")
                if uri and api:
                    dynamic_bases.append(str(uri).rstrip("/"))
    else:
        for item in body:
            if isinstance(item, dict) and item.get("api_url"):
                dynamic_bases.append(str(item["api_url"]).rstrip("/"))
    for idx, base in enumerate(dynamic_bases[:20]):
        if name == "invidious_instances":
            endpoint = f"{base}/api/v1/videos/{VIDEO_ID}"
            params = {"local": "true"}
        else:
            endpoint = f"{base}/streams/{VIDEO_ID}"
            params = None
        r, b = request_record(f"dynamic_{name}_{idx}_{base}", endpoint, params)
        if r is not None and isinstance(b, (dict, list)):
            all_streams.extend(collect_streams(b, r.url))

# Deduplicate and rank likely audio streams by bitrate/size.
dedup: dict[str, dict[str, Any]] = {}
for item in all_streams:
    url = str(item.get("url", ""))
    if url and url not in dedup:
        dedup[url] = item
all_streams = list(dedup.values())

def bitrate(item: dict[str, Any]) -> int:
    for key in ("bitrate", "averageBitrate", "audioBitrate"):
        try:
            return int(item.get(key) or 0)
        except Exception:
            pass
    return 0

all_streams.sort(key=lambda x: (bitrate(x) <= 0, bitrate(x) or 10**12))
save_json("probe_stream_candidates.json", all_streams)

# Download the first working audio candidate, preferring the lowest positive bitrate.
download_log: list[dict[str, Any]] = []
for idx, item in enumerate(all_streams[:30]):
    url = str(item.get("url", ""))
    try:
        with requests.get(url, headers=HEADERS, timeout=90, stream=True, allow_redirects=True) as r:
            ctype = r.headers.get("content-type", "")
            length = int(r.headers.get("content-length") or 0)
            record = {"index": idx, "url": url, "status": r.status_code, "content_type": ctype, "content_length": length, "final_url": r.url}
            if r.status_code != 200 or ("audio" not in ctype.lower() and "video" not in ctype.lower() and "octet-stream" not in ctype.lower()):
                download_log.append(record)
                continue
            suffix = ".m4a" if "mp4" in ctype.lower() else ".webm" if "webm" in ctype.lower() else ".bin"
            target = OUT / f"audio_candidate{suffix}"
            total = 0
            with target.open("wb") as f:
                for chunk in r.iter_content(1024 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > 120 * 1024 * 1024:
                        raise RuntimeError("stream exceeds 120 MiB safety limit")
                    f.write(chunk)
            record["downloaded"] = total
            record["target"] = target.name
            download_log.append(record)
            break
    except Exception as exc:
        download_log.append({"index": idx, "url": url, "error": f"{type(exc).__name__}: {exc}"})

save_json("probe_download_log.json", download_log)
print(json.dumps({"probes": len(probes), "streams": len(all_streams), "download_log": download_log[-3:]}, ensure_ascii=False))
