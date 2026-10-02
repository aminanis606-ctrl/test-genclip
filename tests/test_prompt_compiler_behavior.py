import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import prefilter


def test_prompt_compiler_separates_evidence_and_instructions():
    groups = [{
        "id": 1,
        "anchor_start": 35.0,
        "anchor_end": 70.0,
        "context_start": 5.0,
        "context_end": 100.0,
        "prefilter_marker": {
            "start": 35.0,
            "end": 70.0,
            "duration": 35.0,
        },
        "safe_start_boundaries": [35.0],
        "safe_end_boundaries": [70.0],
        "text": "Akhirnya kami menemukan solusi yang berhasil.",
    }]

    prompt = prefilter.build_gemini_prompt(
        "https://youtube.test/video",
        groups,
    )

    evidence_header = "=== FAKTA DAN KONTEKS/EVIDENCE PREFILTER (GROUPS) ==="
    instruction_header = "=== INSTRUKSI EVALUASI / HIPOTESIS UNTUK LLM EKSTERNAL ==="

    assert evidence_header in prompt
    assert instruction_header in prompt
    assert prompt.index(evidence_header) < prompt.index(instruction_header)

    assert "35.000 - 70.000" in prompt
    assert "Akhirnya kami menemukan solusi yang berhasil." in prompt
    assert "30–90" in prompt

    command_lines = [
        line for line in prompt.splitlines()
        if line.startswith("yt-dlp ")
    ]

    assert len(command_lines) == 1
    assert command_lines[0].count("--download-sections") == 2
    assert "https://youtube.test/video" in command_lines[0]
