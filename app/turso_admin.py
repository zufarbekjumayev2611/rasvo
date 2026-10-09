from fastapi import APIRouter, Depends, HTTPException, Query, status

from . import models
from .deps import require_admin
from .turso_client import query_turso, TursoNotConfigured

router = APIRouter(tags=["turso"])


# Har bir o'quvchi uchun vazifa/davomat hisobi FAQAT u ro'yxatdan o'tganidan keyingi
# testlar va davomat sessiyalari bo'yicha olinadi - yangi qo'shilgan o'quvchi
# hali bo'lmagan testlar uchun "qilmagan" hisoblanmaydi va ro'yxat tepasiga chiqmaydi.
_STUDENTS_SELECT = """
SELECT *,
       (tests_total - tests_done) AS tests_missed,
       (attendance_total - attendance_attended) AS attendance_missed
FROM (
    SELECT u.telegram_id, u.full_name, u.course, u.region, u.district, u.phone,
           u.registered_at, u.role,
           CAST(julianday('now') - julianday(u.registered_at) AS INTEGER) AS days_registered,
           COALESCE(ts.cnt, 0) + COALESCE(ap.cnt, 0) AS tests_done,
           (SELECT COUNT(*) FROM tests t WHERE t.created_at >= u.registered_at)
             + (SELECT COUNT(*) FROM aplus_tests t WHERE t.created_at >= u.registered_at) AS tests_total,
           COALESCE(att.cnt, 0) AS attendance_attended,
           (SELECT COUNT(*) FROM attendance_sessions s WHERE s.created_at >= u.registered_at) AS attendance_total
    FROM users u
    LEFT JOIN (
        SELECT s.telegram_id, COUNT(*) AS cnt
        FROM test_submissions s
        JOIN tests t ON t.id = s.test_id
        JOIN users x ON x.telegram_id = s.telegram_id
        WHERE t.created_at >= x.registered_at
        GROUP BY s.telegram_id
    ) ts ON ts.telegram_id = u.telegram_id
    LEFT JOIN (
        SELECT s.telegram_id, COUNT(*) AS cnt
        FROM aplus_submissions s
        JOIN aplus_tests t ON t.id = s.test_id
        JOIN users x ON x.telegram_id = s.telegram_id
        WHERE t.created_at >= x.registered_at
        GROUP BY s.telegram_id
    ) ap ON ap.telegram_id = u.telegram_id
    LEFT JOIN (
        SELECT r.telegram_id, COUNT(*) AS cnt
        FROM attendance_records r
        JOIN attendance_sessions a ON a.id = r.session_id
        JOIN users x ON x.telegram_id = r.telegram_id
        WHERE a.created_at >= x.registered_at
        GROUP BY r.telegram_id
    ) att ON att.telegram_id = u.telegram_id
    {where_sql}
)
ORDER BY {order_sql}
LIMIT ? OFFSET ?
"""

# "Eng yomonlar birinchi": ro'yxatdan o'tganidan beri eng ko'p vazifa qilmaganlar
# tepada; ko'p vazifa yuborgan pastga tushadi. Teng bo'lsa - avval ro'yxatdan
# o'tgani eskirog'i (necha kundan beri), keyin davomatdan ko'proq qolgani.
# telegram_id oxirida - sahifalashda ("Yana ko'rish") tartib barqaror bo'lishi uchun.
_ORDER_WORST_FIRST = (
    "tests_missed DESC, registered_at ASC, attendance_missed DESC, telegram_id ASC"
)
_ORDER_DEFAULT = "registered_at DESC, telegram_id ASC"


@router.get("/admin/students")
async def list_students(
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None),
    missed_last_session: bool = Query(False),
    sort: str | None = Query(None),
    _admin: models.User = Depends(require_admin),
):
    """
    Botda ro'yxatdan o'tgan o'quvchilarni sahifalab qaytaradi (faqat admin ko'ra oladi).
    Manba: Turso'dagi 'users' jadvali (botning o'zi).

    - search: ism/familiya bo'yicha qidiradi (katta-kichik harf farqi yo'q)
    - missed_last_session: True bo'lsa, faqat ENG OXIRGI davomat sessiyasida
      qatnashmagan o'quvchilarni qaytaradi
    - sort=worst_first: eng yomonlar birinchi - ro'yxatdan o'tganidan beri eng ko'p
      vazifa (oddiy + A+ test) qilmaganlar tepada, ko'p yuborganlar pastda.
      Teng bo'lsa: ro'yxatdan o'tgani eskirog'i, keyin davomatdan ko'p qolgani.

    Har bir o'quvchi uchun (ro'yxatdan o'tganidan keyingi davr bo'yicha) qaytadi:
    tests_done / tests_total / tests_missed, attendance_attended / attendance_total /
    attendance_missed va days_registered (necha kun oldin ro'yxatdan o'tgan).
    """
    try:
        where_clauses = []
        params: list = []

        if search:
            where_clauses.append("LOWER(u.full_name) LIKE ?")
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
                "u.telegram_id NOT IN (SELECT telegram_id FROM attendance_records WHERE session_id = ?)"
            )
            params.append(last_session_id)

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        total_rows = await query_turso(
            f"SELECT COUNT(*) AS cnt FROM users u {where_sql}", tuple(params)
        )
        total = total_rows[0]["cnt"] if total_rows else 0

        order_sql = _ORDER_WORST_FIRST if sort == "worst_first" else _ORDER_DEFAULT
        items = await query_turso(
            _STUDENTS_SELECT.format(where_sql=where_sql, order_sql=order_sql),
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
