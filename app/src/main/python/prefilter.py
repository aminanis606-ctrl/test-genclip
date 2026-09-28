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


def _build_story_window(segments, anchor_index, min_seconds=25.0, max_seconds=70.0):
    """
    Build a bounded story neighborhood around a scored anchor.

    The anchor remains the lexical signal, while the window represents the
    surrounding story material that Gemini can inspect for setup/payoff.
    Prefer complete transcript segments and natural punctuation boundaries.
    """
    if not segments:
        return 0.0, 0.0

    anchor = segments[anchor_index]
    start = float(anchor["start"])
    end = float(anchor["end"])

    # First expand naturally around the anchor until the minimum useful
    # story duration is reached.
    left = anchor_index
    right = anchor_index

    while end - start < min_seconds:
        expanded = False

        if left > 0:
            previous = segments[left - 1]
            gap = start - float(previous["end"])

            if gap <= 1.5:
                candidate_start = float(previous["start"])
                if end - candidate_start <= max_seconds:
                    left -= 1
                    start = candidate_start
                    expanded = True

        if end - start >= min_seconds:
            break

        if right + 1 < len(segments):
            following = segments[right + 1]
            gap = float(following["start"]) - end

            if gap <= 1.5:
                candidate_end = float(following["end"])
                if candidate_end - start <= max_seconds:
                    right += 1
                    end = candidate_end
                    expanded = True

        if not expanded:
            break

    # Once the minimum is reached, allow a little more context when the
    # next segment completes the current thought, but never exceed 70s.
    while right + 1 < len(segments):
        following = segments[right + 1]
        candidate_end = float(following["end"])
        gap = float(following["start"]) - end

        if gap > 1.5 or candidate_end - start > max_seconds:
            break

        current = segments[right]
        current_text = current["text"].strip()

        # If the current segment does not end terminally, include the next
        # segment because the thought is structurally incomplete.
        if not is_terminal_boundary(current_text):
            right += 1
            end = candidate_end
            continue

        break

    return round(start, 3), round(end, 3)


def _story_window_score(segments, start, end, anchor_score):
    """Score the completeness/signal density of a story neighborhood."""
    window = [
        segment
        for segment in segments
        if segment["end"] >= start and segment["start"] <= end
    ]

    if not window:
        return anchor_score

    score_value = float(anchor_score)

    signal_count = sum(
        1 for segment in window
        if SIGNALS.search(segment["text"])
    )
    financial_count = sum(
        1 for segment in window
        if FINANCIAL_RE.search(segment["text"])
    )
    personal_count = sum(
        1 for segment in window
        if PERSONAL_EXP_RE.search(segment["text"])
    )
    transformation_count = sum(
        1 for segment in window
        if TRANSFORMATION_RE.search(segment["text"])
    )
    problem_solution_count = sum(
        1 for segment in window
        if PROBLEM_SOLUTION_RE.search(segment["text"])
    )

    # Multiple related signals are stronger evidence of a story than one
    # isolated keyword hit.
    score_value += min(signal_count, 4) * 1.5
    score_value += min(financial_count, 2) * 1.0
    score_value += min(personal_count, 2) * 1.0
    score_value += min(transformation_count, 2) * 1.5
    score_value += min(problem_solution_count, 2) * 1.5

    # Reward windows that contain both setup and a later terminal statement.
    if len(window) >= 2:
        if not is_terminal_boundary(window[0]["text"]):
            score_value += 1.0

        if any(is_terminal_boundary(segment["text"]) for segment in window[1:]):
            score_value += 1.0

    duration = end - start

    # A useful story neighborhood should normally fit inside the eventual
    # 25-70 second clip range.
    if 25.0 <= duration <= 70.0:
        score_value += 2.0

    return score_value


