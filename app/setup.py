from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from .config import settings
from .turso_client import query_turso, ensure_admins_table, TursoNotConfigured

router = APIRouter(tags=["setup"])


class PromoteRequest(BaseModel):
    phone: str
    setup_secret: str


@router.post("/setup/promote-admin")
async def promote_admin(payload: PromoteRequest):
    """
    Shell/SSH kirish imkoni bo'lmagan platformalarda (masalan Render Free
    tarifi) birinchi admin hisobni tayinlash uchun. SETUP_SECRET .env'da
    to'g'ri sozlanmasa, bu endpoint ishlamaydi.
    """
    if not settings.setup_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SETUP_SECRET .env faylida sozlanmagan",
        )
    if payload.setup_secret != settings.setup_secret:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Noto'g'ri maxfiy kalit",
        )

    try:
        await ensure_admins_table()
        rows = await query_turso(
            "SELECT id, full_name FROM backend_admins WHERE phone = ?", (payload.phone,)
        )
    except TursoNotConfigured as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{payload.phone} raqamli foydalanuvchi topilmadi",
        )

    await query_turso(
        "UPDATE backend_admins SET role = 'admin' WHERE phone = ?", (payload.phone,)
    )
    return {"detail": f"{rows[0]['full_name']} ({payload.phone}) endi admin."}
