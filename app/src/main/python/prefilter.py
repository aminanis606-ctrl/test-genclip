import re


SEGMENT_RE = re.compile(
    r"\[(\d+(?:\.\d+)?)\s*-\s*"
    r"(\d+(?:\.\d+)?)\]\s*(.*)"
)

SRT_TIME_RE = re.compile(
    r"^(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s+-->\s+"
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})$"
)

TERMINAL_BOUNDARY_RE = re.compile(
    r"""[.!?](?:['")\]]*)$"""
)

SIGNALS = re.compile(
    r"\b("
    r"karena|ternyata|tetapi|tapi|namun|akhirnya|"
    r"berhasil|gagal|masalah|solusi|pengalaman|"
    r"kesalahan|pelajaran|rahasia|pertama|terbesar|"
    r"mengapa|kenapa|bagaimana|uang|gaji|bisnis|"
    r"usaha|hasil|berubah|keputusan|"
    r"menurut saya|pernah|dulu|waktu itu"
    r")\b",
    re.I,
)

# Sinyal konten short-form terarah untuk meningkatkan recall hook
FINANCIAL_RE = re.compile(
    r"\b("
    r"rp\.?|rupiah|idr|usd|dollar|dolar|omzet|omset|profit|cuan|modal|utang|hutang|gaji|penjualan"
    r")\b|"
    r"\b\d+(?:[.,]\d+)?\s*(?:ribu|jt|juta|miliar|milyar|triliun|persen|%|k|m|b)\b|"
    r"\brp\s*\d+",
    re.I,
)

AMBITION_RE = re.compile(
    r"\b("
    r"target|ambisi|cita-cita|goal|tujuan|pengen|ingin|bertekad|fokus|"
    r"mau capai|mencapai|tembus|wujudkan|meraih"
    r")\b",
    re.I,
)

PERSONAL_EXP_RE = re.compile(
    r"\b("
    r"pengalaman saya|waktu itu|pas saya|dulu saya|saat saya|ketika saya|"
    r"sewaktu saya|cerita saya|kisah saya|perjalanan saya"
    r")\b|"
    r"\b(saya|aku|gue|gua)\s+(sempat|pernah|mengalami|merasakan|memutuskan|kehilangan|mencoba|sadar|belajar)\b",
    re.I,
)

TRANSFORMATION_RE = re.compile(
    r"\b("
    r"titik balik|berubah total|mengubah hidup|titik terendah|bangkit|"
    r"dari nol|dari bawah|sekarang jadi|akhirnya berubah|berbalik"
    r")\b|"
    r"\b(dulu|awalnya|mulanya)\b.*\b(sekarang|akhirnya)\b",
    re.I,
)

PROBLEM_SOLUTION_RE = re.compile(
    r"\b("
    r"masalahnya|kendala|solusinya|kuncinya|rahasianya|jalan keluar|"
    r"triknya|cara mengatasinya|hasilnya|dampaknya|akibatnya|kesalahan terbesar"
    r")\b",
    re.I,
)

EXTREME_EXP_RE = re.compile(
    r"\b("
    r"hancur|parah|gila|kacau|luar biasa|kaget|syok|shock|bangkrut|"
    r"rugi besar|untung besar|gak nyangka|nggak nyangka|tidak disangka|ajaib|fatal"
    r")\b",
    re.I,
)

STRONG_OPINION_RE = re.compile(
    r"\b("
    r"menurut saya|saya yakin|faktanya|kenyataannya|sejujurnya|jujur saja|"
    r"ingat ya|pelajaran terpenting|prinsip saya|kuncinya adalah|paling penting|"
    r"jangan pernah|kesalahan fatal"
    r")\b",
    re.I,
)

QUESTION_HOOK_RE = re.compile(
    r"\b(kenapa|mengapa|bagaimana|gimana|apa yang terjadi|tahu gak|tahu nggak)\b",
    re.I,
)

BAD = re.compile(
    r"\b("
    r"subscribe|like|comment|follow|jangan lupa|"
    r"terima kasih sudah menonton|website|qr code"
    r")\b",
    re.I,
)


