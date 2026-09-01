from fastapi import APIRouter, Depends, HTTPException, Query, status

from . import models
from .deps import require_admin
from .turso_client import query_turso, TursoNotConfigured

router = APIRouter(tags=["turso"])


@router.get("/admin/students")
async def list_students(
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None),
    missed_last_session: bool = Query(False),
    _admin: models.User = Depends(require_admin),
):
    """
    Botda ro'yxatdan o'tgan o'quvchilarni sahifalab qaytaradi (faqat admin ko'ra oladi).
    Manba: Turso'dagi 'users' jadvali (botning o'zi).

    - search: ism/familiya bo'yicha qidiradi (katta-kichik harf farqi yo'q)
    - missed_last_session: True bo'lsa, faqat ENG OXIRGI davomat sessiyasida
      qatnashmagan o'quvchilarni qaytaradi
    """
    try:
        where_clauses = []
        params: list = []

        if search:
            where_clauses.append("LOWER(full_name) LIKE ?")
            params.append(f"%{search.strip().lower()}%")

        if missed_last_session:
            last_session_rows = await query_turso(
                "SELECT id FROM attendance_sessions ORDER BY created_at DESC LIMIT 1"
            )
            if not last_session_rows:
                # Hali birorta ham davomat sessiyasi bo'lmagan
                return {"items": [], "total": 0, "no_session": True}
            last_session_id = last_session_rows[0]["id"]
            where_clauses.append(
                "telegram_id NOT IN (SELECT telegram_id FROM attendance_records WHERE session_id = ?)"
            )
            params.append(last_session_id)

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        total_rows = await query_turso(f"SELECT COUNT(*) AS cnt FROM users {where_sql}", tuple(params))
        total = total_rows[0]["cnt"] if total_rows else 0

        items = await query_turso(
            f"SELECT telegram_id, full_name, course, region, district, phone, registered_at, role "
            f"FROM users {where_sql} ORDER BY registered_at DESC LIMIT ? OFFSET ?",
            tuple(params) + (limit, offset),
        )
        return {"items": items, "total": total}
    except TursoNotConfigured as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))


@router.get("/public/stats")
async def public_stats():
    """
    Sayt bosh sahifasidagi statistika uchun (login talab qilinmaydi).
    Faqat sonlar qaytadi — hech qanday shaxsiy ma'lumot (ism, telefon) yo'q.
    """
    try:
        students = await query_turso("SELECT COUNT(*) AS cnt FROM users")
        certs = await query_turso("SELECT COUNT(DISTINCT telegram_id) AS cnt FROM aplus_submissions")
        return {
            "students": students[0]["cnt"] if students else 0,
            "certificates": certs[0]["cnt"] if certs else 0,
        }
    except TursoNotConfigured:
        return {"students": 0, "certificates": 0}
