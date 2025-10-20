from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class TimeInterval(BaseModel):
    start: float = Field(..., description="start time in seconds")
    end: float = Field(..., description="end time in seconds")


class TranscribeResponse(BaseModel):
    transcript: str
    filler_timestamps: List[TimeInterval]
    silence_timestamps: List[TimeInterval]
    original_video_url: str
    video_record_id: Optional[str] = None


class AutoEditRequest(BaseModel):
    remove_segments: List[TimeInterval] = Field(default_factory=list)
    apply_color_grade: bool = False
    normalize_audio: bool = False
    overlay_text: Optional[str] = None
    reference_video_url: Optional[str] = None
    video_record_id: Optional[str] = None


class AutoEditResponse(BaseModel):
    edited_video_url: str


class VibeAnalysisRequest(BaseModel):
    transcript: str


class VibeAnalysisResponse(BaseModel):
    emotions: Dict[str, float]
    summary: str
