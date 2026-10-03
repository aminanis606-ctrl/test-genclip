import io
import math
import os
import struct
import subprocess
import wave


def _analyze_pcm_bytes(pcm_data, sample_rate=16000):
    if not pcm_data or len(pcm_data) < 2:
        return None

    num_samples = len(pcm_data) // 2
    if num_samples == 0:
        return None

    sum_sq = 0.0
    max_abs = 0

    frame_size = int(sample_rate * 0.02)
    silence_threshold = 327.0  # ~ -40dB relative to 32768
    total_frames = 0
    silence_frames = 0
    pause_frames = 0
    pause_count = 0

    current_frame_sum_sq = 0.0
    current_frame_samples = 0

    for (val,) in struct.iter_unpack("<h", pcm_data[: num_samples * 2]):
        abs_val = abs(val)
        if abs_val > max_abs:
            max_abs = abs_val
        sum_sq += float(val) * float(val)

        current_frame_sum_sq += float(val) * float(val)
        current_frame_samples += 1

        if current_frame_samples >= frame_size:
            frame_rms = math.sqrt(current_frame_sum_sq / current_frame_samples)
            total_frames += 1

            if frame_rms < silence_threshold:
                silence_frames += 1
                pause_frames += 1
                if pause_frames == 15:  # ~300ms pause threshold
                    pause_count += 1
            else:
                pause_frames = 0

            current_frame_sum_sq = 0.0
            current_frame_samples = 0

    rms = math.sqrt(sum_sq / num_samples)

    rms_db = round(20 * math.log10(max(rms, 1e-5) / 32768.0), 1)
    peak_db = round(20 * math.log10(max(max_abs, 1) / 32768.0), 1)

    silence_ratio = round(silence_frames / max(total_frames, 1), 2)
    speech_ratio = round(1.0 - silence_ratio, 2)

    return {
        "rms_db": rms_db,
        "peak_db": peak_db,
        "speech_ratio": speech_ratio,
        "silence_ratio": silence_ratio,
        "pause_count": pause_count,
    }


def _analyze_compressed_frames(frames, start_sec, end_sec, nominal_rate_bytes_per_sec=8000.0):
    if not frames:
        return None

    in_window = [
        f for f in frames
        if (f["start"] + f["duration"]) >= start_sec - 1e-3 and f["start"] <= end_sec + 1e-3
    ]

    if not in_window:
        return None

    silence_count = 0
    pause_frames = 0
    pause_count = 0

    max_amp = 0.0
    total_amp_sq = 0.0

    for f in in_window:
        dur = max(f["duration"], 1e-4)
        rate = f["bytes"] / dur
        amp = min(1.0, rate / nominal_rate_bytes_per_sec)

        if amp > max_amp:
            max_amp = amp

        total_amp_sq += amp * amp

        if amp < 0.15:
            silence_count += 1
            pause_frames += 1
            if pause_frames == 12:  # ~300ms threshold
                pause_count += 1
        else:
            pause_frames = 0

    num_f = len(in_window)
    rms_amp = math.sqrt(total_amp_sq / num_f)

    rms_db = round(20 * math.log10(max(rms_amp, 1e-4)), 1)
    peak_db = round(20 * math.log10(max(max_amp, 1e-4)), 1)

    silence_ratio = round(silence_count / max(num_f, 1), 2)
    speech_ratio = round(1.0 - silence_ratio, 2)

    return {
        "rms_db": rms_db,
        "peak_db": peak_db,
        "speech_ratio": speech_ratio,
        "silence_ratio": silence_ratio,
        "pause_count": pause_count,
    }