def parse_timestamp(value):
    hours, minutes, seconds, millis = map(int, value)
    return (
        hours * 3600
        + minutes * 60
        + seconds
        + millis / 1000.0
    )


def parse(transcript):
    segments = []
    lines = transcript.splitlines()
    index = 0

    while index < len(lines):
        line = lines[index].strip()

        legacy = SEGMENT_RE.match(line)
        if legacy:
            start = float(legacy.group(1))
            end = float(legacy.group(2))
            text = legacy.group(3).strip()

            if end > start and text:
                segments.append({
                    "start": start,
                    "end": end,
                    "text": text,
                    "raw": line,
                })

            index += 1
            continue

        srt = SRT_TIME_RE.match(line)
        if srt:
            groups = srt.groups()
            start = parse_timestamp(groups[:4])
            end = parse_timestamp(groups[4:])

            index += 1
            text_lines = []

            while index < len(lines) and lines[index].strip():
                text_lines.append(lines[index].strip())
                index += 1

            text = " ".join(text_lines).strip()

            if end > start and text:
                segments.append({
                    "start": start,
                    "end": end,
                    "text": text,
                    "raw": f"[{start:.3f} - {end:.3f}] {text}",
                })

        index += 1

    return segments


def is_terminal_boundary(text):
    normalized = " ".join(str(text).split()).strip()
    return bool(TERMINAL_BOUNDARY_RE.search(normalized))


def _safe_start_boundaries(segments):
    """
    Return segment starts that are not inside any earlier overlapping
    transcript segment.

    A later ASR segment may begin before an earlier segment has ended.
    Such a start is unsafe because it can cut through an ongoing thought.
    """
    safe_starts = []
    max_previous_end = None

    for segment in segments:
        start = float(segment["start"])
        end = float(segment["end"])

        if max_previous_end is None or start >= max_previous_end - 1e-6:
            safe_starts.append(round(start, 3))

        if max_previous_end is None:
            max_previous_end = end
        else:
            max_previous_end = max(max_previous_end, end)

    return sorted(set(safe_starts))


def _safe_end_for_terminal(segments, index):
    """
    Extend a terminal punctuation boundary through every later segment
    that overlaps the current boundary.
    """
    boundary = float(segments[index]["end"])

    for later in segments[index + 1:]:
        if float(later["start"]) < boundary - 1e-6:
            boundary = max(boundary, float(later["end"]))
            continue

        break

    return round(boundary, 3)


def _build_structural_context(segments, anchor_index, max_seconds=120.0):
    """
    Build bounded transcript context using physical timeline gaps.

    Without diarization/VAD, transcript gaps are the strongest structural
    signal currently available. A gap >1.5s is treated as a hard context
    break. The result is capped at max_seconds.
    """
    if not segments:
        return 0.0, 0.0

    anchor = segments[anchor_index]
    start = float(anchor["start"])
    end = float(anchor["end"])

    for index in range(anchor_index - 1, -1, -1):
        candidate_start = float(segments[index]["start"])
        candidate_end = float(segments[index]["end"])
        gap = start - candidate_end

        if gap > 1.5:
            break

        if end - candidate_start > max_seconds:
            break

        start = candidate_start

    for index in range(anchor_index + 1, len(segments)):
        candidate_start = float(segments[index]["start"])
        candidate_end = float(segments[index]["end"])
        gap = candidate_start - end

        if gap > 1.5:
            break

        if candidate_end - start > max_seconds:
            break

        end = candidate_end

    return round(start, 3), round(end, 3)


