from fastapi import HTTPException, UploadFile


async def read_upload_limited(upload: UploadFile, max_bytes: int) -> bytes:
    """Read at most max_bytes + 1 so an oversized upload is never buffered fully."""
    content = await upload.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail="Uploaded file exceeds the size limit")
    return content
