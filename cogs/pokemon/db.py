import os
import time

import aiosqlite

# 기본은 작업 디렉터리의 pokedex.db. ARENA_POKEMON_DB_PATH 로 재정의 가능(도커 볼륨 등).
DB_PATH = os.environ.get("ARENA_POKEMON_DB_PATH", "pokedex.db")


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """CREATE TABLE IF NOT EXISTS species (
                id INTEGER PRIMARY KEY,
                name_en TEXT NOT NULL,
                name_ko TEXT NOT NULL,
                type1 TEXT NOT NULL,
                type2 TEXT,
                hp INTEGER NOT NULL,
                atk INTEGER NOT NULL,
                def_ INTEGER NOT NULL,
                spatk INTEGER NOT NULL,
                spdef INTEGER NOT NULL,
                speed INTEGER NOT NULL,
                capture_rate INTEGER NOT NULL,
                is_legendary INTEGER NOT NULL DEFAULT 0,
                is_mythical INTEGER NOT NULL DEFAULT 0,
                rarity TEXT NOT NULL,
                sprite_url TEXT,
                evolves_to INTEGER,
                evolve_level INTEGER
            )"""
        )
        await db.execute(
            """CREATE TABLE IF NOT EXISTS user_pokemon (
                uid INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER NOT NULL,
                species_id INTEGER NOT NULL,
                nickname TEXT,
                level INTEGER NOT NULL DEFAULT 1,
                exp INTEGER NOT NULL DEFAULT 0,
                is_partner INTEGER NOT NULL DEFAULT 0,
                caught_at REAL NOT NULL
            )"""
        )
        await db.execute(
            """CREATE TABLE IF NOT EXISTS user_items (
                user_id INTEGER,
                item_name TEXT,
                amount INTEGER,
                PRIMARY KEY (user_id, item_name)
            )"""
        )
        await db.execute(
            """CREATE TABLE IF NOT EXISTS user_daily (
                user_id INTEGER,
                kind TEXT,
                last_date TEXT,
                PRIMARY KEY (user_id, kind)
            )"""
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_pokemon_owner ON user_pokemon (owner_id)"
        )
        # 볼 이름 개편(일반볼 → 몬스터볼) 이전에 지급된 보유분을 옮긴다.
        await db.execute(
            """INSERT INTO user_items (user_id, item_name, amount)
               SELECT user_id, '몬스터볼', amount FROM user_items WHERE item_name = '일반볼'
               ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + excluded.amount"""
        )
        await db.execute("DELETE FROM user_items WHERE item_name = '일반볼'")
        await db.commit()


# ==========================================
# 종(species) 관련 함수
# ==========================================

_UPSERT_SPECIES_SQL = """INSERT INTO species
        (id, name_en, name_ko, type1, type2, hp, atk, def_, spatk, spdef, speed,
         capture_rate, is_legendary, is_mythical, rarity, sprite_url, evolves_to, evolve_level)
       VALUES (:id, :name_en, :name_ko, :type1, :type2, :hp, :atk, :def_, :spatk, :spdef, :speed,
               :capture_rate, :is_legendary, :is_mythical, :rarity, :sprite_url, :evolves_to, :evolve_level)
       ON CONFLICT(id) DO UPDATE SET
         name_en=excluded.name_en, name_ko=excluded.name_ko,
         type1=excluded.type1, type2=excluded.type2,
         hp=excluded.hp, atk=excluded.atk, def_=excluded.def_,
         spatk=excluded.spatk, spdef=excluded.spdef, speed=excluded.speed,
         capture_rate=excluded.capture_rate, is_legendary=excluded.is_legendary,
         is_mythical=excluded.is_mythical, rarity=excluded.rarity,
         sprite_url=excluded.sprite_url, evolves_to=excluded.evolves_to,
         evolve_level=excluded.evolve_level"""