def build_prefilter_marker(segments, anchor_start, anchor_end):
    """
    Build deterministic physical/lexical boundaries for Gemini.

    PREFILTER does not decide the final clip duration. It only exposes
    boundaries that are safe with respect to ASR overlap and terminal
    punctuation. Gemini remains responsible for story completeness and
    the final 25-70 second selection.
    """
    safe_starts = _safe_start_boundaries(segments)
    safe_ends = []

    for index, segment in enumerate(segments):
        if not is_terminal_boundary(segment["text"]):
            continue

        terminal_end = _safe_end_for_terminal(segments, index)

        # A punctuation mark followed immediately by another segment is
        # a weak boundary unless the next segment actually begins after
        # a small natural pause.
        next_index = index + 1
        if next_index < len(segments):
            next_start = float(segments[next_index]["start"])
            raw_end = float(segment["end"])
            gap = next_start - raw_end

            if gap < 0.2 and next_start >= raw_end - 1e-6:
                continue

        safe_ends.append(terminal_end)

    safe_ends = sorted(set(safe_ends))

    start_options = [
        value
        for value in safe_starts
        if value <= anchor_start + 1e-6
    ]

    end_options = [
        value
        for value in safe_ends
        if value >= anchor_end - 1e-6
    ]

    if not start_options or not end_options:
        return None, safe_starts, safe_ends

    marker_start = start_options[-1]
    marker_end = end_options[0]

    return {
        "start": marker_start,
        "end": marker_end,
        "duration": round(marker_end - marker_start, 3),
    }, safe_starts, safe_ends


def score(segment, next_segment=None):
    text = segment["text"]
    words = len(text.split())
    value = 0

    if 8 <= words <= 60:
        value += 2
    elif 5 <= words < 8:
        value += 1

    if SIGNALS.search(text):
        value += 3

    # 1. Nominal uang / angka finansial
    if FINANCIAL_RE.search(text):
        value += 3

    # 2. Target atau ambisi
    if AMBITION_RE.search(text):
        value += 2

    # 3. Pengalaman pribadi
    if PERSONAL_EXP_RE.search(text):
        value += 3

    # 4. Perubahan hidup / before-after
    if TRANSFORMATION_RE.search(text):
        value += 3

    # 5. Problem -> result / solusi
    if PROBLEM_SOLUTION_RE.search(text):
        value += 3

    # 6. Pengalaman ekstrem atau mengejutkan
    if EXTREME_EXP_RE.search(text):
        value += 3

    # 7. Pernyataan kuat / opini pribadi
    if STRONG_OPINION_RE.search(text):
        value += 2

    # 8. Pertanyaan yang diikuti jawaban substantif
    if "?" in text:
        value += 2
        if QUESTION_HOOK_RE.search(text):
            value += 1
        if re.search(r"\?.*\b(karena|sebab|jadi|ternyata|yaitu|adalah)\b", text, re.I):
            value += 2
        elif next_segment:
            next_text = next_segment.get("text", "")
            next_words = len(next_text.split())
            if next_words >= 6 and not next_text.strip().endswith("?"):
                value += 2

    if BAD.search(text):
        value -= 8

    return value


def format_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"



def _discover_story_units(segments, gap_seconds=1.5):
    """Discover contiguous narrative units from transcript continuity."""
    if not segments:
        return []

    units = []
    unit_start = 0

    for index in range(1, len(segments)):
        previous_end = float(segments[index - 1]["end"])
        current_start = float(segments[index]["start"])

        if current_start - previous_end > gap_seconds:
            units.append((unit_start, index - 1))
            unit_start = index

    units.append((unit_start, len(segments) - 1))
    return units


def _candidate_windows_in_story_unit(
    segments,
    unit_start,
    unit_end,
    min_seconds=30.0,
    max_seconds=90.0,
):
    """Generate safe 30–90s candidate windows inside one Story Unit."""
    unit_segments = segments[unit_start : unit_end + 1]

    if not unit_segments:
        return []

    safe_starts = _safe_start_boundaries(unit_segments)
    windows = []

    for relative_start in safe_starts:
        candidate_start = float(relative_start)

        start_index = None
        for index, segment in enumerate(unit_segments):
            if abs(float(segment["start"]) - candidate_start) < 0.001:
                start_index = index
                break

        if start_index is None:
            continue

        for relative_end in range(start_index, len(unit_segments)):
            candidate_end = _safe_end_for_terminal(
                unit_segments,
                relative_end,
            )

            duration = candidate_end - candidate_start

            if duration < min_seconds:
                continue

            if duration > max_seconds:
                break

            windows.append(
                (
                    round(candidate_start, 3),
                    round(candidate_end, 3),
                    round(duration, 3),
                )
            )

    return windows


