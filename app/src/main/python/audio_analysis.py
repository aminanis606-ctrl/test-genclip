import os
import math
import struct
import subprocess
import wave

try:
    import av
except ImportError:
    av = None

try:
    import miniaudio
except ImportError:
    miniaudio = None


def _decode_to_pcm(filepath, start_sec=0.0, end_sec=None):
    """
    Decode compressed or uncompressed audio file into raw 16-bit mono PCM sample bytes and sample rate.
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
                    mono_samples = []
                    for i in range(0, len(raw_bytes), 2 * nch):
                        mono_samples.append(raw_bytes[i:i+2])
                    return b"".join(mono_samples), sr
        except Exception:
            pass

    # 2. PyAV (av) decoder for M4A, AAC, MP3, WebM, Opus, Ogg, WAV
    if av is not None:
        try:
            container = av.open(filepath)
            audio_stream = next((s for s in container.streams if s.type == 'audio'), None)
            if audio_stream:
                resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
                pcm_chunks = []
                for frame in container.decode(audio_stream):
                    t = frame.time if frame.time is not None else 0.0
                    rf_list = resampler.resample(frame)
                    for rf in rf_list:
                        rf_t = rf.time if rf.time is not None else t
                        rf_dur = rf.samples / 16000.0
                        if end_sec is not None and rf_t > end_sec:
                            continue
                        if start_sec is not None and (rf_t + rf_dur) < start_sec:
                            continue
                        pcm_chunks.append(rf.planes[0].to_bytes())
                if pcm_chunks:
                    return b"".join(pcm_chunks), 16000
        except Exception:
            pass

    # 3. Miniaudio decoder for MP3, WAV, FLAC, Vorbis
    if miniaudio is not None:
        try:
            decoded = miniaudio.decode_file(filepath, output_format=miniaudio.SampleFormat.SIGNED16)
            if decoded and decoded.samples:
                raw_bytes = decoded.samples.tobytes()
                sr = decoded.sample_rate
                nch = decoded.nchannels

                start_idx = int(start_sec * sr) * 2 * nch
                end_idx = int(end_sec * sr) * 2 * nch if end_sec is not None else len(raw_bytes)
                sliced = raw_bytes[max(0, start_idx):min(len(raw_bytes), end_idx)]

                if nch == 1:
                    return sliced, sr
                else:
                    mono_samples = []
                    for i in range(0, len(sliced), 2 * nch):
                        mono_samples.append(sliced[i:i+2])
                    return b"".join(mono_samples), sr
        except Exception:
            pass

    # 4. ffmpeg pipe fallback if available
    try:
        cmd = ["ffmpeg", "-ss", str(start_sec)]
        if end_sec is not None:
            cmd.extend(["-to", str(end_sec)])
        cmd.extend(["-i", str(filepath), "-f", "s16le", "-ac", "1", "-ar", "16000", "-y", "pipe:1"])
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False, timeout=10)
        if res.returncode == 0 and res.stdout:
            return res.stdout, 16000
    except Exception:
        pass

    return None, 16000


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

    pcm_data, sr = _decode_to_pcm(audio_path, start_sec, end_sec)

    if pcm_data:
        stats = _analyze_pcm_bytes(pcm_data, sr)
        if stats:
            evidence.update(stats)
            evidence["status"] = "analyzed"
            evidence["summary"] = (
                f"Audio [{evidence['start']}s - {evidence['end']}s]: "
                f"RMS {stats['rms_db']} dB, Peak {stats['peak_db']} dB, "
                f"Speech {int(stats['speech_ratio']*100)}%, Pauses {stats['pause_count']}"
            )
            return evidence

    evidence["status"] = "verified_present"
    evidence["summary"] = f"Audio [{evidence['start']}s - {evidence['end']}s]: audio file present"
    return evidence
