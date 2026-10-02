import sys
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure python modules in app/src/main/python are in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app" / "src" / "main" / "python"))

import main
import prefilter


def test_contract_structure(tmp_path):
    video_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    fake_vid = "dQw4w9WgXcQ"

    fake_fetched = [
        MagicMock(start=0.0, duration=5.0, text="Hello world"),
        MagicMock(start=5.0, duration=10.0, text="This is a test video transcript"),
    ]

    mock_api = MagicMock()
    mock_api.list.return_value.find_transcript.return_value.fetch.return_value = fake_fetched

    fake_audio = tmp_path / f"video_{fake_vid}_audio.m4a"
    fake_audio.write_bytes(b"dummy audio content")

    with patch.object(main, "YouTubeTranscriptApi", return_value=mock_api), \
         patch.object(main, "fetch_audio", return_value=str(fake_audio)):

        contract = main.get_video_contract(video_url, cache_dir=str(tmp_path))

        assert contract["video_id"] == fake_vid
        assert "Hello world" in contract["transcript"]
        assert contract["audio_path"] == str(fake_audio)
        assert contract["duration"] == 15.0
        assert Path(contract["audio_path"]).exists()


def test_timeline_unshifted(tmp_path):
    video_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    fake_vid = "dQw4w9WgXcQ"

    fake_fetched = [
        MagicMock(start=0.0, duration=10.0, text="Start at zero"),
        MagicMock(start=10.0, duration=20.0, text="Middle section"),
        MagicMock(start=30.0, duration=10.0, text="End section"),
    ]

    mock_api = MagicMock()
    mock_api.list.return_value.find_transcript.return_value.fetch.return_value = fake_fetched

    fake_audio = tmp_path / f"video_{fake_vid}_audio.m4a"
    fake_audio.write_bytes(b"audio")

    with patch.object(main, "YouTubeTranscriptApi", return_value=mock_api), \
         patch.object(main, "fetch_audio", return_value=str(fake_audio)):

        contract = main.get_video_contract(video_url, cache_dir=str(tmp_path))
        transcript_str = contract["transcript"]

        assert "00:00:00,000 --> 00:00:10,000" in transcript_str
        assert "00:00:10,000 --> 00:00:30,000" in transcript_str
        assert "00:00:30,000 --> 00:00:40,000" in transcript_str

        segments = prefilter.parse(transcript_str)
        assert len(segments) == 3
        assert segments[0]["start"] == 0.0
        assert segments[1]["start"] == 10.0
        assert segments[2]["start"] == 30.0


def test_cache_does_not_mix_videos_and_rejects_incomplete_cache(tmp_path):
    vid1 = "video_id_01"
    vid2 = "video_id_02"
    url1 = f"https://www.youtube.com/watch?v={vid1}"
    url2 = f"https://www.youtube.com/watch?v={vid2}"

    audio1 = tmp_path / f"video_{vid1}_audio.m4a"
    audio1.write_bytes(b"audio1")

    audio2 = tmp_path / f"video_{vid2}_audio.m4a"
    audio2.write_bytes(b"audio2")

    mock_api = MagicMock()
    mock_api.list.return_value.find_transcript.return_value.fetch.return_value = [
        MagicMock(start=0.0, duration=5.0, text="Vid transcript")
    ]

    with patch.object(main, "YouTubeTranscriptApi", return_value=mock_api), \
         patch.object(main, "fetch_audio", side_effect=lambda v, u, c: str(tmp_path / f"video_{v}_audio.m4a")):

        c1 = main.get_video_contract(url1, cache_dir=str(tmp_path))
        c2 = main.get_video_contract(url2, cache_dir=str(tmp_path))

        assert c1["video_id"] == vid1
        assert c2["video_id"] == vid2
        assert c1["video_id"] != c2["video_id"]

        contract1_file = tmp_path / f"video_{vid1}_contract.json"
        assert contract1_file.exists()

        # Simulate transcript-only / missing audio file
        audio1.unlink()

        def recreate_audio(v, u, c):
            p = tmp_path / f"video_{v}_audio.m4a"
            p.write_bytes(b"recreated audio")
            return str(p)

        fetch_audio_mock = MagicMock(side_effect=recreate_audio)
        with patch.object(main, "YouTubeTranscriptApi", return_value=mock_api), \
             patch.object(main, "fetch_audio", fetch_audio_mock):
            c1_recached = main.get_video_contract(url1, cache_dir=str(tmp_path))
            assert fetch_audio_mock.called
            assert c1_recached["video_id"] == vid1
            assert Path(c1_recached["audio_path"]).exists()


def test_audio_failure_raises_explicit_error(tmp_path):
    video_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    fake_vid = "dQw4w9WgXcQ"

    mock_api = MagicMock()
    mock_api.list.return_value.find_transcript.return_value.fetch.return_value = [
        MagicMock(start=0.0, duration=5.0, text="Hello world")
    ]

    with patch.object(main, "YouTubeTranscriptApi", return_value=mock_api), \
         patch.object(main, "fetch_audio", side_effect=RuntimeError("Gagal mengunduh audio: Network error")):

        with pytest.raises(RuntimeError) as exc_info:
            main.get_video_contract(video_url, cache_dir=str(tmp_path))

        assert "Gagal mengunduh audio" in str(exc_info.value)
