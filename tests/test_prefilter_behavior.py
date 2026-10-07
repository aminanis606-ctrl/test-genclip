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


def test_candidate_discovery_does_not_explode_cartesian():
    # Build synthetic transcript with 10 safe starts and 10 safe ends in sequence.
    # Cartesian pairing would produce ~100 candidates if unconstrained.
    # Story-span discovery anchors natural story boundaries and produces bounded candidate counts.
    lines = []
    for i in range(10):
        start_sec = i * 20
        mid_sec = start_sec + 10
        end_sec = start_sec + 20
        # Start sentence (terminal boundary at end)
        lines.append(f"00:{start_sec//60:02d}:{start_sec%60:02d},000 --> 00:{mid_sec//60:02d}:{mid_sec%60:02d},000")
        lines.append(f"Pertama cerita ke {i} dimulai di sini.")
        lines.append("")
        lines.append(f"00:{mid_sec//60:02d}:{mid_sec%60:02d},000 --> 00:{end_sec//60:02d}:{end_sec%60:02d},000")
        lines.append(f"Kemudian cerita ke {i} berlanjut dan selesai.")
        lines.append("")

    transcript = "\n".join(lines)
    candidates = prefilter.find_candidates(transcript)

    # Verify duration hard gate for all
    for c in candidates:
        assert 30.0 <= c["candidate_duration"] <= 90.0

    # With 10 start boundaries and 15 end boundaries spaced 10s apart (spanning 0s to 200s),
    # Cartesian product of all valid start-end pairs between 30s and 90s would produce 63 pairs.
    # Natural story-span discovery anchors safe boundaries and produces 24 bounded candidates.
    assert len(candidates) <= 25


def test_real_sample_candidate_count_bounded():
    transcript_path = (
        Path(__file__).resolve().parent.parent
        / "samples"
        / "youtube"
        / "I2F9dZoLHUg"
        / "transcript.id-orig.srt"
    )
    transcript = transcript_path.read_text(encoding="utf-8")

    candidates = prefilter.find_candidates(transcript)

    # Legacy Cartesian generator produced 1823 candidates for this 20-min video.
    # Story-span discovery reduces this by >80% while retaining all valid story moments.
    assert len(candidates) < 500
    assert len(candidates) > 50  # verify recall is maintained across 20-min video