def _candidate_text(segments, start, end):
    parts = []

    for segment in segments:
        segment_start = float(segment["start"])
        segment_end = float(segment["end"])

        if segment_end <= start:
            continue

        if segment_start >= end:
            break

        text = str(segment.get("text", "")).strip()

        if text:
            parts.append(text)

    return " ".join(parts)


def _structural_candidate_score(segments, start, end):
    """Structural ranking only. Never a viral score."""
    duration = end - start
    text = _candidate_text(segments, start, end)

    score = 0.0

    if 30.0 <= duration <= 90.0:
        score += 2.0

    if re.search(r"[.!?]\s*$", text):
        score += 1.0

    if re.search(
        r"\b(kenapa|mengapa|ternyata|tapi|namun|justru|sebenarnya|"
        r"masalahnya|alasannya|akhirnya|bayangkan|kalau)\b",
        text,
        re.IGNORECASE,
    ):
        score += 1.0

    if re.search(
        r"\b(saya|aku|kami|kita|pernah|merasa|takut|sedih|malu|"
        r"gagal|berhasil|menyesal|bingung|marah|bahagia)\b",
        text,
        re.IGNORECASE,
    ):
        score += 0.75

    return round(score, 3)


def find_candidates(transcript_text, duration_minutes=None):
    """M2 Story Discovery -> M3 structural 30–90s candidate gate."""
    segments = parse(transcript_text)

    if not segments:
        return []

    story_units = _discover_story_units(segments)
    candidates = []
    seen = set()

    for unit_id, (unit_start, unit_end) in enumerate(
        story_units,
        start=1,
    ):
        windows = _candidate_windows_in_story_unit(
            segments,
            unit_start,
            unit_end,
            min_seconds=30.0,
            max_seconds=90.0,
        )

        for candidate_start, candidate_end, duration in windows:
            key = (candidate_start, candidate_end)

            if key in seen:
                continue

            seen.add(key)

            candidates.append(
                {
                    "story_unit": unit_id,
                    "story_unit_start": round(
                        float(segments[unit_start]["start"]),
                        3,
                    ),
                    "story_unit_end": round(
                        float(segments[unit_end]["end"]),
                        3,
                    ),
                    "candidate_start": candidate_start,
                    "candidate_end": candidate_end,
                    "candidate_duration": duration,
                    "context_start": candidate_start,
                    "context_end": candidate_end,
                    "score": _structural_candidate_score(
                        segments,
                        candidate_start,
                        candidate_end,
                    ),
                    "text": _candidate_text(
                        segments,
                        candidate_start,
                        candidate_end,
                    ),
                    "prefilter_marker": {
                        "start": candidate_start,
                        "end": candidate_end,
                        "duration": duration,
                    },
                }
            )

    candidates.sort(
        key=lambda item: (
            item["story_unit"],
            item["candidate_start"],
            -item["score"],
        )
    )

    deduped = []

    for candidate in candidates:
        duplicate = False

        for existing in deduped:
            if candidate["story_unit"] != existing["story_unit"]:
                continue

            overlap_start = max(
                candidate["candidate_start"],
                existing["candidate_start"],
            )

            overlap_end = min(
                candidate["candidate_end"],
                existing["candidate_end"],
            )

            overlap = max(0.0, overlap_end - overlap_start)

            shorter = min(
                candidate["candidate_end"]
                - candidate["candidate_start"],
                existing["candidate_end"]
                - existing["candidate_start"],
            )

            if shorter > 0 and overlap / shorter >= 0.60:
                duplicate = True
                break

        if not duplicate:
            deduped.append(candidate)

    limit = (
        max(20, int(duration_minutes * 1.5))
        if duration_minutes
        else 80
    )

    return deduped[:limit]


def group_candidates(candidates):
    """Group candidates by Story Unit, not transitive overlap."""
    groups = {}

    for candidate in candidates:
        unit_id = candidate.get("story_unit", 0)
        groups.setdefault(unit_id, []).append(candidate)

    ordered = []

    for unit_id, group in sorted(groups.items()):
        group.sort(
            key=lambda item: (
                item["candidate_start"],
                item["candidate_end"],
            )
        )
        ordered.append(group)

    return ordered


