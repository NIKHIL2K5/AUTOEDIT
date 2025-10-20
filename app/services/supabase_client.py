import os
import base64
import json
from typing import Optional, Any, Dict

import httpx
from supabase import create_client, Client
from loguru import logger

_SUPABASE_URL = os.getenv("SUPABASE_URL")
_SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
_SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")  # optional
_SUPABASE_STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "videos")
_SUPABASE_TABLE = os.getenv("SUPABASE_TABLE", "videos")

_client: Optional[Client] = None


def get_supabase() -> Client:
    global _client
    if _client is None:
        if not _SUPABASE_URL or not _SUPABASE_ANON_KEY:
            raise RuntimeError("Missing SUPABASE_URL or SUPABASE_ANON_KEY env vars")
        _client = create_client(_SUPABASE_URL, _SUPABASE_ANON_KEY)
    return _client


async def get_user_from_token(jwt: str) -> Dict[str, Any]:
    # Verify with Supabase Auth endpoint
    url = f"{_SUPABASE_URL}/auth/v1/user"
    headers = {
        "Authorization": f"Bearer {jwt}",
        "apikey": _SUPABASE_ANON_KEY,
    }
    async with httpx.AsyncClient() as client:
        r = await client.get(url, headers=headers, timeout=30)
        if r.status_code != 200:
            logger.error("Auth verification failed: {} {}", r.status_code, r.text)
            raise ValueError("Auth failed")
        data = r.json()
        return {"id": data.get("id"), "email": data.get("email")}


async def upload_bytes_to_storage(client: Client, data: bytes, path: str, content_type: str = "application/octet-stream") -> None:
    res = client.storage.from_(_SUPABASE_STORAGE_BUCKET).upload(path, data, file_options={"contentType": content_type, "upsert": True})
    if hasattr(res, "error") and res.error:
        raise RuntimeError(f"Upload failed: {res.error}")


async def create_signed_url(client: Client, path: str, expires_in: int = 60 * 60 * 24 * 7) -> str:
    # returns signed URL valid for expires_in seconds
    res = client.storage.from_(_SUPABASE_STORAGE_BUCKET).create_signed_url(path, expires_in)
    if hasattr(res, "error") and res.error:
        raise RuntimeError(f"Signed URL failed: {res.error}")
    return res.get("signedURL") or res.get("signed_url") or res["signedURL"]


async def upsert_video_record(
    user_id: str,
    original_url: Optional[str],
    transcript: Optional[str],
    filler_timestamps: Optional[Any],
    silence_timestamps: Optional[Any],
    edited_url: Optional[str],
    record_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "user_id": user_id,
    }
    if original_url is not None:
        payload["original_url"] = original_url
    if edited_url is not None:
        payload["edited_url"] = edited_url
    if transcript is not None:
        payload["transcript"] = transcript
    if filler_timestamps is not None:
        payload["filler_timestamps"] = [x if isinstance(x, dict) else x.dict() for x in filler_timestamps] if hasattr(filler_timestamps, "__iter__") else filler_timestamps
    if silence_timestamps is not None:
        payload["silence_timestamps"] = [x if isinstance(x, dict) else x.dict() for x in silence_timestamps] if hasattr(silence_timestamps, "__iter__") else silence_timestamps

    sb = get_supabase()
    table = sb.table(_SUPABASE_TABLE)
    if record_id:
        # update
        res = table.update(payload).eq("id", record_id).execute()
    else:
        res = table.insert(payload).execute()
    if res.data is None:
        raise RuntimeError("DB write failed")
    return res.data[0]
