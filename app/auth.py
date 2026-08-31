from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address

from . import models, schemas
from .deps import get_current_user, row_to_user
from .security import create_access_token, hash_password, verify_password
from .turso_client import query_turso, ensure_admins_table, TursoNotConfigured

router = APIRouter(prefix="/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)


@router.post("/register", response_model=schemas.UserOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")  # bitta IP daqiqasiga 5 ta ro'yxatdan o'tish urinishi — spam botlardan himoya
async def register(request: Request, payload: schemas.UserRegister):
    try:
        await ensure_admins_table()

        existing = await query_turso(
            "SELECT id FROM backend_admins WHERE phone = ?", (payload.phone,)
        )
        if existing:
            # Telefon raqam allaqachon ro'yxatdan o'tganini aniq aytmaymiz — bu orqali
            # tashqi odam "qaysi raqamlar ro'yxatdan o'tgan" ekanini bilib ololmaydi
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ro'yxatdan o'tishda xatolik. Ma'lumotlarni tekshirib qayta urinib ko'ring.",
            )

        created_at = datetime.now(timezone.utc).isoformat()
        await query_turso(
            "INSERT INTO backend_admins "
            "(full_name, phone, password_hash, role, region, district, is_active, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
            (
                payload.full_name,
                payload.phone,
                hash_password(payload.password),
                payload.role.value,
                payload.region,
                payload.district,
                created_at,
            ),
        )
        rows = await query_turso("SELECT * FROM backend_admins WHERE phone = ?", (payload.phone,))
        return row_to_user(rows[0])
    except TursoNotConfigured as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))


@router.post("/login", response_model=schemas.Token)
@limiter.limit("10/minute")  # brute-force parol urinishlarini sekinlashtiradi
async def login(request: Request, payload: schemas.UserLogin):
    try:
        await ensure_admins_table()
        rows = await query_turso("SELECT * FROM backend_admins WHERE phone = ?", (payload.phone,))
    except TursoNotConfigured as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))

    # Ataylab bir xil, umumiy xato xabari: "raqam topilmadi" va "parol xato"ni
    # ajratib bermaymiz — aks holda hujumchi qaysi raqamlar mavjudligini bilib olishi mumkin
    generic_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Telefon raqam yoki parol noto'g'ri",
    )

    if not rows or not verify_password(payload.password, rows[0]["password_hash"]):
        raise generic_error

    user = row_to_user(rows[0])
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Hisob faol emas")

    token = create_access_token(subject=user.phone)
    return schemas.Token(access_token=token)


@router.get("/me", response_model=schemas.UserOut)
def read_current_user(current_user: models.User = Depends(get_current_user)):
    return current_user