def build_gemini_prompt(video_url, groups):
    """Build the M4 AI Validator prompt."""
    lines = [
        "Kamu adalah M4 — AI Validator untuk memilih momen video yang berpotensi menjadi klip pendek.",
        "",
        "ARSITEKTUR PIPELINE:",
        "M2 menemukan Story Unit berdasarkan kesinambungan cerita.",
        "M3 hanya melakukan structural gate dan menghasilkan kandidat aman.",
        "M4 adalah satu-satunya tahap yang menilai potensi viral.",
        "",
        "ATURAN M3:",
        "- Kandidat wajib 30–90 detik.",
        "- 30–90 detik adalah GATE, bukan target durasi.",
        "- Jangan memaksakan 45 detik.",
        "- START tidak boleh memotong kalimat atau mid-thought.",
        "- Hindari opening, basa-basi, dan filler jika tersedia batas aman yang lebih baik.",
        "- END tidak boleh memotong kalimat.",
        "- END harus mempertahankan payoff/reveal/result bila diperlukan.",
        "",
        "ATURAN M4:",
        "- Evaluasi SETIAP kandidat.",
        "- Jangan menggunakan label STRONG / WEAK / REJECT.",
        "- Berikan VIRAL SCORE 0–100 untuk setiap kandidat.",
        "- Story completeness lebih penting daripada durasi.",
        "- Periksa hook pada 3 detik pertama.",
        "- Periksa keamanan START.",
        "- Periksa keamanan END.",
        "- Nilai engagement dan potensi diskusi sehat.",
        "- Nilai relatability.",
        "- Nilai surprising/counterintuitive element.",
        "- Nilai emotional/vulnerable element jika memang ada.",
        "- Jangan mengarang isi video.",
        "",
        "FORMAT EVALUASI:",
        "GROUP N:",
        "CANDIDATE M:",
        "START: HH:MM:SS.xxx",
        "END: HH:MM:SS.xxx",
        "DURASI: xx.x detik",
        "VIRAL SCORE: 0–100",
        "HOOK ≤3 DETIK: ...",
        "STORY COMPLETENESS: ...",
        "START SAFETY: ...",
        "END SAFETY: ...",
        "ENGAGEMENT: ...",
        "RELATABLE: ...",
        "SURPRISING / COUNTERINTUITIVE: ...",
        "EMOTIONAL / VULNERABLE: ...",
        "ALASAN: ...",
        "KUTIPAN AWAL: exact quote",
        "KUTIPAN AKHIR: exact quote",
        "",
        "Evaluasi SEMUA kandidat sebelum menentukan kandidat final.",
        "Jangan memilih hanya karena durasinya mendekati angka tertentu.",
        "Jika tidak ada kandidat yang memenuhi standar cerita dan kualitas, keluarkan tepat:",
        "TIDAK ADA KLIP LAYAK",
        "dan jangan keluarkan command yt-dlp.",
        "",
        "Jika ada kandidat final, keluarkan SATU command yt-dlp.",
        "Satu URL/invocation saja.",
        'Gunakan -f "bv[vcodec^=avc1]+ba[acodec^=mp4a]/b[ext=mp4]"',
        "--merge-output-format mp4",
        "Output: /storage/emulated/0/Movies/GenClip/",
        "",
        "VIDEO:",
        video_url,
        "",
        "KANDIDAT M3:",
    ]

    for group_number, group in enumerate(groups, start=1):
        lines.append(f"GROUP {group_number}")

        for candidate_number, candidate in enumerate(group, start=1):
            lines.extend(
                [
                    f"CANDIDATE {candidate_number}",
                    f"START: {candidate['candidate_start']:.3f}",
                    f"END: {candidate['candidate_end']:.3f}",
                    f"DURASI: {candidate['candidate_duration']:.1f}",
                    f"STORY UNIT: {candidate['story_unit']}",
                    f"STRUCTURAL SCORE: {candidate['score']:.3f}",
                    f"TEXT: {candidate['text']}",
                ]
            )

    return "\n".join(lines)

