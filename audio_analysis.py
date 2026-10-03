import os
import math
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

    pcm_data = None
    sample_rate = 16000

    # 1. Try reading directly if it's a WAV file
    try:
        if str(audio_path).lower().endswith(".wav"):
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
                    pcm_data = raw_bytes
                    sample_rate = framerate
    except Exception:
        pcm_data = None

    # 2. Try ffmpeg subprocess pipe if pcm_data is not set
    if pcm_data is None:
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
                pcm_data = res.stdout
                sample_rate = 16000
        except Exception:
            pcm_data = None

    # 3. Process PCM bytes if available, else fallback
    if pcm_data:
        stats = _analyze_pcm_bytes(pcm_data, sample_rate)
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