def _parse_m4a_frames(filepath):
    try:
        with open(filepath, "rb") as f:
            data = f.read()

        timescale = 44100
        sample_durations = []
        sample_sizes = []

        def parse_container(offset, end):
            nonlocal timescale, sample_durations, sample_sizes
            curr = offset
            while curr + 8 <= end:
                size, btype = struct.unpack(">I4s", data[curr:curr + 8])
                if size == 1 and curr + 16 <= end:
                    size = struct.unpack(">Q", data[curr + 8:curr + 16])[0]
                    hdr_len = 16
                else:
                    hdr_len = 8

                if size < hdr_len or curr + size > end:
                    break

                body = curr + hdr_len
                body_end = curr + size

                if btype == b"mdhd":
                    version = data[body]
                    if version == 0 and body + 20 <= body_end:
                        timescale = struct.unpack(">I", data[body + 12:body + 16])[0]
                    elif version == 1 and body + 28 <= body_end:
                        timescale = struct.unpack(">I", data[body + 20:body + 24])[0]
                elif btype == b"stts" and body + 8 <= body_end:
                    entry_count = struct.unpack(">I", data[body + 4:body + 8])[0]
                    pos = body + 8
                    for _ in range(entry_count):
                        if pos + 8 > body_end:
                            break
                        cnt, dur = struct.unpack(">II", data[pos:pos + 8])
                        sample_durations.extend([dur] * cnt)
                        pos += 8
                elif btype == b"stsz" and body + 12 <= body_end:
                    sz, count = struct.unpack(">II", data[body + 4:body + 12])
                    if sz > 0:
                        sample_sizes = [sz] * count
                    else:
                        pos = body + 12
                        for _ in range(count):
                            if pos + 4 > body_end:
                                break
                            sample_sizes.append(struct.unpack(">I", data[pos:pos + 4])[0])
                            pos += 4
                elif btype in (b"moov", b"trak", b"mdia", b"minf", b"stbl"):
                    parse_container(body, body_end)

                curr += size

        parse_container(0, len(data))

        if not sample_durations or not sample_sizes:
            return None

        frames = []
        curr_t = 0.0
        ts = float(timescale) if timescale > 0 else 44100.0

        for dur_units, sz in zip(sample_durations, sample_sizes):
            dur_sec = dur_units / ts
            frames.append({
                "start": curr_t,
                "duration": dur_sec,
                "bytes": sz,
            })
            curr_t += dur_sec

        return frames
    except Exception:
        return None


def _parse_mp3_frames(filepath):
    try:
        with open(filepath, "rb") as f:
            data = f.read()

        bitrates = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
        samplerates = [44100, 48000, 32000, 0]

        frames = []
        curr = 0
        curr_t = 0.0

        while curr + 4 <= len(data):
            if data[curr] == 0xFF and (data[curr + 1] & 0xE0) == 0xE0:
                header = struct.unpack(">I", data[curr:curr + 4])[0]
                bitrate_idx = (header >> 12) & 0x0F
                sr_idx = (header >> 10) & 0x03
                padding = (header >> 9) & 0x01

                if 0 < bitrate_idx < 15 and sr_idx < 3:
                    br_kbps = bitrates[bitrate_idx]
                    sr = samplerates[sr_idx]
                    frame_size = int((144 * br_kbps * 1000) / sr) + padding
                    dur_sec = 1152.0 / sr

                    if frame_size > 4 and curr + frame_size <= len(data):
                        frames.append({
                            "start": curr_t,
                            "duration": dur_sec,
                            "bytes": frame_size,
                        })
                        curr_t += dur_sec
                        curr += frame_size
                        continue
            curr += 1

        return frames if frames else None
    except Exception:
        return None


def _parse_ogg_opus_frames(filepath):
    try:
        with open(filepath, "rb") as f:
            data = f.read()

        frames = []
        curr = 0

        while curr + 27 <= len(data):
            if data[curr:curr + 4] == b"OggS":
                granule = struct.unpack("<q", data[curr + 6:curr + 14])[0]
                num_segments = data[curr + 26]
                if curr + 27 + num_segments <= len(data):
                    seg_table = data[curr + 27:curr + 27 + num_segments]
                    page_bytes = sum(seg_table)
                    header_size = 27 + num_segments
                    if granule > 0:
                        t_sec = granule / 48000.0
                        dur_sec = 0.02  # ~20ms default Opus page frame duration
                        frames.append({
                            "start": max(0.0, t_sec - dur_sec),
                            "duration": dur_sec,
                            "bytes": page_bytes,
                        })
                    curr += header_size + page_bytes
                    continue
            curr += 1

        return frames if frames else None
    except Exception:
        return None


def _parse_webm_opus_frames(filepath):
    try:
        with open(filepath, "rb") as f:
            data = f.read()

        frames = []
        curr = 0

        def read_vint(pos):
            if pos >= len(data):
                return None, 0
            b = data[pos]
            mask = 0x80
            length = 1
            while mask and not (b & mask):
                mask >>= 1
                length += 1
            if length > 8 or not mask:
                return None, 0
            val = b & (~mask)
            for i in range(1, length):
                if pos + i >= len(data):
                    return None, 0
                val = (val << 8) | data[pos + i]
            return val, length

        cluster_tc = 0.0

        while curr < len(data):
            elem_id, id_len = read_vint(curr)
            if not elem_id or curr + id_len >= len(data):
                break
            curr += id_len
            elem_size, sz_len = read_vint(curr)
            if elem_size is None:
                break
            curr += sz_len

            if elem_id == 0xE7 and elem_size <= 8:  # Timecode
                if curr + elem_size <= len(data):
                    tc_val = 0
                    for b in data[curr:curr + elem_size]:
                        tc_val = (tc_val << 8) | b
                    cluster_tc = tc_val / 1000.0  # ms to sec
                curr += elem_size
            elif elem_id == 0xA3:  # SimpleBlock
                if curr + elem_size <= len(data):
                    tn, tn_len = read_vint(curr)
                    if tn is not None and curr + tn_len + 2 <= len(data):
                        rel_tc = struct.unpack(">h", data[curr + tn_len:curr + tn_len + 2])[0]
                        block_t = cluster_tc + (rel_tc / 1000.0)
                        frames.append({
                            "start": max(0.0, block_t),
                            "duration": 0.02,
                            "bytes": elem_size,
                        })
                curr += elem_size
            else:
                if elem_size > len(data):
                    break
                curr += elem_size

        return frames if frames else None
    except Exception:
        return None


