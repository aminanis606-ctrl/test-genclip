import math
import struct
import sys
import wave
from pathlib import Path
from unittest.mock import patch, MagicMock

import miniaudio

# Ensure app/src/main/python is in sys.path
sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "app" / "src" / "main" / "python"),
)

import audio_analysis
import main
import prefilter


def create_sample_wav(filepath, duration_sec=5.0, amplitude=16000, pause_start=2.0, pause_end=2.5, sample_rate=16000):
    num_samples = int(duration_sec * sample_rate)
    with wave.open(str(filepath), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)

        frames = []
        for i in range(num_samples):
            t = i / sample_rate
            if pause_start <= t <= pause_end:
                sample_val = 0
            else:
                sample_val = int(amplitude * math.sin(2 * math.pi * 440 * t))
            frames.append(struct.pack("<h", sample_val))

        wf.writeframes(b"".join(frames))


def create_compressed_mp3_fixture(filepath, duration_sec=5.0, payload_byte=0x00):
    frame_size = 417
    header = b"\xff\xfb\x90\x64"  # 128kbps, 44.1kHz, mono MP3 frame
    payload = bytes([payload_byte & 0xFF]) * (frame_size - 4)
    frame = header + payload

    num_frames = int(duration_sec / (1152.0 / 44100.0))

    with open(str(filepath), "wb") as f:
        f.write(frame * num_frames)


def test_audio_segment_analysis_on_wav_file(tmp_path):
    wav_path = tmp_path / "test_audio.wav"
    create_sample_wav(wav_path, duration_sec=5.0)

    evidence = audio_analysis.analyze_audio_segment(
        str(wav_path),
        start_sec=0.0,
        end_sec=5.0,
    )

    assert evidence["audio_present"] is True
    assert evidence["status"] == "analyzed"
    assert evidence["start"] == 0.0
    assert evidence["end"] == 5.0
    assert evidence["duration"] == 5.0
    assert isinstance(evidence["rms_db"], float)
    assert isinstance(evidence["peak_db"], float)
    assert 0.0 <= evidence["speech_ratio"] <= 1.0
    assert "Audio [0.0s - 5.0s]:" in evidence["summary"]


def test_real_compressed_mp3_audio_decoding_and_analysis(tmp_path):
    mp3_path = tmp_path / "sample.mp3"
    create_compressed_mp3_fixture(mp3_path, duration_sec=5.0, payload_byte=0x41)

    evidence = audio_analysis.analyze_audio_segment(str(mp3_path), start_sec=0.0, end_sec=5.0)

    assert evidence["audio_present"] is True
    assert evidence["status"] == "analyzed"
    assert isinstance(evidence["rms_db"], float)
    assert isinstance(evidence["peak_db"], float)


def test_different_compressed_audio_signals_produce_different_audio_evidence(tmp_path):
    mp3_loud = tmp_path / "loud.mp3"
    mp3_quiet = tmp_path / "quiet.mp3"

    # Signal A: Loud compressed MP3 audio (payload byte 0x41)
    create_compressed_mp3_fixture(mp3_loud, duration_sec=5.0, payload_byte=0x41)

    # Signal B: Quiet compressed MP3 audio (payload byte 0x00)
    create_compressed_mp3_fixture(mp3_quiet, duration_sec=5.0, payload_byte=0x00)

    evidence_loud = audio_analysis.analyze_audio_segment(str(mp3_loud), start_sec=0.0, end_sec=5.0)
    evidence_quiet = audio_analysis.analyze_audio_segment(str(mp3_quiet), start_sec=0.0, end_sec=5.0)

    assert evidence_loud["status"] == "analyzed"
    assert evidence_quiet["status"] == "analyzed"

    # Prove that two different decoded compressed PCM audio signals produce distinct AUDIO_EVIDENCE
    assert evidence_loud["rms_db"] > evidence_quiet["rms_db"]
    assert evidence_loud["peak_db"] > evidence_quiet["peak_db"]
    assert evidence_loud["summary"] != evidence_quiet["summary"]


def test_decode_failed_for_corrupted_audio_file(tmp_path):
    corrupt_file = tmp_path / "corrupt.mp3"
    corrupt_file.write_bytes(b"INVALID_HEADER_GARBAGE_BYTES")

    evidence = audio_analysis.analyze_audio_segment(str(corrupt_file), start_sec=0.0, end_sec=5.0)

    assert evidence["audio_present"] is True
    assert evidence["status"] == "decode_failed"
    assert "decode failed" in evidence["summary"]


