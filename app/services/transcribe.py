import os
from typing import List, Tuple, Dict, Any

from loguru import logger
from faster_whisper import WhisperModel


Segment = Dict[str, Any]
_WHISPER_MODEL: WhisperModel | None = None


async def transcribe_video_to_text(video_path: str) -> Tuple[str, List[Segment]]:
    global _WHISPER_MODEL
    model_name = os.getenv("WHISPER_MODEL", "base")  # 'tiny'|'base' recommended for CPU
    if _WHISPER_MODEL is None:
        logger.info("Loading faster-whisper model: {}", model_name)
        # compute_type='int8' for CPU speed; fallback to float32 if issues
        _WHISPER_MODEL = WhisperModel(model_name, device="cpu", compute_type=os.getenv("WHISPER_COMPUTE", "int8"))
    logger.info("Transcribing: {}", video_path)
    segments_iter, info = _WHISPER_MODEL.transcribe(video_path)
    segments_list: List[Segment] = []
    full_text_parts: List[str] = []
    for s in segments_iter:
        segments_list.append({"start": float(s.start), "end": float(s.end), "text": s.text or ""})
        full_text_parts.append(s.text or "")
    full_text = " ".join(t.strip() for t in full_text_parts).strip()
    return full_text, segments_list


FILLERS = {"um", "uh", "erm", "hmm", "uhh", "like", "you know"}


def detect_fillers_from_segments(segments: List[Segment]) -> List[Dict[str, float]]:
    result: List[Dict[str, float]] = []
    for seg in segments:
        lower = seg.get("text", "").lower()
        if any(f in lower for f in FILLERS):
            result.append({"start": float(seg.get("start", 0.0)), "end": float(seg.get("end", 0.0))})
    return result