def find_candidates(transcript, limit=None):
    segments = parse(transcript)

    if not segments:
        return []

    if limit is None:
        duration_seconds = segments[-1]["end"]
        duration_minutes = duration_seconds / 60.0
        limit = max(20, int(duration_minutes * 1.5))

    raw_candidates = []

    for index, segment in enumerate(segments):
        next_segment = (
            segments[index + 1]
            if index + 1 < len(segments)
            else None
        )

        anchor_score = score(segment, next_segment)

        if anchor_score <= 0:
            continue

        anchor_start = float(segment["start"])
        anchor_end = float(segment["end"])

        story_start, story_end = _build_story_window(
            segments,
            index,
            min_seconds=25.0,
            max_seconds=70.0,
        )

        window_score = _story_window_score(
            segments,
            story_start,
            story_end,
            anchor_score,
        )

        prefilter_marker, safe_starts, safe_ends = (
            build_prefilter_marker(
                segments,
                anchor_start,
                anchor_end,
            )
        )

        raw_candidates.append({
            "anchor_start": anchor_start,
            "anchor_end": anchor_end,
            "context_start": story_start,
            "context_end": story_end,
            "prefilter_marker": prefilter_marker,
            "safe_start_boundaries": safe_starts,
            "safe_end_boundaries": safe_ends,
            "score": window_score,
            "anchor_score": anchor_score,
            "text": "\n".join(
                s["raw"]
                for s in segments
                if s["end"] >= story_start
                and s["start"] <= story_end
            ),
        })

    # Highest-value story neighborhoods first.
    raw_candidates.sort(
        key=lambda item: (
            item["score"],
            item["anchor_score"],
        ),
        reverse=True,
    )

    # Suppress redundant anchors whose story windows substantially overlap.
    # Keep separate windows when they represent genuinely different regions.
    selected = []

    for candidate in raw_candidates:
        overlap = False

        for existing in selected:
            overlap_start = max(
                candidate["context_start"],
                existing["context_start"],
            )
            overlap_end = min(
                candidate["context_end"],
                existing["context_end"],
            )

            if overlap_end <= overlap_start:
                continue

            overlap_duration = overlap_end - overlap_start
            candidate_duration = (
                candidate["context_end"]
                - candidate["context_start"]
            )
            existing_duration = (
                existing["context_end"]
                - existing["context_start"]
            )

            smaller_duration = min(
                candidate_duration,
                existing_duration,
            )

            if smaller_duration > 0 and (
                overlap_duration / smaller_duration >= 0.60
            ):
                overlap = True
                break

        if not overlap:
            selected.append(candidate)

        if len(selected) >= limit:
            break

    # Restore chronological order for stable IDs and grouping.
    selected.sort(
        key=lambda item: item["anchor_start"]
    )

    for index, candidate in enumerate(selected, 1):
        candidate["id"] = index

    return selected


def group_candidates(candidates):
    """Group candidates into transitive overlapping context components."""
    groups = []

    for candidate in candidates:
        overlapping = []

        for index, group in enumerate(groups):
            if any(
                candidate["context_start"] < item["context_end"]
                and candidate["context_end"] > item["context_start"]
                for item in group
            ):
                overlapping.append(index)

        if not overlapping:
            groups.append([candidate])
            continue

        merged = [candidate]

        for index in reversed(overlapping):
            merged.extend(groups.pop(index))

        groups.append(merged)

    # Urutkan kandidat dalam tiap group berdasarkan context_start
    for group in groups:
        group.sort(key=lambda item: item["context_start"])

    # Urutkan groups berdasarkan context_start paling awal
    groups.sort(key=lambda group: min(item["context_start"] for item in group))

    return groups


