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
        # 파티(데리고 다니는 6마리) 여부. 나머지는 박스에 보관된다.
        try:
            await db.execute("ALTER TABLE user_pokemon ADD COLUMN in_party INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass    # 이미 있으면 무시
        # 기존 파트너는 파티에 있는 것으로 취급
        await db.execute("UPDATE user_pokemon SET in_party = 1 WHERE is_partner = 1 AND in_party = 0")
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

async def add_user_pokemon(owner_id: int, species_id: int, is_partner: bool = False,
                           party_size: int = 6) -> int:
    """새로 잡은 포켓몬을 등록한다. 파티에 자리가 남아 있으면 자동으로 파티에 넣는다."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM user_pokemon WHERE owner_id = ? AND in_party = 1",
            (owner_id,)) as cur:
            in_party = (await cur.fetchone())[0]
        join = 1 if (is_partner or in_party < party_size) else 0
        cursor = await db.execute(
            """INSERT INTO user_pokemon
                 (owner_id, species_id, level, exp, is_partner, in_party, caught_at)
               VALUES (?, ?, 1, 0, ?, ?, ?)""",
            (owner_id, species_id, int(is_partner), join, time.time()),
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

# ==========================================
# 전설·환상 특별 조우 일정
# ==========================================

async def init_legendary_table():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """CREATE TABLE IF NOT EXISTS legendary_events (
                day TEXT, idx INTEGER, at REAL, done INTEGER DEFAULT 0,
                PRIMARY KEY (day, idx)
            )"""
        )
        await db.commit()


async def get_day_schedule(day: str) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT day, idx, at, done FROM legendary_events WHERE day = ? ORDER BY idx",
            (day,)) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def set_day_schedule(day: str, times: list[float]):
    """그 날의 등장 시각을 저장한다. 이미 있으면 덮어쓰지 않는다."""
    async with aiosqlite.connect(DB_PATH) as db:
        for i, t in enumerate(times):
            await db.execute(
                "INSERT OR IGNORE INTO legendary_events (day, idx, at, done) VALUES (?,?,?,0)",
                (day, i, t))
        await db.commit()


async def mark_legendary_done(day: str, idx: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE legendary_events SET done = 1 WHERE day = ? AND idx = ?",
                         (day, idx))
        await db.commit()


async def find_species_by_name(name: str, rarities: tuple = ()) -> list[dict]:
    """이름으로 종을 찾는다. rarities 를 주면 그 등급만.

    정확히 일치하는 이름을 맨 앞에 둔다.
    (부분 일치만 쓰면 '뮤' 를 찾을 때 '뮤츠' 가 먼저 걸린다)
    """
    sql = "SELECT * FROM species WHERE name_ko LIKE ?"
    params = [f"%{name}%"]
    if rarities:
        sql += f" AND rarity IN ({','.join('?' * len(rarities))})"
        params += list(rarities)
    sql += " ORDER BY CASE WHEN name_ko = ? THEN 0 ELSE 1 END, LENGTH(name_ko), id LIMIT 25"
    params.append(name)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql, params) as cur:
            return [dict(r) for r in await cur.fetchall()]


# ── 웹 등 외부에서 들어온 요청 큐 (봇이 주기적으로 처리) ──
async def init_request_queue():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """CREATE TABLE IF NOT EXISTS admin_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT, payload TEXT, actor TEXT,
                created_at REAL, done INTEGER DEFAULT 0, result TEXT
            )"""
        )
        await db.commit()


async def enqueue_request(kind: str, payload: str, actor: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO admin_requests (kind, payload, actor, created_at, done) "
            "VALUES (?,?,?,?,0)", (kind, payload, actor, time.time()))
        await db.commit()
        return cur.lastrowid


async def fetch_pending_requests(limit: int = 10) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM admin_requests WHERE done = 0 ORDER BY id LIMIT ?", (limit,)) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def complete_request(req_id: int, result: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE admin_requests SET done = 1, result = ? WHERE id = ?",
                         (result[:500], req_id))
        await db.commit()


async def purge_old_legendary(before_day: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM legendary_events WHERE day < ?", (before_day,))
        await db.commit()


# ==========================================
# 파티 / 레벨 / 진화
# ==========================================

async def get_party(owner_id: int) -> list[dict]:
    """데리고 다니는 포켓몬(최대 6마리). 파트너가 맨 앞."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT up.uid, up.species_id, up.nickname, up.level, up.exp,
                      up.is_partner, up.in_party, up.caught_at,
                      s.name_ko, s.rarity, s.sprite_url, s.evolves_to, s.evolve_level
               FROM user_pokemon up JOIN species s ON up.species_id = s.id
               WHERE up.owner_id = ? AND up.in_party = 1
               ORDER BY up.is_partner DESC, up.caught_at""",
            (owner_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_pokemon(uid: int, owner_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT up.*, s.name_ko, s.rarity, s.sprite_url, s.evolves_to, s.evolve_level
               FROM user_pokemon up JOIN species s ON up.species_id = s.id
               WHERE up.uid = ? AND up.owner_id = ?""",
            (uid, owner_id),
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None


async def set_party(uid: int, owner_id: int, value: bool) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE user_pokemon SET in_party = ? WHERE uid = ? AND owner_id = ?",
            (int(value), uid, owner_id))
        if not value:
            # 파티에서 빼면 파트너 자격도 잃는다.
            await db.execute(
                "UPDATE user_pokemon SET is_partner = 0 WHERE uid = ? AND owner_id = ?",
                (uid, owner_id))
        await db.commit()
        return cur.rowcount > 0


async def set_partner(uid: int, owner_id: int) -> bool:
    """파트너를 지정한다. 파티에 없으면 파티에도 넣는다."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT in_party FROM user_pokemon WHERE uid = ? AND owner_id = ?",
            (uid, owner_id)) as cur:
            row = await cur.fetchone()
        if row is None:
            return False
        await db.execute("UPDATE user_pokemon SET is_partner = 0 WHERE owner_id = ?", (owner_id,))
        await db.execute(
            "UPDATE user_pokemon SET is_partner = 1, in_party = 1 WHERE uid = ? AND owner_id = ?",
            (uid, owner_id))
        await db.commit()
        return True


async def add_exp(uid: int, amount: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE user_pokemon SET exp = exp + ? WHERE uid = ?", (amount, uid))
        await db.commit()


async def apply_level(uid: int, level: int, exp: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE user_pokemon SET level = ?, exp = ? WHERE uid = ?",
                         (level, exp, uid))
        await db.commit()


async def evolve(uid: int, new_species_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE user_pokemon SET species_id = ? WHERE uid = ?",
                         (new_species_id, uid))
        await db.commit()


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
    """트레이너가 된 첫 순간에만 초기 볼을 지급합니다.

    예전에는 '볼 행이 있는지'로 판단했는데, consume_item 이 0개가 된 행을 지우기 때문에
    볼을 다 쓰면 행이 사라져 5개가 무한으로 재지급됐다.
    지급 여부를 user_daily 에 영구 기록해서 한 번만 나가도록 한다.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM user_daily WHERE user_id = ? AND kind = 'starter_balls'",
            (user_id,),
        ) as cursor:
            if await cursor.fetchone():
                return
        await db.execute(
            "INSERT OR REPLACE INTO user_daily (user_id, kind, last_date) "
            "VALUES (?, 'starter_balls', 'given')",
            (user_id,),
        )
        await db.execute(
            "INSERT INTO user_items (user_id, item_name, amount) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + excluded.amount",
            (user_id, ball_name, amount),
        )
        await db.commit()
