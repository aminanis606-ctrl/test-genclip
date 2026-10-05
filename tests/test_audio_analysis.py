import io
import math
import os
import struct
import sys
import wave
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import soundfile as sf

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


def extract_opus_packets_from_ogg(ogg_bytes: bytes):
    packets = []
    stream = io.BytesIO(ogg_bytes)
    total_len = len(ogg_bytes)

    while stream.tell() < total_len:
        magic = stream.read(4)
        if magic != b"OggS":
            break
        version = stream.read(1)
        header_type = stream.read(1)[0]
        granule = struct.unpack("<q", stream.read(8))[0]
        serial = struct.unpack("<I", stream.read(4))[0]
        page_num = struct.unpack("<I", stream.read(4))[0]
        checksum = stream.read(4)
        num_segs = stream.read(1)[0]
        seg_table = stream.read(num_segs)

        seg_idx = 0
        while seg_idx < num_segs:
            pkt_data = bytearray()
            while seg_idx < num_segs:
                length = seg_table[seg_idx]
                seg_idx += 1
                pkt_data.extend(stream.read(length))
                if length < 255:
                    break
            packets.append(bytes(pkt_data))

    opus_head = packets[0] if packets else None
    audio_packets = packets[2:] if len(packets) > 2 else []
    return opus_head, audio_packets


