from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import models
from .config import settings
from .database import get_db

router = APIRouter(tags=["setup"])


class PromoteRequest(BaseModel):
    phone: str
    setup_secret: str


@router.post("/setup/promote-admin")
def promote_admin(payload: PromoteRequest, db: Session = Depends(get_db)):
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

    user = db.query(models.User).filter(models.User.phone == payload.phone).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{payload.phone} raqamli foydalanuvchi topilmadi",
        )

    user.role = models.UserRole.admin
    db.commit()
    return {"detail": f"{user.full_name} ({user.phone}) endi admin."}