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

OPENING_RE = re.compile(
    r"\b(sebelum video|video ini dimulai|selamat datang|welcome|qr code|subscribe|like|follow|website)\b",
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


def _token_set(text):
    stopwords = {
        "yang", "dan", "dari", "dengan", "untuk", "atau", "ini", "itu",
        "jadi", "kan", "aku", "saya", "lu", "gua", "kita", "dia", "ada",
        "apa", "nih", "ya", "lah", "kok", "tuh", "si", "ke", "di", "pada",
        "nya", "gue", "bang", "oke", "the", "and", "for", "with", "that",
        "this", "you", "are", "was", "but",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9áéíóúü]+", str(text).lower())
        if len(token) > 2 and token not in stopwords
    }


def _lexical_overlap(left_text, right_text):
    left = _token_set(left_text)
    right = _token_set(right_text)

    if not left:
        return 1.0

    return len(left & right) / len(left)


def _safe_end_for_terminal(segments, index):
    """
    Keep a terminal boundary, extending only through overlapping ASR cues
    that are lexically duplicative. Stop when overlapping text introduces
    new content.
    """
    boundary = float(segments[index]["end"])
    base_text = segments[index]["text"]

    for later in segments[index + 1:]:
        later_start = float(later["start"])
        later_end = float(later["end"])

        if later_start >= boundary - 1e-6:
            break

        if later_end <= boundary + 1e-6:
            continue

        if _lexical_overlap(base_text, later["text"]) >= 0.45:
            boundary = max(boundary, later_end)
            continue

        break

    return round(boundary, 3)


def _safe_end_boundaries(segments):
    safe_ends = []

    for index, segment in enumerate(segments):
        if not is_terminal_boundary(segment["text"]):
            continue

        boundary = _safe_end_for_terminal(segments, index)

        if boundary > float(segment["start"]):
            safe_ends.append(boundary)

    return sorted(set(safe_ends))


def _safe_start_boundaries(segments):
    """
    For overlapping ASR subtitles, a safe START is the first cue beginning
    at or after a verified terminal boundary. Do not require the new cue to
    be outside the entire overlap chain.
    """
    if not segments:
        return []

    safe_ends = _safe_end_boundaries(segments)
    safe_starts = [round(float(segments[0]["start"]), 3)]

    for boundary in safe_ends:
        for segment in segments:
            if float(segment["start"]) >= boundary - 1e-6:
                safe_starts.append(round(float(segment["start"]), 3))
                break

    return sorted(set(safe_starts))


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



def _topic_similarity(left_segments, right_segments):
    left_counts = {}
    right_counts = {}

    for segment in left_segments:
        for token in _token_set(segment["text"]):
            left_counts[token] = left_counts.get(token, 0) + 1

    for segment in right_segments:
        for token in _token_set(segment["text"]):
            right_counts[token] = right_counts.get(token, 0) + 1

    if not left_counts or not right_counts:
        return 0.0

    dot = sum(
        left_counts[token] * right_counts.get(token, 0)
        for token in left_counts
    )

    left_norm = sum(
        value * value for value in left_counts.values()
    ) ** 0.5

    right_norm = sum(
        value * value for value in right_counts.values()
    ) ** 0.5

    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0

    return dot / (left_norm * right_norm)


def _discover_story_units(segments, window_size=8):
    """
    M2 Story Discovery.

    Detect local lexical-cohesion valleys, then snap each topic boundary
    forward to a safe transcript START. This discovers structural story
    units; it does not score virality and does not impose a duration target.
    """
    if not segments:
        return []

    safe_starts = _safe_start_boundaries(segments)
    safe_ends = _safe_end_boundaries(segments)

    if not safe_starts or not safe_ends:
        return [(0, len(segments) - 1)]

    if len(segments) < (window_size * 2) + 1:
        return [(0, len(segments) - 1)]

    scores = []

    for index in range(
        window_size,
        len(segments) - window_size,
    ):
        left = segments[index - window_size:index]
        right = segments[index:index + window_size]

        scores.append(
            {
                "index": index,
                "similarity": _topic_similarity(left, right),
            }
        )

    if len(scores) < 3:
        return [(0, len(segments) - 1)]

    mean = sum(
        item["similarity"] for item in scores
    ) / len(scores)

    variance = sum(
        (item["similarity"] - mean) ** 2
        for item in scores
    ) / len(scores)

    threshold = mean - (1.5 * (variance ** 0.5))

    boundary_starts = [safe_starts[0]]

    for position in range(1, len(scores) - 1):
        current = scores[position]
        previous = scores[position - 1]
        following = scores[position + 1]

        if current["similarity"] > threshold:
            continue

        if current["similarity"] > previous["similarity"]:
            continue

        if current["similarity"] > following["similarity"]:
            continue

        raw_start = float(
            segments[current["index"]]["start"]
        )

        snapped = next(
            (
                value
                for value in safe_starts
                if value >= raw_start - 1e-6
            ),
            safe_starts[-1],
        )

        if snapped <= boundary_starts[-1] + 1e-6:
            continue

        boundary_starts.append(snapped)

    boundary_starts = sorted(set(boundary_starts))

    if boundary_starts[-1] != safe_starts[-1]:
        boundary_starts.append(safe_starts[-1])

    units = []

    for unit_number, start in enumerate(boundary_starts):
        if unit_number + 1 < len(boundary_starts):
            next_start = boundary_starts[unit_number + 1]

            candidate_ends = [
                value
                for value in safe_ends
                if value < next_start - 1e-6
            ]

            end_time = (
                candidate_ends[-1]
                if candidate_ends
                else None
            )
        else:
            end_time = safe_ends[-1]

        if end_time is None or end_time <= start:
            continue

        unit_start = next(
            (
                index
                for index, segment in enumerate(segments)
                if abs(
                    float(segment["start"]) - start
                ) < 0.001
            ),
            None,
        )

        unit_end = None

        for index, segment in enumerate(segments):
            if float(segment["end"]) <= end_time + 1e-6:
                unit_end = index

        if (
            unit_start is None
            or unit_end is None
            or unit_end < unit_start
        ):
            continue

        units.append((unit_start, unit_end))

    return units or [(0, len(segments) - 1)]


