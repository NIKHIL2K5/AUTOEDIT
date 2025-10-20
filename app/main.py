import os
import io
import json
import uuid
import tempfile
from typing import List, Optional

from fastapi import FastAPI, File, UploadFile, Depends, HTTPException, Header, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from dotenv import load_dotenv

from app.models.schemas import TranscribeResponse, VibeAnalysisRequest, VibeAnalysisResponse, AutoEditRequest, AutoEditResponse
from app.services.supabase_client import get_supabase, get_user_from_token, upload_bytes_to_storage, create_signed_url, upsert_video_record
from app.services.transcribe import transcribe_video_to_text, detect_fillers_from_segments
from app.utils.silence import detect_silence_intervals
from app.services.editing import auto_edit_video
from app.services.vibe import analyze_vibe_safe

# Load environment from .env if present
load_dotenv()

app = FastAPI(title="Vibe Editing Backend", version="0.1.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def logging_middleware(request, call_next):
    user = "unknown"
    try:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1]
            try:
                u = await get_user_from_token(token)
                user = u.get("id", "unknown")
            except Exception:
                pass
    except Exception:
        pass
    logger.info("REQ {} {} user={} ", request.method, request.url.path, user)
    try:
        resp = await call_next(request)
        logger.info("RES {} {} status={} user={}", request.method, request.url.path, resp.status_code, user)
        return resp
    except Exception as e:
        logger.exception("Unhandled error for {} {}", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


async def get_current_user(Authorization: Optional[str] = Header(None)):
    if not Authorization or not Authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization Bearer token")
    token = Authorization.split(" ", 1)[1]
    try:
        user = await get_user_from_token(token)
        return user
    except Exception as e:
        logger.exception("Auth failure")
        raise HTTPException(status_code=401, detail="Invalid or expired token")


@app.post("/transcribe", response_model=TranscribeResponse)
async def transcribe_endpoint(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    logger.info("/transcribe called by user={}", current_user.get("id"))

    if file.content_type not in ("video/mp4", "video/quicktime", "application/octet-stream"):
        raise HTTPException(status_code=400, detail="Unsupported file type. Use mp4/mov.")

    # Save to temp
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = os.path.join(tmpdir, f"{uuid.uuid4()}.mp4")
        data = await file.read()
        with open(tmp_path, "wb") as f:
            f.write(data)

        # Upload original to Supabase storage
        sb = get_supabase()
        storage_key = f"original/{current_user['id']}/{uuid.uuid4()}_{file.filename}"
        await upload_bytes_to_storage(sb, data, storage_key, content_type=file.content_type)
        original_url = await create_signed_url(sb, storage_key)

        # Transcribe with Whisper
        transcript_text, segments = await transcribe_video_to_text(tmp_path)

        # Filler detection (by segments)
        filler_timestamps = detect_fillers_from_segments(segments)

        # Silence detection via ffmpeg silencedetect
        silence_timestamps = await detect_silence_intervals(tmp_path)

        # Persist metadata
        record = await upsert_video_record(
            user_id=current_user["id"],
            original_url=original_url,
            transcript=transcript_text,
            filler_timestamps=filler_timestamps,
            silence_timestamps=silence_timestamps,
            edited_url=None,
        )

        return TranscribeResponse(
            transcript=transcript_text,
            filler_timestamps=filler_timestamps,
            silence_timestamps=silence_timestamps,
            original_video_url=original_url,
            video_record_id=record.get("id"),
        )


@app.post("/autoedit", response_model=AutoEditResponse)
async def autoedit_endpoint(
    file: UploadFile = File(None),
    body: AutoEditRequest | None = Body(None),
    current_user: dict = Depends(get_current_user),
):
    logger.info("/autoedit called by user={}", current_user.get("id"))

    # Input handling: either we received a file OR a reference_url (but file preferred)
    if not file and not (body and body.reference_video_url):
        raise HTTPException(status_code=400, detail="Provide a video file or reference_video_url")

    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = None
        if file:
            data = await file.read()
            input_path = os.path.join(tmpdir, f"{uuid.uuid4()}.mp4")
            with open(input_path, "wb") as f:
                f.write(data)
        else:
            # Download from reference URL
            import httpx
            input_path = os.path.join(tmpdir, f"{uuid.uuid4()}.mp4")
            async with httpx.AsyncClient() as client:
                resp = await client.get(body.reference_video_url)  # type: ignore
                resp.raise_for_status()
                with open(input_path, "wb") as f:
                    f.write(resp.content)

        # Compute keep segments from provided remove timestamps
        edited_path = os.path.join(tmpdir, f"edited_{uuid.uuid4()}.mp4")
        await auto_edit_video(
            input_path,
            edited_path,
            remove_segments=(body.remove_segments if body else []) or [],
            apply_color_grade=bool(body and body.apply_color_grade),
            normalize_audio=bool(body and body.normalize_audio),
            overlay_text=(body.overlay_text if body else None),
        )

        # Upload edited video
        sb = get_supabase()
        with open(edited_path, "rb") as f:
            edited_bytes = f.read()
        storage_key = f"edited/{current_user['id']}/{uuid.uuid4()}_edited.mp4"
        await upload_bytes_to_storage(sb, edited_bytes, storage_key, content_type="video/mp4")
        edited_url = await create_signed_url(sb, storage_key)

        # Update DB record if provided
        record_id = body.video_record_id if body else None
        await upsert_video_record(
            user_id=current_user["id"],
            original_url=None,
            transcript=None,
            filler_timestamps=None,
            silence_timestamps=None,
            edited_url=edited_url,
            record_id=record_id,
        )

        return AutoEditResponse(edited_video_url=edited_url)


@app.post("/vibeanalysis", response_model=VibeAnalysisResponse)
async def vibe_analysis_endpoint(
    request: VibeAnalysisRequest,
    current_user: dict = Depends(get_current_user),
):
    logger.info("/vibeanalysis called by user={}", current_user.get("id"))
    result = await analyze_vibe_safe(request.transcript)
    return result


@app.get("/health")
async def health():
    return {"status": "ok"}
