from io import BytesIO

import pytest
import anyio
from fastapi import HTTPException, UploadFile

from core.uploads import read_upload_limited


def test_upload_reader_accepts_content_at_limit():
    upload = UploadFile(filename="small.csv", file=BytesIO(b"12345"))

    assert anyio.run(read_upload_limited, upload, 5) == b"12345"


def test_upload_reader_rejects_oversize_without_buffering_the_rest():
    upload = UploadFile(filename="large.csv", file=BytesIO(b"123456789"))

    with pytest.raises(HTTPException) as error:
        anyio.run(read_upload_limited, upload, 5)

    assert error.value.status_code == 413
    assert upload.file.tell() == 6
