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
    r"""[.!](?:['")\]]*)$"""
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


def build_prefilter_marker(segments, anchor_start, anchor_end):
    safe_starts = []
    safe_ends = []

    if segments:
        safe_starts.append(round(segments[0]["start"], 3))

    for index, segment in enumerate(segments):
        if not is_terminal_boundary(segment["text"]):
            continue

        terminal_end = round(segment["end"], 3)
        safe_ends.append(terminal_end)

        # Transcript segments can overlap. The next segment by list index
        # may start before the terminal sentence has actually ended, which
        # would create a START boundary inside the same spoken thought.
        next_start = next(
            (
                candidate["start"]
                for candidate in segments[index + 1:]
                if candidate["start"] >= segment["end"] - 1e-6
            ),
            None,
        )

        if next_start is not None:
            safe_starts.append(round(next_start, 3))

    safe_starts = sorted(set(safe_starts))
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

    for marker_end in end_options:
        duration = marker_end - marker_start

        if duration < 25.0:
            continue

        if duration > 70.0:
            break

        return {
            "start": marker_start,
            "end": marker_end,
            "duration": round(duration, 3),
        }, safe_starts, safe_ends

    return None, safe_starts, safe_ends


def score(segment):
    text = segment["text"]
    words = len(text.split())
    value = 0

    if 8 <= words <= 60:
        value += 2

    if SIGNALS.search(text):
        value += 4

    if "?" in text:
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
        value = score(segment)

        if value <= 0:
            continue

        anchor_start = segment["start"]
        anchor_end = segment["end"]
        anchor_duration = anchor_end - anchor_start

        context_budget = max(
            0.0,
            70.0 - anchor_duration
        )
        before = context_budget / 2.0
        after = context_budget - before

        start = max(0.0, anchor_start - before)
        end = anchor_end + after

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

    lines = [
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
            g_start = min(c["context_start"] for c in group)
            g_end = max(c["context_end"] for c in group)
            lines.append(
                f"--- GROUP {g_idx} ({len(group)} kandidat, Rentang Konteks: {format_time(g_start)} - {format_time(g_end)} / {g_start:.1f}s - {g_end:.1f}s) ---"
            )
            for c in group:
                lines.extend([
                    f"CANDIDATE {c['id']}",
                    f"ANCHOR: {c['anchor_start']:.3f} - {c['anchor_end']:.3f} ({format_time(c['anchor_start'])} - {format_time(c['anchor_end'])})",
                    f"AVAILABLE_CONTEXT: {c['context_start']:.3f} - {c['context_end']:.3f} ({format_time(c['context_start'])} - {format_time(c['context_end'])})",
                    f"PREFILTER_FINAL_MARKER: {c['prefilter_marker'] if c['prefilter_marker'] else 'NONE'}",
                    f"SAFE_START_BOUNDARIES: {c['safe_start_boundaries']}",
                    f"SAFE_END_BOUNDARIES: {c['safe_end_boundaries']}",
                    "TRANSCRIPT:",
                    c.get("text", "").strip(),
                    "",
                ])

    lines.extend([
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
        "",
        "=== ATURAN COMMAND YT-DLP ===",
        "11. Jika ada satu atau lebih clip terpilih, Anda HARUS menghasilkan TEPAT SATU command shell yt-dlp untuk SEMUA clip tersebut.",
        "    Satu response = satu command yt-dlp.",
        "12. Gunakan SATU URL YouTube dan SATU invocation yt-dlp.",
        "13. Untuk SETIAP clip terpilih, gunakan satu:",
        '    --download-sections "*START-END"',
        '    Contoh dua clip: --download-sections "*00:02:46-00:03:16" --download-sections "*00:07:44-00:08:14"',
        "    Jangan membuat command yt-dlp terpisah untuk masing-masing clip.",
        "14. Command WAJIB menggunakan format kompatibel ClipClip:",
        '    -f "bv*[vcodec^=avc1]+ba[acodec^=mp4a]/b[ext=mp4]"',
        '    JANGAN menggunakan "bv*+ba/b" atau "-f 134".',
        "15. Command WAJIB menggunakan:",
        "    --merge-output-format mp4",
        "16. Output diarahkan ke:",
        "    /storage/emulated/0/Movies/GenClip/",
        "17. Kontrak Filename:",
        '    - JANGAN mengandalkan "%(title)s" milik YouTube sebagai judul clip.',
        '    - Judul clip yang dibuat Gemini harus menjadi bagian dari nama output.',
        '    - Judul harus disanitasi: Karakter terlarang filesystem / \\ : * ? " < > | TIDAK BOLEH muncul; ganti dengan "_" dan rapikan spasi berlebih.',
        '    - Gunakan pola nama file: JudulClip_START-END.mp4 dengan timestamp section dari yt-dlp agar setiap clip memiliki nama unik dan tidak saling menimpa:',
        '      -o "/storage/emulated/0/Movies/GenClip/[JudulClipSanitasi]_%(section_start)s-%(section_end)s.%(ext)s"',
        "18. Anda HANYA menghasilkan command, BUKAN menjalankannya. Jangan buat command untuk clip yang ditolak.",
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
    ])

    return "\n".join(lines)
