import sys
from pathlib import Path

from whisper import transcript
from prefilter import find_candidates, group_candidates, build_gemini_prompt


def main():
    if len(sys.argv) != 2:
        print('Pakai: python pipeline.py "YOUTUBE_URL"')
        return

    url = sys.argv[1].strip()

    print("[1] AUDIO + TRANSCRIPT")

    transcript_file = transcript(url)

    if not transcript_file:
        print("[ERROR] Transkrip tidak ditemukan.")
        return

    if isinstance(transcript_file, Path):
        text = transcript_file.read_text(encoding="utf-8")
    else:
        text = str(transcript_file)

    print("[2] PREFILTER")

    candidates = find_candidates(text)

    print(f"[PREFILTER] {len(candidates)} kandidat ditemukan")

    if not candidates:
        print("[STOP] Kandidat kosong.")
        return

    print("[3] GROUPING & PROMPT BUILDER")

    groups = group_candidates(candidates)
    prompt = build_gemini_prompt(url, groups)

    print(f"[GROUPING] {len(groups)} kelompok kandidat")
    print("\n" + "=" * 20 + " PROMPT AI VALIDATION " + "=" * 20 + "\n")
    print(prompt)


if __name__ == "__main__":
    main()
