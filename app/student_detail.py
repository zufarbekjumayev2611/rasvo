from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from . import models, schemas
from .deps import require_admin
from .turso_client import query_turso, TursoNotConfigured

router = APIRouter(tags=["student-detail"])

_notes_table_ready = False


async def _ensure_notes_table():
    """Turso'da 'admin_notes' jadvali mavjudligini ta'minlaydi (bir marta,
    keyingi so'rovlarda qayta tekshirilmaydi)."""
    global _notes_table_ready
    if _notes_table_ready:
        return
    await query_turso(
        "CREATE TABLE IF NOT EXISTS admin_notes ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "telegram_id INTEGER NOT NULL, "
        "author_name TEXT NOT NULL, "
        "note TEXT NOT NULL, "
        "created_at TEXT NOT NULL)"
    )
    _notes_table_ready = True


@router.get("/admin/students/{telegram_id}/detail")
async def student_detail(telegram_id: int, _admin: models.User = Depends(require_admin)):
    """
    Bitta o'quvchi haqida ma'lumot: oddiy testlar, A+ testlar, davomat.
    Hammasi Turso'dan (faqat o'qish).

    Eslatma: 'score_adjustments' (ball tuzatishlari) ATAYLAB bu yerga
    qo'shilmagan — bu ma'lumot maxfiy va faqat cofounderlar uchun,
    oddiy admin panelida umuman ko'rsatilmaydi.
    """
    try:
        test_results = await query_turso(
            "SELECT t.name AS test_name, t.total_questions, ts.score, ts.submitted_at "
            "FROM test_submissions ts JOIN tests t ON ts.test_id = t.id "
            "WHERE ts.telegram_id = ? ORDER BY ts.submitted_at DESC",
            (telegram_id,),
        )

        aplus_results = await query_turso(
            "SELECT at.name AS test_name, at.question_count, aps.score, aps.submitted_at "
            "FROM aplus_submissions aps JOIN aplus_tests at ON aps.test_id = at.id "
            "WHERE aps.telegram_id = ? ORDER BY aps.submitted_at DESC",
            (telegram_id,),
        )

        attendance = await query_turso(
            "SELECT s.id AS session_id, s.code, s.created_at, "
            "CASE WHEN r.telegram_id IS NOT NULL THEN 1 ELSE 0 END AS attended "
            "FROM attendance_sessions s "
            "LEFT JOIN attendance_records r ON r.session_id = s.id AND r.telegram_id = ? "
            "ORDER BY s.created_at DESC",
            (telegram_id,),
        )

        return {
            "test_results": test_results,
            "aplus_results": aplus_results,
            "attendance": attendance,
        }
    except TursoNotConfigured:
        return {"test_results": [], "aplus_results": [], "attendance": []}


@router.get("/admin/students/{telegram_id}/notes")
async def list_notes(
    telegram_id: int,
    _admin: models.User = Depends(require_admin),
):
    """
    Bu o'quvchi haqidagi barcha izohlarni Turso'dan o'qiydi
    ('admin_notes' jadvali — botning jadvallaridan alohida, faqat
    admin panel ishlatadi).
    """
    try:
        await _ensure_notes_table()
        return await query_turso(
            "SELECT id, telegram_id, author_name, note, created_at "
            "FROM admin_notes WHERE telegram_id = ? ORDER BY created_at DESC",
            (telegram_id,),
        )
    except TursoNotConfigured as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))


@router.post("/admin/students/{telegram_id}/notes", status_code=201)
async def add_note(
    telegram_id: int,
    payload: schemas.NoteCreate,
    admin: models.User = Depends(require_admin),
):
    try:
        await _ensure_notes_table()
        created_at = datetime.now(timezone.utc).isoformat()
        await query_turso(
            "INSERT INTO admin_notes (telegram_id, author_name, note, created_at) "
            "VALUES (?, ?, ?, ?)",
            (telegram_id, admin.full_name, payload.note, created_at),
        )
        return {
            "telegram_id": telegram_id,
            "author_name": admin.full_name,
            "note": payload.note,
            "created_at": created_at,
        }
    except TursoNotConfigured as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
