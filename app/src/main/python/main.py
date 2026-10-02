import os
import re
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    VideoUnavailable,
    TranscriptsDisabled,
    NoTranscriptFound,
    RequestBlocked,
    IpBlocked
)


def video_id(url):
    if not url:
        return None

    cleaned = re.sub(r"\s+", "", str(url).strip())

    match = re.search(
        r"(?:v=|\/|youtu\.be\/|embed\/|shorts\/|^)([a-zA-Z0-9_-]{11})(?:[?&/#]|$)",
        cleaned
    )
    if match:
        return match.group(1)

    parsed = urlparse(cleaned)

    if parsed.hostname in ("youtu.be", "www.youtu.be"):
        return parsed.path.strip("/")

    if parsed.hostname and "youtube.com" in parsed.hostname:
        query_id = parse_qs(parsed.query).get("v")
        if query_id:
            return query_id[0]

        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] in ("shorts", "embed", "live"):
            return parts[1]

    return None


def fetch_transcript_and_duration(vid):
    api = YouTubeTranscriptApi()

    fetched = None
    fetch_error = None

    try:
        ts = api.list(vid)
        try:
            t = ts.find_transcript(["id", "en"])
        except Exception:
            try:
                t = next(iter(ts))
            except Exception:
                t = None

        if t is not None:
            fetched = t.fetch()
    except (RequestBlocked, IpBlocked):
        raise RuntimeError(
            "YouTube membatasi/memblokir permintaan dari IP server cloud emulator. "
            "Gunakan opsi tempel transcript SRT di bawah, atau uji APK di HP fisik Anda."
        )
    except VideoUnavailable:
        raise RuntimeError("Video YouTube ini tidak tersedia (telah dihapus atau ID video salah).")
    except TranscriptsDisabled:
        raise RuntimeError("Pembuat video menonaktifkan transcript/subtitle untuk video ini.")
    except Exception as e:
        fetch_error = e

    if fetched is None:
        for languages in (["id", "en"], ["en", "id"], ["en"], ["id"]):
            try:
                fetched = api.fetch(vid, languages=languages)
                if fetched:
                    break
            except (RequestBlocked, IpBlocked):
                raise RuntimeError(
                    "YouTube memblokir permintaan dari IP cloud ini. "
                    "Silakan tempel langsung transcript SRT di kotak bawah."
                )
            except VideoUnavailable:
                raise RuntimeError("Video YouTube ini tidak tersedia atau telah dihapus.")
            except Exception as e:
                fetch_error = e
                continue

    if fetched is None:
        err_msg = str(fetch_error) if fetch_error else "Tidak ada subtitle yang tersedia"
        raise RuntimeError(f"Transcript YouTube tidak tersedia: {err_msg}")

    lines = []
    max_end = 0.0

    for index, item in enumerate(fetched, 1):
        start = float(item.start)
        duration = float(item.duration)
        end = start + duration
        text = item.text.strip()

        if not text or end <= start:
            continue

        if end > max_end:
            max_end = end

        def timestamp(seconds):
            total_ms = round(seconds * 1000)
            hours, remainder = divmod(total_ms, 3600000)
            minutes, remainder = divmod(remainder, 60000)
            seconds, milliseconds = divmod(remainder, 1000)
            return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

        lines.extend([
            str(index),
            f"{timestamp(start)} --> {timestamp(end)}",
            text,
            ""
        ])

    if not lines:
        raise RuntimeError("Transcript kosong.")

    return "\n".join(lines), round(max_end, 3)


def fetch_audio(vid, url, cache_dir):
    cache_path = Path(cache_dir)
    audio_file = cache_path / f"video_{vid}_audio.m4a"

    if audio_file.exists() and audio_file.stat().st_size > 0:
        return str(audio_file), None

    download_success = False
    error_msg = ""
    media_duration = None

    try:
        import yt_dlp
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': str(cache_path / f"video_{vid}_audio.%(ext)s"),
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            target_url = url if url else f"https://www.youtube.com/watch?v={vid}"
            info_dict = ydl.extract_info(target_url, download=True)
            if info_dict:
                raw_duration = info_dict.get('duration')
                if raw_duration is not None:
                    media_duration = float(raw_duration)

        for ext in ["m4a", "webm", "opus", "mp3", "aac"]:
            candidate = cache_path / f"video_{vid}_audio.{ext}"
            if candidate.exists() and candidate.stat().st_size > 0:
                if candidate != audio_file:
                    candidate.rename(audio_file)
                download_success = True
                break
    except Exception as e:
        error_msg = str(e)

    if not download_success or not audio_file.exists() or audio_file.stat().st_size == 0:
        raise RuntimeError(f"Gagal mengunduh/mengambil audio untuk video ID '{vid}': {error_msg or 'Audio tidak tersedia'}")

    return str(audio_file), media_duration


def get_video_contract(url, cache_dir=None):
    vid = video_id(url)
    if not vid:
        raise ValueError("URL YouTube tidak valid atau ID video tidak ditemukan.")

    if cache_dir is None:
        import tempfile
        cache_dir = tempfile.gettempdir()

    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)

    contract_file = cache_path / f"video_{vid}_contract.json"

    if contract_file.exists():
        try:
            data = json.loads(contract_file.read_text(encoding="utf-8"))
            cached_vid = data.get("video_id")
            cached_transcript = data.get("transcript")
            cached_audio = data.get("audio_path")

            if (
                cached_vid == vid
                and cached_transcript
                and cached_audio
                and os.path.exists(cached_audio)
                and os.path.getsize(cached_audio) > 0
            ):
                return data
            else:
                contract_file.unlink(missing_ok=True)
        except Exception:
            contract_file.unlink(missing_ok=True)

    transcript, transcript_max_end = fetch_transcript_and_duration(vid)
    audio_path, media_duration = fetch_audio(vid, url, cache_dir)

    final_duration = media_duration if media_duration is not None else transcript_max_end

    contract = {
        "video_id": vid,
        "transcript": transcript,
        "audio_path": audio_path,
        "duration": final_duration,
        "transcript_max_end": transcript_max_end,
    }

    try:
        contract_file.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    return contract


def get_video_contract_json(url, cache_dir=None):
    contract = get_video_contract(url, cache_dir)
    return json.dumps(contract, ensure_ascii=False)


def transcript_srt(url):
    vid = video_id(url)
    if not vid:
        raise ValueError("URL YouTube tidak valid atau ID video tidak ditemukan.")
    transcript, _ = fetch_transcript_and_duration(vid)
    return transcript


def status():
    return "Clipper Python core ready"
