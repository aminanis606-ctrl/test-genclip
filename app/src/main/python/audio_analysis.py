import math
import os
import wave
import numpy as np

# PyAV (av) - Primary decoder if present on host system
try:
    import av
except ImportError:
    av = None

# Miniaudio - Production C decoder for Chaquopy/Android (FLAC / MP3 / WAV / Vorbis)
try:
    import miniaudio
except ImportError:
    miniaudio = None

# Soundfile - libsndfile fallback decoder for OGG / FLAC / WAV
try:
    import soundfile as sf
except ImportError:
    sf = None

_PCM_CACHE = {}


def load_audio_pcm(audio_path):
    """
    Decodes audio file into raw float32 PCM samples (mono) and sample rate.
    Supports WebM/Opus, OGG/Opus, MP3, FLAC, Vorbis, and WAV formats.
    Attempts decoding using available decoders (PyAV, miniaudio, soundfile, wave).
    Caches PCM per file path to avoid redundant decoding.
    """
    if not os.path.exists(audio_path):
        return None, None, "missing_file"

    resolved_path = os.path.abspath(audio_path)
    if resolved_path in _PCM_CACHE:
        return _PCM_CACHE[resolved_path]

    # Attempt 1: PyAV (if available)
    if av is not None:
        try:
            container = av.open(resolved_path)
            audio_streams = [s for s in container.streams if s.type == "audio"]
            if audio_streams:
                audio_stream = audio_streams[0]
                sample_rate = audio_stream.codec_context.sample_rate or 48000
                resampled_chunks = []

                for frame in container.decode(audio_stream):
                    arr = frame.to_ndarray()
                    if arr.ndim > 1:
                        arr = arr.mean(axis=0)  # Downmix to mono
                    resampled_chunks.append(arr.astype(np.float32))

                if resampled_chunks:
                    samples = np.concatenate(resampled_chunks)
                    if np.abs(samples).max() > 1.0:
                        samples = samples / 32768.0
                    res = (samples, sample_rate, "ok")
                    _PCM_CACHE[resolved_path] = res
                    return res
        except Exception:
            pass

    # Attempt 2: miniaudio (Native C decoder for FLAC, MP3, WAV, Vorbis on Chaquopy/Android)
    if miniaudio is not None:
        try:
            decoded = miniaudio.decode_file(resolved_path)
            samples = np.array(decoded.samples, dtype=np.float32)
            if decoded.nchannels > 1:
                samples = samples.reshape(-1, decoded.nchannels).mean(axis=1)
            if np.abs(samples).max() > 1.0:
                samples = samples / 32768.0
            res = (samples, decoded.sample_rate, "ok")
            _PCM_CACHE[resolved_path] = res
            return res
        except Exception:
            pass

    # Attempt 3: soundfile / libsndfile fallback (Handles OGG, FLAC, WAV)
    if sf is not None:
        try:
            data, sample_rate = sf.read(resolved_path, dtype="float32")
            if data.ndim > 1:
                data = data.mean(axis=1)
            res = (data, sample_rate, "ok")
            _PCM_CACHE[resolved_path] = res
            return res
        except Exception:
            pass

    # Attempt 4: Standard library wave (Uncompressed WAV fallback)
    try:
        with wave.open(resolved_path, "rb") as wf:
            sample_rate = wf.getframerate()
            nchannels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            nframes = wf.getnframes()
            raw_bytes = wf.readframes(nframes)

            if sampwidth == 2:
                samples = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            elif sampwidth == 4:
                samples = np.frombuffer(raw_bytes, dtype=np.int32).astype(np.float32) / 2147483648.0
            else:
                return None, None, "decode_failed"

            if nchannels > 1:
                samples = samples.reshape(-1, nchannels).mean(axis=1)

            res = (samples, sample_rate, "ok")
            _PCM_CACHE[resolved_path] = res
            return res
    except Exception:
        pass

    return None, None, "decode_failed"


def analyze_audio_segment(audio_path, start_sec, end_sec):
    """
    Analyzes PCM audio within [start_sec, end_sec].
    Returns dict with rms_db, peak_db, speech_ratio, silence_ratio, pause_count, and formatted summary string.
    """
    samples, sample_rate, status = load_audio_pcm(audio_path)

    if status == "missing_file":
        return {
            "start": float(start_sec),
            "end": float(end_sec),
            "duration": float(end_sec - start_sec),
            "audio_present": False,
            "status": "missing_file",
            "summary": f"Audio [{start_sec:.1f}s - {end_sec:.1f}s]: file not found",
        }

    if status != "ok" or samples is None or len(samples) == 0:
        return {
            "start": float(start_sec),
            "end": float(end_sec),
            "duration": float(end_sec - start_sec),
            "audio_present": True,
            "status": "decode_failed",
            "summary": f"Audio [{start_sec:.1f}s - {end_sec:.1f}s]: decode failed",
        }

    start_idx = int(start_sec * sample_rate)
    end_idx = int(end_sec * sample_rate)

    if start_idx >= len(samples):
        segment = np.array([0.0], dtype=np.float32)
    else:
        segment = samples[start_idx:min(end_idx, len(samples))]

    if len(segment) == 0:
        segment = np.array([0.0], dtype=np.float32)

    # RMS Energy & Peak Amplitude Calculation
    rms = np.sqrt(np.mean(segment**2)) + 1e-9
    peak = np.max(np.abs(segment)) + 1e-9

    rms_db = round(float(20 * math.log10(rms)), 1)
    peak_db = round(float(20 * math.log10(peak)), 1)

    # Windowed VAD (Voice Activity Detection) analysis: 100ms frames
    frame_size = int(sample_rate * 0.1)
    num_frames = max(1, len(segment) // frame_size)

    silence_count = 0
    pause_count = 0
    in_pause = False

    # Silence threshold: -45 dB RMS or < 0.005 linear amplitude
    for i in range(num_frames):
        frame = segment[i * frame_size : (i + 1) * frame_size]
        if len(frame) == 0:
            continue
        frame_rms = np.sqrt(np.mean(frame**2))
        if frame_rms < 0.005:
            silence_count += 1
            if not in_pause:
                pause_count += 1
                in_pause = True
        else:
            in_pause = False

    silence_ratio = round(float(silence_count / num_frames), 2)
    speech_ratio = round(float(1.0 - silence_ratio), 2)

    summary_str = (
        f"Audio [{start_sec:.1f}s - {end_sec:.1f}s]: "
        f"RMS {rms_db} dB, Peak {peak_db} dB, "
        f"Speech {int(speech_ratio * 100)}%, Pauses {pause_count}"
    )

    return {
        "start": float(start_sec),
        "end": float(end_sec),
        "duration": round(float(end_sec - start_sec), 1),
        "audio_present": True,
        "status": "analyzed",
        "rms_db": rms_db,
        "peak_db": peak_db,
        "speech_ratio": speech_ratio,
        "silence_ratio": silence_ratio,
        "pause_count": pause_count,
        "summary": summary_str,
    }
