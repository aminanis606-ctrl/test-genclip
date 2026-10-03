import math
import struct
import sys
import wave
from pathlib import Path

# Ensure app/src/main/python is in sys.path
sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "app" / "src" / "main" / "python"),
)

import audio_analysis
import prefilter


def create_sample_wav(filepath, duration_sec=5.0, sample_rate=16000):
    num_samples = int(duration_sec * sample_rate)
    with wave.open(str(filepath), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)

        frames = []
        for i in range(num_samples):
            t = i / sample_rate
            if 2.0 <= t <= 2.5:  # 0.5s silence pause
                sample_val = 0
            else:
                sample_val = int(16000 * math.sin(2 * math.pi * 440 * t))
            frames.append(struct.pack("<h", sample_val))

        wf.writeframes(b"".join(frames))


def create_sample_m4a(filepath, duration_sec=10.0, sample_rate=44100):
    timescale = sample_rate
    num_samples = int(duration_sec * 44100 / 1024)

    stts_data = struct.pack(">IIII", 0, 1, num_samples, 1024)
    stts_box = struct.pack(">I4s", len(stts_data) + 8, b"stts") + stts_data

    sizes = []
    for i in range(num_samples):
        t = i * (1024 / 44100.0)
        if 4.0 <= t <= 6.0:
            sizes.append(10)  # Silence frame
        else:
            sizes.append(200)  # Speech frame

    stsz_header = struct.pack(">III", 0, 0, num_samples)
    stsz_table = b"".join(struct.pack(">I", sz) for sz in sizes)
    stsz_box = struct.pack(">I4s", len(stsz_header) + len(stsz_table) + 8, b"stsz") + stsz_header + stsz_table

    mdhd_data = struct.pack(">BBBBIIIIHH", 0, 0, 0, 0, 0, 0, timescale, num_samples * 1024, 0, 0)
    mdhd_box = struct.pack(">I4s", len(mdhd_data) + 8, b"mdhd") + mdhd_data

    stbl_box = struct.pack(">I4s", len(stts_box) + len(stsz_box) + 8, b"stbl") + stts_box + stsz_box
    minf_box = struct.pack(">I4s", len(stbl_box) + 8, b"minf") + stbl_box
    mdia_box = struct.pack(">I4s", len(mdhd_box) + len(minf_box) + 8, b"mdia") + mdhd_box + minf_box
    trak_box = struct.pack(">I4s", len(mdia_box) + 8, b"trak") + mdia_box
    moov_box = struct.pack(">I4s", len(trak_box) + 8, b"moov") + trak_box

    ftyp_data = b"M4A \x00\x00\x02\x00M4A mp42isom"
    ftyp_box = struct.pack(">I4s", len(ftyp_data) + 8, b"ftyp") + ftyp_data

    mdat_data = b"".join(b"\x00" * sz for sz in sizes)
    mdat_box = struct.pack(">I4s", len(mdat_data) + 8, b"mdat") + mdat_data

    with open(filepath, "wb") as f:
        f.write(ftyp_box + moov_box + mdat_box)


def create_sample_mp3(filepath, duration_sec=10.0):
    frame_size = 417
    header = b"\xff\xfb\x90\x64"
    num_frames = int(duration_sec / (1152 / 44100.0))

    with open(filepath, "wb") as f:
        for i in range(num_frames):
            t = i * (1152 / 44100.0)
            if 4.0 <= t <= 6.0:
                payload = b"\x00" * (frame_size - 4)
            else:
                payload = b"\xaa" * (frame_size - 4)
            f.write(header + payload)


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
    assert evidence["pause_count"] >= 1
    assert "Audio [0.0s - 5.0s]:" in evidence["summary"]


def test_production_m4a_format_analysis(tmp_path):
    m4a_path = tmp_path / "video_123_audio.m4a"
    create_sample_m4a(m4a_path, duration_sec=10.0)

    evidence = audio_analysis.analyze_audio_segment(
        str(m4a_path),
        start_sec=0.0,
        end_sec=10.0,
    )

    assert evidence["audio_present"] is True
    assert evidence["status"] == "analyzed"
    assert isinstance(evidence["rms_db"], float)
    assert isinstance(evidence["peak_db"], float)
    assert 0.0 <= evidence["speech_ratio"] <= 1.0


def test_production_mp3_format_analysis(tmp_path):
    mp3_path = tmp_path / "video_123_audio.mp3"
    create_sample_mp3(mp3_path, duration_sec=10.0)

    evidence = audio_analysis.analyze_audio_segment(
        str(mp3_path),
        start_sec=0.0,
        end_sec=10.0,
    )

    assert evidence["audio_present"] is True
    assert evidence["status"] == "analyzed"
    assert isinstance(evidence["rms_db"], float)
    assert isinstance(evidence["peak_db"], float)


def test_missing_audio_file_returns_missing_status(tmp_path):
    non_existent = tmp_path / "missing.m4a"

    evidence = audio_analysis.analyze_audio_segment(
        str(non_existent),
        start_sec=10.0,
        end_sec=40.0,
    )

    assert evidence["audio_present"] is False
    assert evidence["status"] == "missing_file"
    assert "file not found" in evidence["summary"]


def test_find_candidates_integrates_production_m4a_audio_evidence(tmp_path):
    m4a_path = tmp_path / "video_sample_audio.m4a"
    create_sample_m4a(m4a_path, duration_sec=60.0)

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

    candidates = prefilter.find_candidates(transcript, audio_path=str(m4a_path))

    assert len(candidates) > 0
    for candidate in candidates:
        audio_ev = candidate.get("audio_evidence")
        assert audio_ev is not None
        assert audio_ev["audio_present"] is True
        assert audio_ev["status"] == "analyzed"
        assert isinstance(audio_ev["rms_db"], float)


def test_prompt_compiler_includes_audio_evidence_without_exposing_filepath(tmp_path):
    m4a_path = tmp_path / "secret_local_path.m4a"
    create_sample_m4a(m4a_path, duration_sec=60.0)

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

    candidates = prefilter.find_candidates(transcript, audio_path=str(m4a_path))
    groups = prefilter.group_candidates(candidates)
    prompt = prefilter.build_gemini_prompt("https://youtube.test/v1", groups)

    assert "AUDIO_EVIDENCE:" in prompt
    assert "RMS " in prompt
    assert "Peak " in prompt
    # Strict check: local filepath or audio_path string must NEVER be exposed in prompt
    assert str(m4a_path) not in prompt
    assert "secret_local_path" not in prompt