def test_missing_audio_file_returns_missing_status(tmp_path):
    non_existent = tmp_path / "missing.mp3"

    evidence = audio_analysis.analyze_audio_segment(
        str(non_existent),
        start_sec=10.0,
        end_sec=40.0,
    )

    assert evidence["audio_present"] is False
    assert evidence["status"] == "missing_file"
    assert "file not found" in evidence["summary"]


def test_fetch_audio_selects_lowest_bitrate_audio_only_format_and_decodes_pcm(tmp_path):
    vid = "test_vid_123"
    url = f"https://www.youtube.com/watch?v={vid}"

    fake_mp3 = tmp_path / f"video_{vid}_audio.mp3"

    def mock_extract(target_url, download=True):
        create_compressed_mp3_fixture(fake_mp3, duration_sec=10.0, payload_byte=0x41)
        return {"duration": 10.0}

    mock_ydl = MagicMock()
    mock_ydl.extract_info.side_effect = mock_extract

    with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

        audio_path, duration = main.fetch_audio(vid, url, str(tmp_path))

        assert mock_ydl_cls.called
        opts = mock_ydl_cls.call_args[0][0]

        # Verify format selector enforces audio-only lowest bitrate
        assert opts["format"] == "worstaudio[ext=m4a]/worstaudio[ext=webm]/worstaudio[ext=mp3]/worstaudio/worst"
        assert audio_path == str(fake_mp3)
        assert duration == 10.0

        # Prove that the downloaded audio file passes directly through decoder to PCM and candidate AUDIO_EVIDENCE
        transcript = "00:00:00,000 --> 00:00:35,000\nSolusi bisnis yang berhasil."
        candidates = prefilter.find_candidates(transcript, audio_path=audio_path)
        assert len(candidates) > 0
        audio_ev = candidates[0]["audio_evidence"]
        assert audio_ev["status"] == "analyzed"
        assert isinstance(audio_ev["rms_db"], float)


def test_find_candidates_integrates_audio_evidence(tmp_path):
    mp3_path = tmp_path / "sample.mp3"
    create_compressed_mp3_fixture(mp3_path, duration_sec=60.0, payload_byte=0x41)

    transcript = "\n".join([
        "00:00:00,000 --> 00:00:20,000",
        "Pertama kita menghadapi masalah besar dalam bisnis.",
        "",
        "00:00:20,000 --> 00:00:45,000",
        "Kemudian akhirnya kami menemukan solusi yang berhasil.",
        "",
        "00:00:45,000 --> 00:01:10,000",
        "Setelah itu keputusan tersebut mengubah segalanya.",
    ])

    candidates = prefilter.find_candidates(transcript, audio_path=str(mp3_path))

    assert len(candidates) > 0
    for candidate in candidates:
        audio_ev = candidate.get("audio_evidence")
        assert audio_ev is not None
        assert audio_ev["audio_present"] is True
        assert audio_ev["status"] == "analyzed"
        assert isinstance(audio_ev["rms_db"], float)


def test_prompt_compiler_includes_audio_evidence_without_exposing_filepath(tmp_path):
    mp3_path = tmp_path / "secret_local_path.mp3"
    create_compressed_mp3_fixture(mp3_path, duration_sec=60.0, payload_byte=0x41)

    transcript = "\n".join([
        "00:00:00,000 --> 00:00:20,000",
        "Pertama kita menghadapi masalah besar dalam bisnis.",
        "",
        "00:00:20,000 --> 00:00:45,000",
        "Kemudian akhirnya kami menemukan solusi yang berhasil.",
        "",
        "00:00:45,000 --> 00:01:10,000",
        "Setelah itu keputusan tersebut mengubah segalanya.",
    ])

    candidates = prefilter.find_candidates(transcript, audio_path=str(mp3_path))
    groups = prefilter.group_candidates(candidates)
    prompt = prefilter.build_gemini_prompt("https://youtube.test/v1", groups)

    assert "AUDIO_EVIDENCE:" in prompt
    assert "RMS " in prompt
    assert "Peak " in prompt
    # Strict check: local filepath or audio_path string must NEVER be exposed in prompt
    assert str(mp3_path) not in prompt
    assert "secret_local_path" not in prompt