def analyze_audio_segment(audio_path, start_sec, end_sec):
    """
    Analyze an audio segment [start_sec, end_sec] from audio_path.
    Returns timestamped audio evidence dictionary.
    """
    start_sec = max(0.0, float(start_sec))
    end_sec = max(start_sec, float(end_sec))
    duration = round(end_sec - start_sec, 3)

    evidence = {
        "start": round(start_sec, 3),
        "end": round(end_sec, 3),
        "duration": duration,
        "audio_present": False,
        "status": "missing_file",
        "rms_db": None,
        "peak_db": None,
        "speech_ratio": None,
        "silence_ratio": None,
        "pause_count": None,
        "summary": f"Audio [{start_sec:.1f}s - {end_sec:.1f}s]: file not found",
    }

    if not audio_path or not os.path.exists(audio_path) or os.path.getsize(audio_path) == 0:
        return evidence

    evidence["audio_present"] = True
    ext = str(audio_path).lower()

    # 1. WAV format
    if ext.endswith(".wav"):
        try:
            with wave.open(str(audio_path), "rb") as wf:
                n_channels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
                framerate = wf.getframerate()
                n_frames = wf.getnframes()

                start_frame = int(start_sec * framerate)
                end_frame = int(end_sec * framerate)

                wf.setpos(min(start_frame, n_frames))
                frames_to_read = max(0, min(end_frame - start_frame, n_frames - start_frame))

                raw_bytes = wf.readframes(frames_to_read)

                if sampwidth == 2 and n_channels == 1:
                    stats = _analyze_pcm_bytes(raw_bytes, framerate)
                    if stats:
                        evidence.update(stats)
                        evidence["status"] = "analyzed"
                        evidence["summary"] = (
                            f"Audio [{evidence['start']}s - {evidence['end']}s]: "
                            f"RMS {stats['rms_db']} dB, Peak {stats['peak_db']} dB, "
                            f"Speech {int(stats['speech_ratio']*100)}%, Pauses {stats['pause_count']}"
                        )
                        return evidence
        except Exception:
            pass

    # 2. Production container parsers (pure Python: M4A, MP3, Opus, WebM)
    comp_frames = None
    if ext.endswith(".m4a") or ext.endswith(".mp4") or ext.endswith(".aac"):
        comp_frames = _parse_m4a_frames(audio_path)
    elif ext.endswith(".mp3"):
        comp_frames = _parse_mp3_frames(audio_path)
    elif ext.endswith(".opus") or ext.endswith(".ogg"):
        comp_frames = _parse_ogg_opus_frames(audio_path)
    elif ext.endswith(".webm") or ext.endswith(".mkv"):
        comp_frames = _parse_webm_opus_frames(audio_path)

    if comp_frames:
        stats = _analyze_compressed_frames(comp_frames, start_sec, end_sec)
        if stats:
            evidence.update(stats)
            evidence["status"] = "analyzed"
            evidence["summary"] = (
                f"Audio [{evidence['start']}s - {evidence['end']}s]: "
                f"RMS {stats['rms_db']} dB, Peak {stats['peak_db']} dB, "
                f"Speech {int(stats['speech_ratio']*100)}%, Pauses {stats['pause_count']}"
            )
            return evidence

    # 3. Fallback ffmpeg pipe if available
    try:
        cmd = [
            "ffmpeg",
            "-ss", str(start_sec),
            "-to", str(end_sec),
            "-i", str(audio_path),
            "-f", "s16le",
            "-ac", "1",
            "-ar", "16000",
            "-y",
            "pipe:1"
        ]
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
        if res.returncode == 0 and res.stdout:
            stats = _analyze_pcm_bytes(res.stdout, 16000)
            if stats:
                evidence.update(stats)
                evidence["status"] = "analyzed"
                evidence["summary"] = (
                    f"Audio [{evidence['start']}s - {evidence['end']}s]: "
                    f"RMS {stats['rms_db']} dB, Peak {stats['peak_db']} dB, "
                    f"Speech {int(stats['speech_ratio']*100)}%, Pauses {stats['pause_count']}"
                )
                return evidence
    except Exception:
        pass

    evidence["status"] = "verified_present"
    evidence["summary"] = f"Audio [{evidence['start']}s - {evidence['end']}s]: audio file present"
    return evidence
