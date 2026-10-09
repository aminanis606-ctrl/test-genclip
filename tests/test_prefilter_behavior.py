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


def test_find_candidates_lossless_oracle_and_timestamps():
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

    # Reference oracle generating all valid duration pairs (30-90s)
    oracle_pairs = []
    for s in safe_starts:
        for e in safe_ends:
            if 30.0 <= (e - s) <= 90.0:
                oracle_pairs.append((round(s, 3), round(e, 3)))

    candidates = prefilter.find_candidates(transcript)
    cand_pairs = [(c["candidate_start"], c["candidate_end"]) for c in candidates]

    # Verify exact parity
    assert cand_pairs == oracle_pairs
    assert len(candidates) == 1823

    # Representative timestamp verification
    assert (0.28, 57.76) in cand_pairs
    assert (523.479, 604.04) in cand_pairs
    assert (523.479, 579.16) in cand_pairs


def test_prompt_compiler_size_reduction():
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

    # Verify TEXT is present for every candidate
    for c in candidates[:10]:
        assert f"CANDIDATE {c['id']}" in prompt
        assert c["text"] in prompt

    # Verify compact boundary formatting
    assert "[0.280..87.760]" in prompt or "[0.280" in prompt
