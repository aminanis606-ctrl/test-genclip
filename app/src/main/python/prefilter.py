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


def find_candidates(transcript, limit=None):
    segments = parse(transcript)
    if limit is None:
        duration_seconds = segments[-1]["end"] if segments else 0.0
        duration_minutes = duration_seconds / 60.0
        limit = max(20, int(duration_minutes * 1.5))
    candidates = []

    for index, segment in enumerate(segments):
        next_segment = segments[index + 1] if index + 1 < len(segments) else None
        value = score(segment, next_segment)

        if value <= 0:
            continue

        anchor_start = segment["start"]
        anchor_end = segment["end"]
        anchor_duration = anchor_end - anchor_start

        start, end = _build_structural_context(
            segments,
            index,
            max_seconds=120.0,
        )

        prefilter_marker, safe_starts, safe_ends = (
            build_prefilter_marker(
                segments,
                anchor_start,
                anchor_end,
            )
        )

        if prefilter_marker:
            start = min(
                start,
                prefilter_marker["start"]
            )
            end = max(
                end,
                prefilter_marker["end"]
            )

        context = [
            s for s in segments
            if s["end"] >= start and s["start"] <= end
        ]

        candidates.append({
            "anchor_start": anchor_start,
            "anchor_end": anchor_end,
            "context_start": start,
            "context_end": end,
            "prefilter_marker": prefilter_marker,
            "safe_start_boundaries": safe_starts,
            "safe_end_boundaries": safe_ends,
            "score": value,
            "text": "\n".join(
                s["raw"] for s in context
            ),
        })

    candidates.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    # Ambil top kandidat hingga limit=20 tanpa membuang karena overlap
    selected = candidates[:limit]

    # Urutkan secara kronologis
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
        "   - KUTIPAN AWAL",
        "   - KUTIPAN AKHIR",
        "6. KUTIPAN AWAL dan KUTIPAN AKHIR HARUS dikutip persis dari teks 'TRANSCRIPT' yang diberikan dalam prompt. JANGAN mengarang kutipan.",
        "   Kutipan awal membuktikan titik START alami, dan kutipan akhir membuktikan titik END alami.",
        "7. START dan END harus:",
        "   - Berada di dalam AVAILABLE_CONTEXT kandidat terkait.",
        "   - Tidak memotong kalimat dan tidak memotong pemikiran pembicara.",
        "   - Mencakup setup yang diperlukan dan mencakup explanation/reveal/result/payoff yang diperlukan.",
        "8. Durasi clip valid berada pada rentang 25–70 detik. TIDAK ADA preferred duration.",
        "9. Gunakan prinsip: 'STORY COMPLETENESS > DURATION TARGET'. Kelengkapan cerita selalu lebih penting daripada mengejar angka durasi.",
        "   - Setup yang diperlukan harus tetap masuk.",
        "   - Explanation/reveal/result/payoff harus tetap masuk.",
        "   - Jangan memotong clip yang masih koheren hanya agar durasinya lebih pendek.",
        "   - Jangan memperpanjang clip dengan materi yang tidak diperlukan hanya agar mendekati 70 detik.",
        "10. Jangan memilih kandidat hanya karena ANCHOR-nya memiliki score PREFILTER tinggi. Transcript dan konteks tetap menjadi dasar keputusan.",
        "11. PREFILTER_FINAL_MARKER adalah baseline deterministic dari PREFILTER dan harus dibandingkan dengan keputusan Gemini.",
        "12. SAFE_START_BOUNDARIES dan SAFE_END_BOUNDARIES adalah batas waktu yang diizinkan.",
        "13. START HARUS sama persis dengan salah satu SAFE_START_BOUNDARIES.",
        "14. END HARUS sama persis dengan salah satu SAFE_END_BOUNDARIES.",
        "15. Jangan membuat START atau END di luar boundary yang diberikan, meskipun secara semantik terlihat lebih baik.",
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
        "- KUTIPAN AWAL: \"[kutipan persis dari transcript di titik START]\"",
        "- KUTIPAN AKHIR: \"[kutipan persis dari transcript di titik END]\"",
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

    total_raw_transcript_chars = 0
    total_deduped_transcript_chars = 0

    if not groups:
        lines.append("(Tidak ada kelompok kandidat ditemukan)")
    else:
        for g_idx, group in enumerate(groups, 1):
            g_start = min(c["context_start"] for c in group)
            g_end = max(c["context_end"] for c in group)
            lines.append(
                f"--- GROUP {g_idx} ({len(group)} kandidat, Rentang Konteks: {format_time(g_start)} - {format_time(g_end)} / {g_start:.1f}s - {g_end:.1f}s) ---"
            )

            # Metadata candidate dibuat ringkas, satu baris
            raw_group_chars = 0
            unique_segments = {}

            for c in group:
                lines.append(
                    f"CANDIDATE {c['id']}: ANCHOR {c['anchor_start']:.3f}-{c['anchor_end']:.3f} | AVAILABLE_CONTEXT {c['context_start']:.3f}-{c['context_end']:.3f} | PREFILTER_FINAL_MARKER {c.get('prefilter_marker') if c.get('prefilter_marker') else 'NONE'} | SAFE_START_BOUNDARIES {c.get('safe_start_boundaries', [])} | SAFE_END_BOUNDARIES {c.get('safe_end_boundaries', [])}"
                )
                c_text = c.get("text", "").strip()
                raw_group_chars += len(c_text)

                for line in c_text.splitlines():
                    line_clean = line.strip()
                    if not line_clean:
                        continue
                    m = SEGMENT_RE.match(line_clean)
                    if m:
                        key = (float(m.group(1)), float(m.group(2)), m.group(3).strip())
                        if key not in unique_segments:
                            unique_segments[key] = (key[0], key[1], line_clean)
                    else:
                        key = (0.0, 0.0, line_clean)
                        if key not in unique_segments:
                            unique_segments[key] = (0.0, 0.0, line_clean)

            # Satu timeline TRANSCRIPT deduplicated per GROUP, diurutkan berdasarkan start
            sorted_segments = sorted(unique_segments.values(), key=lambda x: (x[0], x[1]))
            deduped_text = "\n".join(seg[2] for seg in sorted_segments)
            deduped_group_chars = len(deduped_text)

            total_raw_transcript_chars += raw_group_chars
            total_deduped_transcript_chars += deduped_group_chars

            # Diagnostic karakter transcript per GROUP
            print(
                f"[DIAGNOSTIC] GROUP {g_idx}: "
                f"chars transcript sebelum dedup={raw_group_chars}, "
                f"chars sesudah dedup={deduped_group_chars}"
            )

            lines.extend([
                "TRANSCRIPT:",
                deduped_text,
                "",
            ])

    final_prompt = "\n".join(lines)

    # Diagnostic total prompt chars
    print(
        f"[DIAGNOSTIC] total prompt chars={len(final_prompt)} "
        f"(total transcript sebelum dedup={total_raw_transcript_chars}, "
        f"sesudah dedup={total_deduped_transcript_chars})"
    )

    return final_prompt
