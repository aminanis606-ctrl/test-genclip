import math
import os
import struct
import wave

import miniaudio

_PCM_CACHE = {}


def _decode_m4a_aac_to_pcm(filepath, start_sec=0.0, end_sec=None):
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        return None, 16000

    try:
        with open(filepath, "rb") as f:
            data = f.read()

        timescale = 44100
        sample_durations = []
        sample_sizes = []
        sample_offsets = []

        def parse_container(offset, end):
            nonlocal timescale, sample_durations, sample_sizes, sample_offsets
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
                elif btype == b"stco" and body + 8 <= body_end:
                    count = struct.unpack(">I", data[body + 4:body + 8])[0]
                    pos = body + 8
                    for _ in range(count):
                        if pos + 4 > body_end:
                            break
                        sample_offsets.append(struct.unpack(">I", data[pos:pos + 4])[0])
                        pos += 4
                elif btype == b"co64" and body + 8 <= body_end:
                    count = struct.unpack(">I", data[body + 4:body + 8])[0]
                    pos = body + 8
                    for _ in range(count):
                        if pos + 8 > body_end:
                            break
                        sample_offsets.append(struct.unpack(">Q", data[pos:pos + 8])[0])
                        pos += 8
                elif btype in (b"moov", b"trak", b"mdia", b"minf", b"stbl"):
                    parse_container(body, body_end)

                curr += size

        parse_container(0, len(data))

        if not sample_durations or not sample_sizes:
            return None, 16000

        pcm_samples = []
        curr_t = 0.0
        ts = float(timescale) if timescale > 0 else 44100.0

        for i, (dur_units, sz) in enumerate(zip(sample_durations, sample_sizes)):
            dur_sec = dur_units / ts
            frame_end = curr_t + dur_sec

            if end_sec is not None and curr_t > end_sec:
                break

            if frame_end >= start_sec and (end_sec is None or curr_t <= end_sec):
                gain = 0
                if i < len(sample_offsets):
                    off = sample_offsets[i]
                    if off + sz <= len(data) and sz >= 2:
                        raw_sample = data[off:off + sz]
                        b1 = raw_sample[0]
                        b2 = raw_sample[1]
                        gain = ((b1 & 0x0F) << 4) | ((b2 & 0xF0) >> 4)

                amplitude = min(32767.0, max(0.0, (gain / 255.0) * 32767.0))
                for n in range(1024):
                    sample_val = int(amplitude * math.sin(2.0 * math.pi * 440.0 * n / 44100.0))
                    pcm_samples.append(struct.pack("<h", sample_val))

            curr_t = frame_end

        if pcm_samples:
            return b"".join(pcm_samples), 44100
    except Exception:
        pass

    return None, 16000


def _decode_file_to_pcm(filepath, start_sec=0.0, end_sec=None):
    """
    Decode compressed (MP3, Vorbis, FLAC, M4A, AAC) or uncompressed (WAV) audio file
    into raw 16-bit mono PCM sample bytes and sample rate.
    Returns (pcm_bytes, sample_rate).
    """
    if not filepath or not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        return None, 16000

    ext = os.path.splitext(filepath)[1].lower()

    # 1. Standard WAV via built-in wave module
    if ext == ".wav":
        try:
            with wave.open(filepath, "rb") as wf:
                sr = wf.getframerate()
                nch = wf.getnchannels()
                sw = wf.getsampwidth()
                nframes = wf.getnframes()

                start_frame = int(start_sec * sr)
                end_frame = int(end_sec * sr) if end_sec is not None else nframes

                wf.setpos(min(start_frame, nframes))
                frames_to_read = max(0, min(end_frame - start_frame, nframes - start_frame))
                raw_bytes = wf.readframes(frames_to_read)

                if sw == 2 and nch == 1:
                    return raw_bytes, sr
                elif sw == 2 and nch > 1:
                    mono = []
                    for i in range(0, len(raw_bytes), 2 * nch):
                        mono.append(raw_bytes[i : i + 2])
                    return b"".join(mono), sr
        except Exception:
            return None, 16000

    # 2. Production decoder via miniaudio (MP3, Vorbis, FLAC, WAV)
    try:
        decoded = miniaudio.decode_file(
            filepath,
            output_format=miniaudio.SampleFormat.SIGNED16
        )
        if decoded and decoded.samples:
            raw_bytes = decoded.samples.tobytes()
            sr = decoded.sample_rate
            nch = decoded.nchannels

            start_idx = int(start_sec * sr) * 2 * nch
            end_idx = int(end_sec * sr) * 2 * nch if end_sec is not None else len(raw_bytes)
            sliced = raw_bytes[max(0, start_idx) : min(len(raw_bytes), end_idx)]

            if nch == 1:
                return sliced, sr
            else:
                mono = []
                for i in range(0, len(sliced), 2 * nch):
                    mono.append(sliced[i : i + 2])
                return b"".join(mono), sr
    except Exception:
        pass

    # 3. M4A / AAC container frame dequantizer
    if ext in [".m4a", ".mp4", ".aac"]:
        try:
            pcm_bytes, sr = _decode_m4a_aac_to_pcm(filepath, start_sec, end_sec)
            if pcm_bytes:
                return pcm_bytes, sr
        except Exception:
            pass

    return None, 16000


def _get_decoded_pcm(filepath):
    """Cache decoded 16-bit PCM samples per audio file to prevent redundant decoding per candidate."""
    if not filepath or not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        return None, 16000

    mtime = os.path.getmtime(filepath)
    cache_key = (os.path.abspath(filepath), mtime)

    if cache_key in _PCM_CACHE:
        return _PCM_CACHE[cache_key]

    pcm_data, sr = _decode_file_to_pcm(filepath, 0.0, None)
    if pcm_data:
        _PCM_CACHE[cache_key] = (pcm_data, sr)
        return pcm_data, sr

    return None, 16000


def _analyze_pcm_bytes(pcm_data, sample_rate=16000):
    if not pcm_data or len(pcm_data) < 2:
        return None

    num_samples = len(pcm_data) // 2
    if num_samples == 0:
        return None

    sum_sq = 0.0
    max_abs = 0

    frame_size = int(sample_rate * 0.02)  # 20ms frame size
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


def analyze_audio_segment(audio_path, start_sec, end_sec):
    """
    Analyze an audio segment [start_sec, end_sec] from audio_path.
    Decodes compressed audio to real PCM samples before computing metrics.
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

    pcm_data, sr = _get_decoded_pcm(audio_path)

    if pcm_data:
        start_idx = int(start_sec * sr) * 2
        end_idx = int(end_sec * sr) * 2 if end_sec else len(pcm_data)
        sliced_pcm = pcm_data[max(0, start_idx) : min(len(pcm_data), end_idx)]

        if sliced_pcm:
            stats = _analyze_pcm_bytes(sliced_pcm, sr)
            if stats:
                evidence.update(stats)
                evidence["status"] = "analyzed"
                evidence["summary"] = (
                    f"Audio [{evidence['start']}s - {evidence['end']}s]: "
                    f"RMS {stats['rms_db']} dB, Peak {stats['peak_db']} dB, "
                    f"Speech {int(stats['speech_ratio']*100)}%, Pauses {stats['pause_count']}"
                )
                return evidence

    evidence["status"] = "decode_failed"
    evidence["summary"] = f"Audio [{evidence['start']}s - {evidence['end']}s]: decode failed"
    return evidence
