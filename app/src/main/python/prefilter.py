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

HARD_CONTINUATION_RE = re.compile(
    r"^\s*(?:"
    r"karena|sehingga|maka|yang|dan|tetapi|tapi|atau|kalau|jika|bila|"
    r"meskipun|walaupun|agar|supaya|hingga|sampai|sejak|selama|"
    r"melainkan|padahal|kecuali"
    r")\b",
    re.IGNORECASE,
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

    if not left or not right:
        return 0.0

    return len(left & right) / len(left)


def _safe_end_for_terminal(segments, index):
    terminal_start = float(segments[index]["start"])
    boundary = float(segments[index]["end"])
    accumulated_text = segments[index]["text"]

    prior_overlap = [
        segment
        for segment in segments[:index]
        if (
            float(segment["start"]) < terminal_start - 1e-6
            and float(segment["end"]) > terminal_start + 1e-6
            and float(segment["end"]) > boundary + 1e-6
        )
    ]

    if prior_overlap:
        prior = max(
            prior_overlap,
            key=lambda segment: (
                float(segment["start"]),
                float(segment["end"]),
            ),
        )
        boundary = float(prior["end"])

    for later in segments[index + 1:]:
        later_start = float(later["start"])
        later_end = float(later["end"])

        if later_start >= boundary - 1e-6:
            break

        if later_end <= boundary + 1e-6:
            accumulated_text = f"{accumulated_text} {later['text']}"
            continue

        if _lexical_overlap(accumulated_text, later["text"]) >= 0.45:
            boundary = max(boundary, later_end)
            accumulated_text = f"{accumulated_text} {later['text']}"
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


def _is_valid_start(text):
    return not HARD_CONTINUATION_RE.match(str(text).strip())


def _safe_start_boundaries(segments):
    if not segments:
        return []

    safe_ends = _safe_end_boundaries(segments)
    safe_starts = []

    if _is_valid_start(segments[0].get("text", "")):
        safe_starts.append(round(float(segments[0]["start"]), 3))

    for boundary in safe_ends:
        for index, segment in enumerate(segments):
            candidate_start = float(segment["start"])

            if candidate_start < boundary - 1e-6:
                continue

            previous = None
            for earlier in segments[:index]:
                if (
                    float(earlier["start"]) < candidate_start - 1e-6
                    and float(earlier["end"]) > candidate_start + 1e-6
                ):
                    previous = earlier

            if previous is not None:
                previous_text = str(previous.get("text", "")).strip()

                if not is_terminal_boundary(previous_text):
                    continue

            if not _is_valid_start(segment.get("text", "")):
                continue

            safe_starts.append(round(candidate_start, 3))
            break

    return sorted(set(safe_starts))


def _build_structural_context(segments, start_time, end_time, padding=30.0):
    if not segments:
        return 0.0, 0.0

    min_time = float(segments[0]["start"])
    max_time = float(segments[-1]["end"])

    context_start = max(min_time, start_time - padding)
    context_end = min(max_time, end_time + padding)

    return round(context_start, 3), round(context_end, 3)


def build_prefilter_marker(segments, anchor_start, anchor_end):
    safe_starts = _safe_start_boundaries(segments)
    safe_ends = []

    for index, segment in enumerate(segments):
        if not is_terminal_boundary(segment["text"]):
            continue

        terminal_end = _safe_end_for_terminal(segments, index)

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


def format_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _candidate_windows(
    segments,
    min_seconds=30.0,
    max_seconds=90.0,
):
    if not segments:
        return []

    safe_starts = _safe_start_boundaries(segments)
    safe_ends = _safe_end_boundaries(segments)

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

        if segment_start < start - 1e-6:
            continue

        if segment_start >= end:
            break

        if segment_end <= start:
            continue

        text = str(segment.get("text", "")).strip()

        if text:
            parts.append(text)

    return " ".join(parts)


def _structural_candidate_score(segments, start, end):
    duration = end - start
    text = _candidate_text(segments, start, end)

    score_val = 0.0

    if 30.0 <= duration <= 90.0:
        score_val += 2.0

    if is_terminal_boundary(text):
        score_val += 1.0

    if SIGNALS.search(text):
        score_val += 2.0

    if BAD.search(text):
        score_val -= 5.0

    return round(score_val, 3)


def find_candidates(transcript_text, limit=None, audio_path=None):
    """
    Search across entire transcript for non-overlapping candidate story moments (30-90s).
    Keyword/signals are indicators, not strict prerequisites.
    Preserves 100% backward compatibility for legacy positional arguments find_candidates(text, limit).
    """
    if isinstance(limit, str) and audio_path is None:
        audio_path, limit = limit, None

    segments = parse(transcript_text)

    if not segments:
        return []

    windows = _candidate_windows(
        segments,
        min_seconds=30.0,
        max_seconds=90.0,
    )

    candidates = []
    seen = set()

    for candidate_start, candidate_end, duration in windows:
        key = (candidate_start, candidate_end)

        if key in seen:
            continue

        text = _candidate_text(
            segments,
            candidate_start,
            candidate_end,
        )

        if BAD.search(text[:200]):
            continue

        seen.add(key)

        score_val = _structural_candidate_score(
            segments,
            candidate_start,
            candidate_end,
        )

        context_start, context_end = _build_structural_context(
            segments,
            candidate_start,
            candidate_end,
            padding=30.0,
        )

        safe_starts = _safe_start_boundaries(
            [s for s in segments if s["end"] >= context_start and s["start"] <= context_end]
        )
        safe_ends = _safe_end_boundaries(
            [s for s in segments if s["end"] >= context_start and s["start"] <= context_end]
        )

        audio_ev = None
        if audio_path:
            try:
                from audio_analysis import analyze_audio_segment
                audio_ev = analyze_audio_segment(
                    audio_path,
                    candidate_start,
                    candidate_end,
                )
            except Exception as e:
                audio_ev = {
                    "start": candidate_start,
                    "end": candidate_end,
                    "duration": duration,
                    "audio_present": True,
                    "status": "decode_failed",
                    "rms_db": None,
                    "peak_db": None,
                    "speech_ratio": None,
                    "silence_ratio": None,
                    "pause_count": None,
                    "summary": f"Audio [{candidate_start:.1f}s - {candidate_end:.1f}s]: decode failed ({str(e)})",
                }

        candidates.append(
            {
                "anchor_start": candidate_start,
                "anchor_end": candidate_end,
                "context_start": context_start,
                "context_end": context_end,
                "candidate_start": candidate_start,
                "candidate_end": candidate_end,
                "candidate_duration": duration,
                "prefilter_marker": {
                    "start": candidate_start,
                    "end": candidate_end,
                    "duration": duration,
                },
                "safe_start_boundaries": safe_starts,
                "safe_end_boundaries": safe_ends,
                "score": score_val,
                "text": text,
                "audio_evidence": audio_ev,
            }
        )

    # Sort by candidate_start chronologically
    candidates.sort(
        key=lambda item: (
            item["candidate_start"],
            item["candidate_end"],
        )
    )

    # Preserve all valid candidates.
    # Overlap is handled later by grouping; it must not cause recall loss here.
    for index, candidate in enumerate(candidates, start=1):
        candidate["id"] = index

    return candidates


def group_candidates(candidates):
    """Group candidates into transitive overlapping context components."""
    if not candidates:
        return []

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

    for group in groups:
        group.sort(key=lambda item: item["context_start"])

    groups.sort(key=lambda group: min(item["context_start"] for item in group))

    return groups


def build_gemini_prompt(source_url, groups):
    """
    Build prompt for AI validation.
    Accepts (source_url, groups) or (groups, source_url) for compatibility.
    """
    if isinstance(source_url, (list, tuple)):
        source_url, groups = groups if isinstance(groups, str) else "", source_url

    if groups and isinstance(groups, (list, tuple)):
        first = groups[0]
        if isinstance(first, dict):
            groups = group_candidates(groups)
    elif not groups:
        groups = []

    target_url = str(source_url).strip() if source_url else "<URL_YOUTUBE>"

    lines = [
        "=== GENCLIP PROMPT COMPILER ===",
        "Tujuan: Menyiapkan fakta, evidence transkrip, kandidat timestamp, dan instruksi evaluasi untuk LLM eksternal.",
        "",
        "URL YouTube:",
        target_url,
        "",
        "=== FAKTA DAN KONTEKS/EVIDENCE PREFILTER (GROUPS) ===",
        "Kandidat di bawah telah dikelompokkan berdasarkan tumpang tindih waktu/konteks (transitive overlap).",
        "Semua timestamp, batas aman, dan transkrip di bawah adalah fakta/evidence aktual.",
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
                cand_id = c.get("id", 1)
                audio_ev = c.get("audio_evidence")
                audio_summary = (
                    audio_ev.get("summary")
                    if isinstance(audio_ev, dict) and audio_ev.get("summary")
                    else "N/A"
                )
                cand_lines = [
                    f"CANDIDATE {cand_id}",
                    f"ANCHOR: {c['anchor_start']:.3f} - {c['anchor_end']:.3f} ({format_time(c['anchor_start'])} - {format_time(c['anchor_end'])})",
                    f"AVAILABLE_CONTEXT: {c['context_start']:.3f} - {c['context_end']:.3f} ({format_time(c['context_start'])} - {format_time(c['context_end'])})",
                    f"PREFILTER_FINAL_MARKER: {c.get('prefilter_marker', 'NONE')}",
                    f"SAFE_START_BOUNDARIES: {c.get('safe_start_boundaries', [])}",
                    f"SAFE_END_BOUNDARIES: {c.get('safe_end_boundaries', [])}",
                ]
                if audio_summary != "N/A":
                    cand_lines.append(f"AUDIO_EVIDENCE: {audio_summary}")
                cand_lines.extend([
                    f"TEXT: {c.get('text', '')}",
                    "",
                ])
                lines.extend(cand_lines)

    lines.extend([
        "=== INSTRUKSI EVALUASI / HIPOTESIS UNTUK LLM EKSTERNAL ===",
        "1. Analisis Audio & Transkrip: Gunakan kemampuanmu untuk menganalisis transkrip dan MENDENGARKAN AUDIO video untuk mendeteksi intonasi dan jeda napas. ABAIKAN/JANGAN proses elemen visual (frame video) agar pemrosesan lebih cepat.",
        "2. Beri VIRAL SCORE 0–100 untuk SETIAP CANDIDATE berdasarkan kriteria berikut:",
        "   - Hook awal (≤3 detik pertama harus menarik perhatian).",
        "   - Story completeness (kelengkapan cerita/pemikiran utuh, tidak menggantung).",
        "   - Start/end safety (START tidak memotong kalimat/pikiran/ASR overlap; END menjaga payoff).",
        "   - Engagement & Relatability.",
        "   - Surprising/Counterintuitive atau Emotional/Vulnerable.",
        "3. Durasi final WAJIB 30–90 detik. Catatan: 30–90 detik adalah HARD GATE, BUKAN target durasi.",
        "4. START dan END wajib berada di dalam AVAILABLE_CONTEXT kandidat terkait.",
        "5. Bebas dari intro, basa-basi, sponsor, CTA (like/subscribe), dan salam pembuka.",
        "6. Sertakan exact quote: KUTIPAN AWAL dan KUTIPAN AKHIR yang persis ada pada video/transcript.",
        "7. Jika TIDAK ADA kandidat yang benar-benar layak, outputkan: TIDAK ADA KLIP LAYAK.",
        "",
        "=== ATURAN COMMAND YT-DLP ===",
        "8. Jika ada satu atau lebih clip terpilih, Anda HARUS menghasilkan TEPAT SATU command shell yt-dlp untuk SEMUA clip tersebut.",
        "9. Gunakan SATU URL YouTube dan SATU invocation yt-dlp dengan multiple --download-sections.",
        "10. Command WAJIB menggunakan format kompatibel ClipClip:",
        '    -f "bv*[vcodec^=avc1]+ba[acodec^=mp4a]/b[ext=mp4]" --merge-output-format mp4',
        "11. Output diarahkan ke: /storage/emulated/0/Movies/GenClip/[JudulClipSanitasi]_%(section_start)s-%(section_end)s.%(ext)s",
        "12. HANYA hasilkan command, JANGAN jalankan command.",
        "",
        "=== FORMAT RESPONSE GEMINI ===",
        "Respons Anda HARUS mengikuti urutan berikut:",
        "",
        "EVALUASI CANDIDATE",
        "CANDIDATE N: VIRAL SCORE 0-100 — [alasan evaluasi]",
        "(tuliskan evaluasi satu baris untuk SETIAP CANDIDATE)",
        "",
        "DAFTAR CLIP TERPILIH",
        "(Jika tidak ada klip yang layak, tulis TEPAT:)",
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
        f'yt-dlp --force-keyframes-at-cuts --download-sections "*START1-END1" --download-sections "*START2-END2" -f "bv*[vcodec^=avc1]+ba[acodec^=mp4a]/b[ext=mp4]" --merge-output-format mp4 -o "/storage/emulated/0/Movies/GenClip/[JudulClipSanitasi]_%(section_start)s-%(section_end)s.%(ext)s" "{target_url}"',
    ])

    return "\n".join(lines)
