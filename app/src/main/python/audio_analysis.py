import math
import os
import wave
import io
import struct
import numpy as np

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


def demux_webm_opus_to_ogg(webm_bytes: bytes) -> bytes:
    """
    Parses an authentic Matroska/WebM EBML container, extracts the OpusHead
    and SimpleBlock audio frames, and re-wraps them into a standard OGG/Opus bitstream.
    Pure Python, zero binary dependencies.
    """
    def read_vint(stream):
        first_byte_val = stream.read(1)
        if not first_byte_val:
            return None, 0
        b = first_byte_val[0]
        length = 1
        mask = 0x80
        while mask and not (b & mask):
            length += 1
            mask >>= 1
        if length > 8:
            return None, 0
        value = b & (mask - 1)
        for _ in range(length - 1):
            next_b = stream.read(1)
            if not next_b:
                return None, 0
            value = (value << 8) | next_b[0]
        return value, length

    def read_element_header(stream):
        pos = stream.tell()
        first_byte_val = stream.read(1)
        if not first_byte_val:
            return None, None, 0
        b = first_byte_val[0]
        id_len = 1
        mask = 0x80
        while mask and not (b & mask):
            id_len += 1
            mask >>= 1
        stream.seek(pos)
        raw_id = stream.read(id_len)
        if len(raw_id) < id_len:
            return None, None, 0
        elem_id = int.from_bytes(raw_id, "big")
        data_len, vint_len = read_vint(stream)
        return elem_id, data_len, id_len + vint_len

    stream = io.BytesIO(webm_bytes)
    total_size = len(webm_bytes)

    codec_private = None
    opus_frames = []

    while stream.tell() < total_size:
        elem_id, data_len, header_len = read_element_header(stream)
        if elem_id is None or data_len is None:
            break

        # Dive into EBML container elements
        if elem_id in (0x1A45DFA3, 0x18538067, 0x1654AE6B, 0xAE, 0x1F43B675, 0x0F43B675):
            continue

        # CodecPrivate (0x63A2) - OpusHead
        if elem_id == 0x63A2:
            codec_private = stream.read(data_len)
            continue

        # SimpleBlock (0xA3) or Block (0xA1)
        if elem_id in (0xA3, 0xA1):
            block_bytes = stream.read(data_len)
            if len(block_bytes) > 4:
                tb_stream = io.BytesIO(block_bytes)
                _, tn_len = read_vint(tb_stream)
                tb_stream.seek(tn_len + 3)  # Skip track number, timecode, flags
                frame_data = tb_stream.read()
                if frame_data:
                    opus_frames.append(frame_data)
            continue

        stream.seek(data_len, io.SEEK_CUR)

    if not codec_private or not opus_frames:
        raise ValueError("Could not find WebM Opus track or audio frames")

    opus_head = codec_private if codec_private.startswith(b"OpusHead") else b"OpusHead" + codec_private
    opus_tags = b"OpusTags" + struct.pack("<I", 8) + b"genclip\x00" + struct.pack("<I", 0)

    # Ogg CRC32 table
    crc_table = []
    for i in range(256):
        r = i << 24
        for _ in range(8):
            if r & 0x80000000:
                r = ((r << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
            else:
                r = (r << 1) & 0xFFFFFFFF
        crc_table.append(r)

    def ogg_crc(data: bytes) -> int:
        crc = 0
        for byte in data:
            crc = ((crc << 8) & 0xFFFFFFFF) ^ crc_table[((crc >> 24) ^ byte) & 0xFF]
        return crc

    def make_page(header_type: int, granule_pos: int, serial: int, page_num: int, packets: list) -> bytes:
        body = b"".join(packets)
        segment_table = bytes([len(p) for p in packets])
        header = struct.pack("<4sBBqIIIB", b"OggS", 0, header_type, granule_pos, serial, page_num, 0, len(packets)) + segment_table
        full = header + body
        checksum = ogg_crc(full)
        return header[:22] + struct.pack("<I", checksum) + header[26:] + body

    serial = 0x47454E43
    buf = io.BytesIO()

    buf.write(make_page(2, 0, serial, 0, [opus_head]))
    buf.write(make_page(0, 0, serial, 1, [opus_tags]))

    page_num = 2
    granule = 0
    chunk_size = 50
    for i in range(0, len(opus_frames), chunk_size):
        chunk = opus_frames[i : i + chunk_size]
        is_last = (i + chunk_size) >= len(opus_frames)
        granule += len(chunk) * 960
        buf.write(make_page(4 if is_last else 0, granule, serial, page_num, chunk))
        page_num += 1

    return buf.getvalue()


def load_audio_pcm(audio_path):
    """
    Decodes audio file into raw float32 PCM samples (mono) and sample rate.
    Supports WebM/Opus, OGG/Opus, MP3, FLAC, Vorbis, and WAV formats.
    Uses native C miniaudio decoder and soundfile (libsndfile) with in-memory WebM demuxing.
    Caches PCM per file path to avoid redundant decoding.
    """
    if not os.path.exists(audio_path):
        return None, None, "missing_file"

    resolved_path = os.path.abspath(audio_path)
    if resolved_path in _PCM_CACHE:
        return _PCM_CACHE[resolved_path]

    # Attempt 1: Check if file is WebM / Matroska (EBML magic 0x1A45DFA3)
    try:
        with open(resolved_path, "rb") as f:
            header_bytes = f.read(1024 * 1024)  # Read up to 1MB or full header
            f.seek(0)
            full_bytes = f.read()

        if header_bytes.startswith(b"\x1a\x45\xdf\xa3") and sf is not None:
            ogg_bytes = demux_webm_opus_to_ogg(full_bytes)
            data, sample_rate = sf.read(io.BytesIO(ogg_bytes), dtype="float32")
            if data.ndim > 1:
                data = data.mean(axis=1)
            res = (data, sample_rate, "ok")
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
