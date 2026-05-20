"""File upload router — handles image attachments from CustomerPortal / AgentWorkspace."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import JSONResponse

from ..routers.auth import get_current_user

# ── Config ────────────────────────────────────────────────────────────────────

UPLOAD_DIR = Path(__file__).resolve().parents[4] / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_CONTENT_TYPES = {
    "image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif",
}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

router = APIRouter(prefix="/api", tags=["upload"])


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/upload", summary="Upload an image attachment")
async def upload_file(
    file: Annotated[UploadFile, File(description="Image file (JPEG/PNG/WEBP/GIF, max 10 MB)")],
    current_user: dict = Depends(get_current_user),
) -> JSONResponse:
    """Accept an image upload and return the served URL.

    The URL is of the form ``/uploads/<uuid>.<ext>`` and is served by the
    FastAPI StaticFiles mount at ``/uploads``.
    """
    # Validate content type
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type '{file.content_type}'. Allowed: JPEG, PNG, WEBP, GIF.",
        )

    # Read content (with size guard)
    contents = await file.read(MAX_FILE_SIZE + 1)
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File too large. Maximum allowed size is 10 MB.",
        )

    # Derive safe extension
    ext = _safe_extension(file.content_type)
    filename = f"{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_DIR / filename
    dest.write_bytes(contents)

    return JSONResponse({"url": f"/uploads/{filename}", "filename": filename})


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_extension(content_type: str) -> str:
    return {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }.get(content_type, ".bin")