def build_gemini_prompt(groups, source_url=""):
    # Mendukung input baik berupa hasil group_candidates (list of groups)
    # maupun flat list candidates jika dipanggil secara legacy
    if groups and isinstance(groups, (list, tuple)):
        first = groups[0]
        if isinstance(first, dict):
            groups = group_candidates(groups)
    elif not groups:
        groups = []

    target_url = source_url.strip() if source_url else "<URL_YOUTUBE>"

    # Pindahkan seluruh instruksi Gemini ke PALING ATAS prompt
    lines = [
        "=== ATURAN EVALUASI & VALIDASI ===",
        "1. Evaluasi SETIAP GROUP secara independen dan BERURUTAN mulai dari GROUP 1 sampai GROUP terakhir. Tidak boleh melewati group mana pun.",
        "2. Sebelum membuat daftar clip final, Anda WAJIB menulis satu baris evaluasi untuk SETIAP GROUP dengan format persis:",
        "   GROUP N: STRONG / WEAK / REJECT — alasan singkat",
        "   Arti keputusan:",
        "   - STRONG: Terdapat setidaknya satu kandidat yang berpotensi menjadi clip mandiri yang kuat.",
        "   - WEAK: Ada materi tetapi tidak cukup kuat/mandiri untuk dijadikan clip.",
        "   - REJECT: Tidak layak dijadikan clip.",
        "",
        "3. Setelah seluruh GROUP dievaluasi, susun 'DAFTAR CLIP TERPILIH' hanya dari kandidat yang benar-benar layak.",
        "   Jangan memaksakan jumlah clip tertentu.",
        "4. Jika tidak ada clip yang layak dari SEMUA GROUP:",
        "   - Tulis tepat: TIDAK ADA KLIP LAYAK",
        "   - JANGAN menghasilkan command yt-dlp apa pun.",
        "",
        "=== ATURAN PEMILIHAN CLIP ===",
        "5. Untuk setiap clip terpilih, tentukan:",
        "   - GROUP",
        "   - CANDIDATE",
        "   - START (format HH:MM:SS atau MM:SS)",
        "   - END (format HH:MM:SS atau MM:SS)",
        "   - DURASI",
        "   - JUDUL/TOPIK",
        "   - ALASAN",
        "6. Gunakan URL YouTube sebagai sumber utama. Periksa langsung video pada sekitar timestamp kandidat untuk memahami ucapan, konteks, setup, reveal, result, dan payoff.",
        "   Transcript TIDAK disertakan dalam prompt.",
        "7. START dan END harus dipilih berdasarkan isi video yang benar-benar diperiksa:",
        "   - Tidak memotong kalimat atau pemikiran pembicara.",
        "   - Mencakup setup yang diperlukan dan mencakup explanation/reveal/result/payoff yang diperlukan.",
        "8. Durasi clip valid berada pada rentang 25–70 detik. TIDAK ADA preferred duration.",
        "9. Gunakan prinsip: 'STORY COMPLETENESS > DURATION TARGET'. Kelengkapan cerita selalu lebih penting daripada mengejar angka durasi.",
        "   - Setup yang diperlukan harus tetap masuk.",
        "   - Explanation/reveal/result/payoff harus tetap masuk.",
        "   - Jangan memotong clip yang masih koheren hanya agar durasinya lebih pendek.",
        "   - Jangan memperpanjang clip dengan materi yang tidak diperlukan hanya agar mendekati 70 detik.",
        "10. Jangan memilih kandidat hanya karena ANCHOR-nya memiliki score PREFILTER tinggi. Periksa langsung isi video di sekitar timestamp kandidat.",
        "",
        "=== ATURAN COMMAND YT-DLP ===",
        "16. Jika ada satu atau lebih clip terpilih, Anda HARUS menghasilkan TEPAT SATU command shell yt-dlp untuk SEMUA clip tersebut.",
        "    Satu response = satu command yt-dlp.",
        "17. Gunakan SATU URL YouTube dan SATU invocation yt-dlp.",
        "18. Untuk SETIAP clip terpilih, gunakan satu:",
        '    --download-sections "*START-END"',
        '    Contoh dua clip: --download-sections "*00:02:46-00:03:16" --download-sections "*00:07:44-00:08:14"',
        "    Jangan membuat command yt-dlp terpisah untuk masing-masing clip.",
        "19. Command WAJIB menggunakan format kompatibel ClipClip:",
        '    -f "bv*[vcodec^=avc1]+ba[acodec^=mp4a]/b[ext=mp4]"',
        '    JANGAN menggunakan "bv*+ba/b" atau "-f 134".',
        "20. Command WAJIB menggunakan:",
        "    --merge-output-format mp4",
        "21. Output diarahkan ke:",
        "    /storage/emulated/0/Movies/GenClip/",
        "22. Kontrak Filename:",
        '    - JANGAN mengandalkan "%(title)s" milik YouTube sebagai judul clip.',
        '    - Judul clip yang dibuat Gemini harus menjadi bagian dari nama output.',
        '    - Judul harus disanitasi: Karakter terlarang filesystem / \\ : * ? " < > | TIDAK BOLEH muncul; ganti dengan "_" dan rapikan spasi berlebih.',
        '    - Gunakan pola nama file: JudulClip_START-END.mp4 dengan timestamp section dari yt-dlp agar setiap clip memiliki nama unik dan tidak saling menimpa:',
        '      -o "/storage/emulated/0/Movies/GenClip/[JudulClipSanitasi]_%(section_start)s-%(section_end)s.%(ext)s"',
        "23. Anda HANYA menghasilkan command, BUKAN menjalankannya. Jangan buat command untuk clip yang ditolak.",
        "",
        "=== FORMAT RESPONSE GEMINI ===",
        "Respons Anda HARUS mengikuti urutan berikut:",
        "",
        "EVALUASI GROUP",
        "GROUP 1: STRONG / WEAK / REJECT — [alasan singkat]",
        "GROUP 2: STRONG / WEAK / REJECT — [alasan singkat]",
        "(tuliskan evaluasi satu baris untuk SETIAP GROUP secara berurutan)",
        "",
        "DAFTAR CLIP TERPILIH",
        "(Jika tidak ada klip yang layak dari semua group, tulis TEPAT:)",
        "TIDAK ADA KLIP LAYAK",
        "(Jika ada klip layak, tulis untuk setiap clip terpilih:)",
        "- GROUP: [nomor group]",
        "- CANDIDATE: [id kandidat]",
        "- START: [HH:MM:SS atau MM:SS]",
        "- END: [HH:MM:SS atau MM:SS]",
        "- DURASI: [durasi dalam detik]",
        "- JUDUL/TOPIK: [judul singkat bersih dari karakter ilegal filesystem]",
        "- ALASAN: [alasan singkat]",
        "- KONTEKS: [ringkasan singkat isi yang diperiksa dari video]",
        "",
        "SATU COMMAND YT-DLP",
        "(Hanya jika ada clip terpilih. JANGAN tampilkan bagian ini jika TIDAK ADA KLIP LAYAK)",
        f'yt-dlp --download-sections "*START1-END1" --download-sections "*START2-END2" -f "bv*[vcodec^=avc1]+ba[acodec^=mp4a]/b[ext=mp4]" --merge-output-format mp4 -o "/storage/emulated/0/Movies/GenClip/[JudulClipSanitasi]_%(section_start)s-%(section_end)s.%(ext)s" "{target_url}"',
        "",
        "=== DATA SUMBER ===",
        "URL YouTube:",
        target_url,
        "",
        "=== KELOMPOK KANDIDAT PREFILTER (GROUPS) ===",
        "Kandidat di bawah telah dikelompokkan berdasarkan tumpang tindih waktu/konteks (transitive overlap).",
        "Kandidat dalam satu group harus dinilai bersamaan.",
        "",
    ]

    if not groups:
        lines.append("(Tidak ada kelompok kandidat ditemukan)")
    else:
        for g_idx, group in enumerate(groups, 1):
            lines.append(
                f"--- GROUP {g_idx} ({len(group)} kandidat) ---"
            )

            for c in group:
                lines.append(
                    f"CANDIDATE {c['id']}: START {c['anchor_start']:.3f} | END {c['anchor_end']:.3f}"
                )

            lines.append("")

    final_prompt = "\n".join(lines)

    print(f"[DIAGNOSTIC] total prompt chars={len(final_prompt)}")

    return final_prompt
