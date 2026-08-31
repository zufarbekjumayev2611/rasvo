from datetime import datetime

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from . import models
from .security import decode_access_token
from .turso_client import query_turso, ensure_admins_table, TursoNotConfigured

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Tizimga kirish talab qilinadi yoki token yaroqsiz",
    headers={"WWW-Authenticate": "Bearer"},
)


def row_to_user(row: dict) -> models.User:
    """Turso'dan kelgan qatorni models.User obyektiga aylantiradi
    (ma'lumotlar bazasiga yozmasdan, faqat xotirada — attributlarga
    kirish uchun)."""
    return models.User(
        id=row["id"],
        full_name=row["full_name"],
        phone=row["phone"],
        password_hash=row["password_hash"],
        role=models.UserRole(row["role"]),
        region=row.get("region"),
        district=row.get("district"),
        is_active=bool(row["is_active"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


async def get_current_user(token: str = Depends(oauth2_scheme)) -> models.User:
    phone = decode_access_token(token)
    if phone is None:
        raise CREDENTIALS_ERROR

    try:
        await ensure_admins_table()
        rows = await query_turso("SELECT * FROM backend_admins WHERE phone = ?", (phone,))
    except TursoNotConfigured:
        raise CREDENTIALS_ERROR

    if not rows or not rows[0]["is_active"]:
        raise CREDENTIALS_ERROR

    return row_to_user(rows[0])


def require_admin(current_user: models.User = Depends(get_current_user)) -> models.User:
    if current_user.role != models.UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu amal faqat admin uchun ruxsat etilgan",
        )
    return current_user
