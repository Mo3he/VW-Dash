from __future__ import annotations

import os
import tempfile

from fastapi import APIRouter, Form, UploadFile

from config import settings
from import_vwsfriend import import_from_backup

router = APIRouter(prefix="/api/import", tags=["import"])


@router.post("/vwsfriend")
async def import_vwsfriend(
    file: UploadFile,
    battery_kwh: float = Form(default=77.0),
    wipe: bool = Form(default=False),
):
    suffix = os.path.splitext(file.filename or "")[1] or ".backup"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        result = import_from_backup(
            backup_path=tmp_path,
            db_path=settings.db_path,
            battery_kwh=battery_kwh,
            wipe=wipe,
        )
    finally:
        os.unlink(tmp_path)

    return result
