import re
import asyncio
import ffmpeg
from typing import List, Dict
from loguru import logger


_SILENCE_RE_START = re.compile(r"silence_start: ([0-9.]+)")
_SILENCE_RE_END = re.compile(r"silence_end: ([0-9.]+)")


async def detect_silence_intervals(video_path: str, silence_threshold: str = "-30dB", min_silence_duration: float = 0.4) -> List[Dict[str, float]]:
    # Use ffmpeg silencedetect on audio stream
    logger.info("Detecting silence via ffmpeg: {}", video_path)
    proc = (
        ffmpeg
        .input(video_path)
        .output('pipe:', format='null', af=f"silencedetect=noise={silence_threshold}:d={min_silence_duration}")
        .global_args('-hide_banner')
        .global_args('-nostats')
    )

    # ffmpeg-python doesn't expose stderr easily; run async via subprocess
    cmd = ' '.join(proc.get_args())
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    text = stderr.decode('utf-8', errors='ignore')

    silences: List[Dict[str, float]] = []
    current_start = None
    for line in text.splitlines():
        m1 = _SILENCE_RE_START.search(line)
        if m1:
            current_start = float(m1.group(1))
        m2 = _SILENCE_RE_END.search(line)
        if m2 and current_start is not None:
            end = float(m2.group(1))
            silences.append({"start": current_start, "end": end})
            current_start = None
    return silences