def _candidate_windows_in_story_unit(
    segments,
    unit_start,
    unit_end,
    min_seconds=30.0,
    max_seconds=90.0,
):
    """Generate all structurally safe 30–90s windows in one Story Unit."""
    unit_segments = segments[unit_start : unit_end + 1]

    if not unit_segments:
        return []

    safe_starts = _safe_start_boundaries(unit_segments)
    safe_ends = _safe_end_boundaries(unit_segments)

    windows = []

    for candidate_start in safe_starts:
        for candidate_end in safe_ends:
            if candidate_end <= candidate_start:
                continue

            duration = candidate_end - candidate_start

            if duration < min_seconds:
                continue

            if duration > max_seconds:
                continue

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

            text = _candidate_text(
                segments,
                candidate_start,
                candidate_end,
            )

            if (
                abs(
                    candidate_start
                    - float(segments[0]["start"])
                ) < 0.001
                and OPENING_RE.search(text[:500])
            ):
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
                    "text": text,
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
            overlap = max(
                0.0,
                overlap_end - overlap_start,
            )

            shorter = min(
                candidate["candidate_duration"],
                existing["candidate_duration"],
            )

            duration_delta = abs(
                candidate["candidate_duration"]
                - existing["candidate_duration"]
            )

            if (
                shorter > 0
                and overlap / shorter >= 0.85
                and duration_delta <= 8.0
            ):
                duplicate = True
                break

        if not duplicate:
            deduped.append(candidate)

    return deduped


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
    """Build the AI Validator prompt."""
    lines = [
        "Kamu adalah AI Validator untuk memvalidasi dan memilih momen-momen video terbaik yang layak dijadikan klip pendek.",
        "TUGAS & ATURAN Analisis Audio & Transkrip: Gunakan kemampuanmu untuk menarik transkrip dan analisis mendalam, membaca timestamp, dan MENDENGARKAN AUDIO video. Jangan gunakan elemen visual.",
        "1. Validasi Kritis: JANGAN jadikan STRUCTURAL SCORE pada prompt sebagai patokan mati. Kamu WAJIB menarik transkrip video dan memvalidasi ulang sendiri apakah kandidat tersebut benar-benar memiliki cerita yang utuh, menarik, dan aman.",
        "2. Pilih Semua yang Layak: Pilih SEMUA kandidat yang memenuhi syarat. Tidak dibatasi hanya satu.",
        "3. Filter Overlap: Banyak kandidat yang durasinya tumpang tindih (overlapping) di momen yang sama. Untuk setiap adegan/momen yang berdekatan, pilih HANYA SATU kandidat dengan batas START dan END paling sempurna (kalimat tidak terpotong, cerita tuntas).",
        "4. Kriteria Kelolosan:",
        "   * Story completeness (Cerita utuh/tidak menggantung).",
        "   * Hook awal menarik.",
        "   * Start/End safety (Tidak memotong kata/kalimat orang berbicara).",
        "   * Bebas intro, sponsor, CTA, salam pembuka, dsb.",
        "FORMAT OUTPUT YANG DIIZINKAN (Jangan gunakan format evaluasi panjang, cukup keluarkan format di bawah ini):",
        "KLIP YANG LOLOS VALIDASI:",
        " * [Group X, Candidate Y] | [START - END] | Alasan: [1 kalimat singkat alasan potongan ini utuh/pas]",
        " * [Group X, Candidate Y] | [START - END] | Alasan: [1 kalimat singkat alasan potongan ini utuh/pas]",
        "   (Lanjutkan sesuai jumlah klip yang lolos...)",
        "COMMAND YT-DLP:",
        "Keluarkan HANYA SATU command yt-dlp yang menggabungkan semua klip terpilih menggunakan multiple --download-sections.",
        "",
        'yt-dlp "[URL_VIDEO]" \\',
        '--download-sections "*[START1]-[END1]" \\',
        '--download-sections "*[START2]-[END2]" \\',
        '*(tambahkan sesuai jumlah klip terpilih)* \\',
        "--force-keyframes-at-cuts \\",
        '-f "bv[vcodec^=avc1]+ba[acodec^=mp4a]/b[ext=mp4]" \\',
        "--merge-output-format mp4 \\",
        '-o "/storage/emulated/0/Movies/GenClip/[JudulClipSanitasi]_%(section_start)s-%(section_end)s.%(ext)s"',
        "",
        "VIDEO:",
        video_url,
        "",
        "KANDIDAT M3:",
    ]

    for group_number, group in enumerate(groups, start=1):
        for candidate_number, candidate in enumerate(group, start=1):
            lines.append(
                f"G{group_number} C{candidate_number} | "
                f"{candidate['candidate_start']:.3f}-{candidate['candidate_end']:.3f} | "
                f"{candidate['candidate_duration']:.1f}s | "
                f"SCORE {candidate['score']:.3f}"
            )

    return "\n".join(lines)
