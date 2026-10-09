import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "app" / "src" / "main" / "python"),
)

import prefilter


def test_prefilter_contract_uses_timestamps_and_preserves_recall_boundaries():
    transcript = "\n".join([
        "00:00:00,000 --> 00:00:35,000",
        "Pertama kita mengalami masalah besar dalam bisnis.",
        "",
        "00:00:35,000 --> 00:01:10,000",
        "Kemudian akhirnya kami menemukan solusi yang berhasil.",
        "",
        "00:01:10,000 --> 00:01:45,000",
        "Setelah itu keputusan tersebut mengubah semuanya.",
        "",
        "00:01:45,000 --> 00:02:20,000",
        "yang kemudian menjadi pelajaran penting bagi kami.",
        "",
        "00:02:20,000 --> 00:02:55,000",
        "Namun bagian ini berakhir sebagai pertanyaan?",
    ])

    segments = prefilter.parse(transcript)

    assert len(segments) == 5
    assert segments[0]["start"] == 0.0
    assert segments[1]["start"] == 35.0
    assert segments[2]["start"] == 70.0
    assert segments[3]["start"] == 105.0
    assert segments[4]["start"] == 140.0

    safe_starts = prefilter._safe_start_boundaries(segments)
    safe_ends = prefilter._safe_end_boundaries(segments)

    assert 0.0 in safe_starts
    assert 35.0 in safe_starts
    assert 70.0 in safe_starts
    assert 105.0 not in safe_starts

    assert 35.0 in safe_ends
    assert 70.0 in safe_ends
    assert 105.0 in safe_ends
    assert 175.0 not in safe_ends

    candidates = prefilter.find_candidates(transcript)

    windows = {
        (candidate["candidate_start"], candidate["candidate_end"])
        for candidate in candidates
    }

    assert (0.0, 70.0) in windows
    assert (35.0, 105.0) in windows

    assert any(
        candidate["candidate_start"] == 0.0
        and candidate["candidate_end"] == 70.0
        and candidate["candidate_end"] - candidate["candidate_start"] == 70.0
        for candidate in candidates
    )

    assert any(
        candidate["candidate_start"] == 35.0
        and candidate["candidate_end"] == 105.0
        and candidate["candidate_end"] - candidate["candidate_start"] == 70.0
        for candidate in candidates
    )

    assert all(
        30.0 <= candidate["candidate_duration"] <= 90.0
        for candidate in candidates
    )

def test_real_sample_finds_mother_umrah_story_candidate():
    transcript_path = (
        Path(__file__).resolve().parent.parent
        / "samples"
        / "youtube"
        / "I2F9dZoLHUg"
        / "transcript.id-orig.srt"
    )
    transcript = transcript_path.read_text(encoding="utf-8")

    candidates = prefilter.find_candidates(transcript)

    assert any(
        candidate["candidate_start"] == 523.479
        and candidate["candidate_end"] == 604.04
        and candidate["candidate_duration"] == 80.561
        for candidate in candidates
    )


def test_find_candidates_lossless_oracle_comparison():
    transcript_path = (
        Path(__file__).resolve().parent.parent
        / "samples"
        / "youtube"
        / "I2F9dZoLHUg"
        / "transcript.id-orig.srt"
    )
    transcript = transcript_path.read_text(encoding="utf-8")

    segments = prefilter.parse(transcript)
    safe_starts = prefilter._safe_start_boundaries(segments)
    safe_ends = prefilter._safe_end_boundaries(segments)

    # Brute-force reference oracle
    oracle_pairs = []
    for s in safe_starts:
        for e in safe_ends:
            if 30.0 <= (e - s) <= 90.0:
                oracle_pairs.append((round(s, 3), round(e, 3)))

    candidates = prefilter.find_candidates(transcript)
    cand_pairs = [
        (c["candidate_start"], c["candidate_end"]) for c in candidates
    ]

    # Verify exact 100% parity with brute-force reference oracle
    assert len(candidates) == len(oracle_pairs)
    assert cand_pairs == oracle_pairs

    # Verify candidates under 60 seconds are present (e.g. 523.479 -> 579.160 = 55.681s)
    under_60s = [c for c in candidates if c["candidate_duration"] < 60.0]
    assert len(under_60s) > 900


def test_synthetic_2hour_transcript_lossless_oracle_and_performance():
    # Build synthetic 2-hour transcript (7,200s, 360 segments of 20s each)
    lines = []
    for i in range(360):
        s_sec = i * 20
        e_sec = s_sec + 20
        lines.append(f"{s_sec//3600:02d}:{(s_sec%3600)//60:02d}:{s_sec%60:02d},000 --> {e_sec//3600:02d}:{(e_sec%3600)//60:02d}:{e_sec%60:02d},000")
        lines.append(f"Segmen cerita ke {i} dimulai di sini dan berlanjut sampai selesai.")
        lines.append("")

    synth_transcript = "\n".join(lines)
    segments = prefilter.parse(synth_transcript)
    safe_starts = prefilter._safe_start_boundaries(segments)
    safe_ends = prefilter._safe_end_boundaries(segments)

    oracle_pairs = []
    for s in safe_starts:
        for e in safe_ends:
            if 30.0 <= (e - s) <= 90.0:
                oracle_pairs.append((round(s, 3), round(e, 3)))

    candidates = prefilter.find_candidates(synth_transcript)
    cand_pairs = [(c["candidate_start"], c["candidate_end"]) for c in candidates]

    assert len(candidates) == len(oracle_pairs)
    assert cand_pairs == oracle_pairs


def test_prompt_size_reduction_and_performance():
    transcript_path = (
        Path(__file__).resolve().parent.parent
        / "samples"
        / "youtube"
        / "I2F9dZoLHUg"
        / "transcript.id-orig.srt"
    )
    transcript = transcript_path.read_text(encoding="utf-8")

    candidates = prefilter.find_candidates(transcript)
    groups = prefilter.group_candidates(candidates)
    prompt = prefilter.build_gemini_prompt(
        "https://www.youtube.com/watch?v=I2F9dZoLHUg",
        groups,
        full_transcript_text=transcript,
    )

    # Target prompt size: <= 549,321 characters (80% drop from 2,746,605)
    assert len(prompt) <= 549321
    assert len(candidates) == 1823