def encode_genuine_webm_opus_fixture(filepath, duration_sec=5.0, amplitude=0.8, sample_rate=16000):
    """
    Encodes a genuine Matroska/WebM container file with an authentic Opus audio stream.
    EBML Magic Header: 0x1A45DFA3 DocType 'webm'
    Track 1: CodecID 'A_OPUS' with OpusHead CodecPrivate
    Cluster SimpleBlocks containing real encoded Opus audio frames.
    """
    num_samples = int(duration_sec * sample_rate)
    t = np.linspace(0, duration_sec, num_samples, endpoint=False)
    signal = amplitude * np.sin(2 * np.pi * 440 * t)

    ogg_buf = io.BytesIO()
    sf.write(ogg_buf, signal, sample_rate, format="OGG", subtype="OPUS")
    ogg_bytes = ogg_buf.getvalue()

    opus_head, audio_packets = extract_opus_packets_from_ogg(ogg_bytes)

    def encode_vint(num):
        if num < 127:
            return bytes([num | 0x80])
        elif num < 16383:
            return struct.pack(">H", num | 0x4000)
        elif num < 2097151:
            return bytes([(num >> 16) | 0x20, (num >> 8) & 0xFF, num & 0xFF])
        else:
            return bytes([(num >> 24) | 0x10, (num >> 16) & 0xFF, (num >> 8) & 0xFF, num & 0xFF])

    def make_elem(elem_id, data):
        id_bytes = elem_id.to_bytes((elem_id.bit_length() + 7) // 8, "big")
        return id_bytes + encode_vint(len(data)) + data

    ebml = (
        make_elem(0x4286, b"\x01") +
        make_elem(0x42F7, b"\x01") +
        make_elem(0x42F2, b"\x04") +
        make_elem(0x42F3, b"\x08") +
        make_elem(0x4282, b"webm") +
        make_elem(0x4287, b"\x02") +
        make_elem(0x4285, b"\x02")
    )
    ebml_header = make_elem(0x1A45DFA3, ebml)

    track_entry = (
        make_elem(0xD7, b"\x01") +
        make_elem(0x73C5, b"\x01\x00\x00\x00\x00\x00\x00\x01") +
        make_elem(0x83, b"\x02") +
        make_elem(0x86, b"A_OPUS") +
        make_elem(0x63A2, opus_head) +
        make_elem(0xE1, make_elem(0xB5, struct.pack(">f", 48000.0)) + make_elem(0x9F, b"\x01"))
    )
    tracks = make_elem(0x1654AE6B, track_entry)

    cluster_payload = make_elem(0xE7, b"\x00")
    for i, pkt in enumerate(audio_packets):
        timecode = (i * 20) & 0x7FFF
        block_hdr = bytes([0x81]) + struct.pack(">h", timecode) + b"\x80"
        simple_block = make_elem(0xA3, block_hdr + pkt)
        cluster_payload += simple_block

    cluster = make_elem(0x1F43B675, cluster_payload)
    segment = make_elem(0x18538067, tracks + cluster)

    webm_bytes = ebml_header + segment
    with open(str(filepath), "wb") as f:
        f.write(webm_bytes)


def test_audio_segment_analysis_on_wav_file(tmp_path):
    wav_path = tmp_path / "test_audio.wav"
    create_sample_wav(wav_path, duration_sec=5.0, amplitude=12000, pause_start=2.0, pause_end=2.5)

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


def test_real_genuine_webm_opus_audio_decoding_and_analysis(tmp_path):
    webm_path = tmp_path / "sample.webm"
    encode_genuine_webm_opus_fixture(webm_path, duration_sec=5.0, amplitude=0.8)

    # Verify that the fixture is an authentic WebM EBML container
    assert webm_path.read_bytes().startswith(b"\x1a\x45\xdf\xa3")

    evidence = audio_analysis.analyze_audio_segment(str(webm_path), start_sec=0.0, end_sec=5.0)

    assert evidence["audio_present"] is True
    assert evidence["status"] == "analyzed"
    assert isinstance(evidence["rms_db"], float)
    assert isinstance(evidence["peak_db"], float)


def test_different_webm_opus_audio_signals_produce_different_audio_evidence(tmp_path):
    webm_loud = tmp_path / "loud.webm"
    webm_quiet = tmp_path / "quiet.webm"

    # Signal A: Loud genuine WebM Opus audio (amplitude 0.9)
    encode_genuine_webm_opus_fixture(webm_loud, duration_sec=5.0, amplitude=0.9)

    # Signal B: Quiet genuine WebM Opus audio (amplitude 0.05)
    encode_genuine_webm_opus_fixture(webm_quiet, duration_sec=5.0, amplitude=0.05)

    evidence_loud = audio_analysis.analyze_audio_segment(str(webm_loud), start_sec=0.0, end_sec=5.0)
    evidence_quiet = audio_analysis.analyze_audio_segment(str(webm_quiet), start_sec=0.0, end_sec=5.0)

    assert evidence_loud["status"] == "analyzed"
    assert evidence_quiet["status"] == "analyzed"

    # Prove that two different decoded WebM Opus PCM audio signals produce distinct AUDIO_EVIDENCE (> 10 dB difference)
    assert evidence_loud["rms_db"] > evidence_quiet["rms_db"] + 10.0
    assert evidence_loud["peak_db"] > evidence_quiet["peak_db"] + 10.0
    assert evidence_loud["summary"] != evidence_quiet["summary"]


def test_decode_failed_for_corrupted_audio_file(tmp_path):
    corrupt_file = tmp_path / "corrupt.webm"
    corrupt_file.write_bytes(b"INVALID_HEADER_GARBAGE_BYTES")

    evidence = audio_analysis.analyze_audio_segment(str(corrupt_file), start_sec=0.0, end_sec=5.0)

    assert evidence["audio_present"] is True
    assert evidence["status"] == "decode_failed"
    assert "decode failed" in evidence["summary"]


def test_missing_audio_file_returns_missing_status(tmp_path):
    non_existent = tmp_path / "missing.webm"

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

    fake_webm = tmp_path / f"video_{vid}_audio.webm"

    def mock_extract(target_url, download=True):
        encode_genuine_webm_opus_fixture(fake_webm, duration_sec=10.0, amplitude=0.8)
        return {"duration": 10.0}

    mock_ydl = MagicMock()
    mock_ydl.extract_info.side_effect = mock_extract

    with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

        audio_path, duration = main.fetch_audio(vid, url, str(tmp_path))

        assert mock_ydl_cls.called
        opts = mock_ydl_cls.call_args[0][0]

        # Verify format selector enforces WebM/Opus priority audio-only lowest bitrate
        assert "worstaudio[ext=webm]" in opts["format"]
        assert audio_path == str(fake_webm)
        assert duration == 10.0

        # Prove that the downloaded WebM Opus audio file passes directly through decoder to PCM and candidate AUDIO_EVIDENCE
        transcript = "00:00:00,000 --> 00:00:35,000\nSolusi bisnis yang berhasil."
        candidates = prefilter.find_candidates(transcript, audio_path=audio_path)
        assert len(candidates) > 0
        audio_ev = candidates[0]["audio_evidence"]
        assert audio_ev["status"] == "analyzed"
        assert isinstance(audio_ev["rms_db"], float)


def test_find_candidates_positional_backwards_compatibility(tmp_path):
    transcript = "00:00:00,000 --> 00:00:35,000\nSolusi bisnis yang berhasil."

    # Legacy call with 2 positional arguments: (transcript_text, limit)
    candidates = prefilter.find_candidates(transcript, 10)
    assert isinstance(candidates, list)


def test_prompt_compiler_includes_audio_evidence_without_exposing_filepath(tmp_path):
    webm_path = tmp_path / "secret_local_path.webm"
    encode_genuine_webm_opus_fixture(webm_path, duration_sec=60.0, amplitude=0.8)

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

    candidates = prefilter.find_candidates(transcript, audio_path=str(webm_path))
    groups = prefilter.group_candidates(candidates)
    prompt = prefilter.build_gemini_prompt("https://youtube.test/v1", groups)

    assert "AUDIO_EVIDENCE:" in prompt
    assert "RMS " in prompt
    assert "Peak " in prompt
    # Strict check: local filepath or audio_path string must NEVER be exposed in prompt
    assert str(webm_path) not in prompt
    assert "secret_local_path" not in prompt
