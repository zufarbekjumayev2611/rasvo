"""
Botning Turso (libSQL) bazasiga so'rov yuborish uchun yordamchi funksiya.

TURSO_DATABASE_URL va TURSO_AUTH_TOKEN backend'ning `.env` faylida bo'lishi kerak.
Bu qiymatlar bot uchun ishlatilayotgan bazaning O'ZI — botning kodini o'zgartirish
shart emas, biz faqat o'qish (SELECT) uchun ulanamiz.
"""
import libsql_client

from .config import settings


class TursoNotConfigured(Exception):
    pass


async def query_turso(sql: str, params: tuple = ()) -> list[dict]:
    """
    SQL so'rovni Turso'da bajaradi va natijani lug'atlar ro'yxati sifatida qaytaradi
    (masalan: [{"full_name": "Aziz", "phone": "+998..."}, ...]).
    """
    if not settings.turso_database_url or not settings.turso_auth_token:
        raise TursoNotConfigured(
            "TURSO_DATABASE_URL yoki TURSO_AUTH_TOKEN backend .env faylida sozlanmagan"
        )

    client = libsql_client.create_client(
        url=settings.turso_database_url,
        auth_token=settings.turso_auth_token,
    )
    try:
        result = await client.execute(sql, params)
        columns = result.columns
        return [dict(zip(columns, row)) for row in result.rows]
    finally:
        await client.close()


_admins_table_ready = False


async def ensure_admins_table():
    """
    Sayt/admin panel uchun login hisoblari saqlanadigan 'backend_admins'
    jadvali Turso'da mavjudligini ta'minlaydi (bir marta yaratiladi).
    Botning o'z 'users' jadvalidan ATAYLAB alohida nom bilan — ikkalasi
    bir-biriga aralashmasin, sxemasi ham boshqacha.
    """
    global _admins_table_ready
    if _admins_table_ready:
        return
    await query_turso(
        "CREATE TABLE IF NOT EXISTS backend_admins ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "full_name TEXT NOT NULL, "
        "phone TEXT NOT NULL UNIQUE, "
        "password_hash TEXT NOT NULL, "
        "role TEXT NOT NULL, "
        "region TEXT, "
        "district TEXT, "
        "is_active INTEGER NOT NULL DEFAULT 1, "
        "created_at TEXT NOT NULL)"
    )
    _admins_table_ready = True
