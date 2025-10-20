# Vibe Editing Backend (FastAPI)

## Features
- Whisper transcription with filler and silence detection
- Auto-edit video by removing segments (silence/fillers)
- Optional vibe analysis via Hugging Face transformers
- Supabase integration for auth, storage, and DB
- CORS, logging, and Render deploy config

## Setup
- Install FFmpeg locally and ensure `ffmpeg` is on PATH.
- Create virtual env and install deps:
```
pip install -r requirements.txt
```
- Copy `.env.example` to `.env` and set values.

## Env
```
SUPABASE_URL=...
SUPABASE_ANON_KEY=...
SUPABASE_STORAGE_BUCKET=videos
SUPABASE_TABLE=videos
CORS_ALLOW_ORIGINS=*
WHISPER_MODEL=base
```

## Run
```
uvicorn app.main:app --reload
```

## API
- `POST /transcribe` form-data file=`video.mp4`. Requires `Authorization: Bearer <supabase_jwt>`
- `POST /autoedit` form-data: optional file, and JSON fields via `AutoEditRequest` using `request` body or query.
- `POST /vibeanalysis` JSON `{ "transcript": "..." }`
- `GET /health`

## Supabase
- Create Storage bucket `videos` (public or use signed URLs).
- Create table `videos` with columns:
  - `id` UUID default uuid_generate_v4() primary key
  - `user_id` text
  - `original_url` text
  - `edited_url` text
  - `transcript` text
  - `filler_timestamps` jsonb
  - `silence_timestamps` jsonb
  - `created_at` timestamptz default now()

## Deploy (Render)
- Use provided `render.yaml`. Add env vars in dashboard.
- Render build installs FFmpeg and requirements.

## Notes
- Whisper requires FFmpeg.
- For CPU-only deploy, keep `WHISPER_MODEL=base` or `tiny` for speed.
- If transformers pipeline is heavy, you can disable by not calling `/vibeanalysis`.
