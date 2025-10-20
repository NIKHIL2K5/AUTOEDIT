import os
import math
import asyncio
from typing import List, Dict, Optional

import ffmpeg
from loguru import logger


def _coalesce_ranges(ranges: List[Dict[str, float]], eps: float = 1e-3) -> List[Dict[str, float]]:
    if not ranges:
        return []
    ranges = sorted(ranges, key=lambda r: r['start'])
    merged = [ranges[0]]
    for r in ranges[1:]:
        last = merged[-1]
        if r['start'] <= last['end'] + eps:
            last['end'] = max(last['end'], r['end'])
        else:
            merged.append(r)
    return merged


def _invert_ranges(remove: List[Dict[str, float]], duration: float) -> List[Dict[str, float]]:
    keep = []
    cur = 0.0
    for r in remove:
        if r['start'] > cur:
            keep.append({'start': cur, 'end': r['start']})
        cur = max(cur, r['end'])
    if cur < duration:
        keep.append({'start': cur, 'end': duration})
    return keep


async def _probe_duration(path: str) -> float:
    probe = ffmpeg.probe(path)
    for stream in probe['streams']:
        if stream.get('codec_type') == 'video':
            return float(stream.get('duration') or probe['format']['duration'])
    return float(probe['format']['duration'])


async def auto_edit_video(
    input_path: str,
    output_path: str,
    remove_segments: List[Dict[str, float]],
    apply_color_grade: bool = False,
    normalize_audio: bool = False,
    overlay_text: Optional[str] = None,
):
    logger.info("Auto-edit start: {}", input_path)
    duration = await _probe_duration(input_path)
    remove = _coalesce_ranges(remove_segments)
    keep = _invert_ranges(remove, duration)
    if not keep:
        raise ValueError("Nothing to keep after removing segments")

    # Build filter_complex with trim for each keep segment
    vf_parts = []
    af_parts = []
    concat_inputs = []

    for idx, seg in enumerate(keep):
        ss = max(0.0, seg['start'])
        to = max(ss, seg['end'])
        vf_parts.append(f"[0:v]trim=start={ss}:end={to},setpts=PTS-STARTPTS[v{idx}]")
        af_parts.append(f"[0:a]atrim=start={ss}:end={to},asetpts=PTS-STARTPTS[a{idx}]")
        concat_inputs.append(f"[v{idx}][a{idx}]")

    vf = ';'.join(vf_parts)
    af = ';'.join(af_parts)
    concat_n = len(keep)

    # Optional filters
    color_chain = ""
    if apply_color_grade:
        color_chain = ",eq=contrast=1.1:brightness=0.02:saturation=1.1"

    overlay_chain = ""
    if overlay_text:
        # Basic drawtext, requires libfreetype enabled ffmpeg
        overlay_chain = f",drawtext=text='{overlay_text}':fontcolor=white:fontsize=24:x=(w-text_w)/2:y=50:box=1:boxcolor=black@0.4:boxborderw=10"

    an_chain = ""
    if normalize_audio:
        an_chain = ",loudnorm=I=-16:TP=-1.5:LRA=11"

    filter_complex = (
        f"{vf};{af};" +
        f"{''.join(concat_inputs)}concat=n={concat_n}:v=1:a=1[v][a];" +
        f"[v]format=yuv420p{color_chain}{overlay_chain}[vout];" +
        f"[a]anull{an_chain}[aout]"
    )

    cmd = (
        ffmpeg
        .input(input_path)
        .output(
            output_path,
            vcodec='libx264',
            acodec='aac',
            movflags='+faststart',
            video_bitrate='2000k',
            audio_bitrate='128k'
        )
        .global_args('-hide_banner')
        .global_args('-y')
        .global_args('-filter_complex', filter_complex)
        .global_args('-map', '[vout]', '-map', '[aout]')
    )

    logger.debug('FFmpeg args: {}', ' '.join(cmd.get_args()))

    proc = await asyncio.create_subprocess_exec(
        *cmd.get_args(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {stderr.decode('utf-8', 'ignore')}")
    logger.info("Auto-edit complete: {}", output_path)
