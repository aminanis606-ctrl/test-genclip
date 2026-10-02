import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "app" / "src" / "main" / "python"),
)

import prefilter


def test_overlapping_candidates_are_preserved():
    transcript = "\n".join([
        "[0-35] Pertama kita mengalami masalah besar dalam bisnis.",
        "[35-70] Kemudian akhirnya kami menemukan solusi yang berhasil.",
        "[70-105] Setelah itu keputusan tersebut mengubah semuanya.",
        "[105-140] Dari pengalaman itu saya belajar banyak hal.",
    ])

    candidates = prefilter.find_candidates(transcript)

    windows = {
        (candidate["candidate_start"], candidate["candidate_end"])
        for candidate in candidates
    }

    assert (0.0, 70.0) in windows
    assert (35.0, 105.0) in windows
    assert (70.0, 140.0) in windows