async def upsert_species(row: dict):
    """시딩 스크립트 전용: 종 데이터를 삽입하거나 갱신합니다."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(_UPSERT_SPECIES_SQL, row)
        await db.commit()


async def upsert_species_many(rows: list[dict]):
    """시딩 스크립트 전용: 여러 종을 한 연결/한 트랜잭션으로 기록합니다.

    SQLite 는 동시 writer 를 허용하지 않아, 종마다 새 연결로 write 하면
    'database is locked' 로 시딩이 중간에 깨집니다. 수집은 병렬로 하되
    기록은 여기로 모아서 한 번에 처리합니다.
    """
    if not rows:
        return
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.executemany(_UPSERT_SPECIES_SQL, rows)
        await db.commit()


async def get_species(species_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM species WHERE id = ?", (species_id,)) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None


async def get_random_species_id(rarity_weights: dict[str, float]) -> int | None:
    """등급별 가중치에 따라 무작위 종 하나를 뽑아 species_id를 반환합니다."""
    async with aiosqlite.connect(DB_PATH) as db:
        placeholders = ",".join("?" for _ in rarity_weights)
        async with db.execute(
            f"SELECT id, rarity FROM species WHERE rarity IN ({placeholders})",
            tuple(rarity_weights.keys()),
        ) as cursor:
            rows = await cursor.fetchall()
        if not rows:
            return None
        import random

        weights = [rarity_weights[r] for _, r in rows]
        return random.choices([sid for sid, _ in rows], weights=weights, k=1)[0]


async def species_count() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM species") as cursor:
            row = await cursor.fetchone()
        return row[0] if row else 0


# ==========================================
# 유저 보유 포켓몬 관련 함수
# ==========================================

async def add_user_pokemon(owner_id: int, species_id: int, is_partner: bool = False) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO user_pokemon (owner_id, species_id, level, exp, is_partner, caught_at)
               VALUES (?, ?, 1, 0, ?, ?)""",
            (owner_id, species_id, int(is_partner), time.time()),
        )
        await db.commit()
        return cursor.lastrowid


async def get_user_pokemon_count(owner_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM user_pokemon WHERE owner_id = ?", (owner_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else 0


async def list_user_pokemon(owner_id: int, limit: int = 20, offset: int = 0):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT up.uid, up.species_id, up.nickname, up.level, up.exp, up.is_partner,
                      up.caught_at, s.name_ko, s.rarity, s.sprite_url
               FROM user_pokemon up JOIN species s ON up.species_id = s.id
               WHERE up.owner_id = ?
               ORDER BY up.is_partner DESC, up.caught_at DESC
               LIMIT ? OFFSET ?""",
            (owner_id, limit, offset),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# ==========================================
# 유저 아이템(볼 등) 관련 함수
# ==========================================

async def get_item_amount(user_id: int, item_name: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT amount FROM user_items WHERE user_id = ? AND item_name = ?",
            (user_id, item_name),
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else 0


async def add_item(user_id: int, item_name: str, amount: int = 1):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO user_items (user_id, item_name, amount) VALUES (?, ?, ?)
               ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + ?""",
            (user_id, item_name, amount, amount),
        )
        await db.commit()


async def consume_item(user_id: int, item_name: str, amount: int = 1) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT amount FROM user_items WHERE user_id = ? AND item_name = ?",
            (user_id, item_name),
        ) as cursor:
            row = await cursor.fetchone()
        if not row or row[0] < amount:
            return False
        await db.execute(
            "UPDATE user_items SET amount = amount - ? WHERE user_id = ? AND item_name = ?",
            (amount, user_id, item_name),
        )
        await db.execute("DELETE FROM user_items WHERE amount <= 0")
        await db.commit()
        return True


async def list_items(user_id: int) -> dict[str, int]:
    """유저의 전체 소지품을 {아이템명: 개수} 로 반환합니다."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT item_name, amount FROM user_items WHERE user_id = ? AND amount > 0",
            (user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
    return {name: amount for name, amount in rows}


async def try_claim_daily(user_id: int, kind: str, today: str) -> bool:
    """오늘치 일일 보상을 아직 안 받았으면 받은 것으로 기록하고 True 를 반환합니다.

    이미 받았으면 아무것도 하지 않고 False. (하루 한 번 제한)
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT last_date FROM user_daily WHERE user_id = ? AND kind = ?",
            (user_id, kind),
        ) as cursor:
            row = await cursor.fetchone()
        if row and row[0] == today:
            return False
        await db.execute(
            """INSERT INTO user_daily (user_id, kind, last_date) VALUES (?, ?, ?)
               ON CONFLICT(user_id, kind) DO UPDATE SET last_date = excluded.last_date""",
            (user_id, kind, today),
        )
        await db.commit()
        return True


async def ensure_starter_balls(user_id: int, ball_name: str, amount: int):
    """유저가 볼을 하나도 가진 적 없으면(행이 없으면) 초기 볼을 지급합니다."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM user_items WHERE user_id = ? AND item_name = ?",
            (user_id, ball_name),
        ) as cursor:
            row = await cursor.fetchone()
        if row:
            return
        await db.execute(
            "INSERT INTO user_items (user_id, item_name, amount) VALUES (?, ?, ?)",
            (user_id, ball_name, amount),
        )
        await db.commit()
