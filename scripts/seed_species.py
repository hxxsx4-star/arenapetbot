"""
전국도감 시딩 스크립트 (1회성, 수동 실행)

PokeAPI(https://pokeapi.co, 무료 공개 API, 키 불필요)에서 포켓몬 종 데이터를 가져와
pokedex.db 의 species 테이블을 채웁니다. 런타임 봇 코드는 이 스크립트가 만든 로컬 DB만
읽고, PokeAPI를 직접 호출하지 않습니다.

사용법:
    python scripts/seed_species.py
"""
import asyncio
import sys
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cogs.pokemon import db  # noqa: E402

API_BASE = "https://pokeapi.co/api/v2"
CONCURRENCY = 10
MAX_RETRIES = 3

STAT_KEY_MAP = {
    "hp": "hp",
    "attack": "atk",
    "defense": "def_",
    "special-attack": "spatk",
    "special-defense": "spdef",
    "speed": "speed",
}


async def fetch_json(session: aiohttp.ClientSession, url: str, sem: asyncio.Semaphore):
    async with sem:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    if resp.status == 404:
                        return None
                    resp.raise_for_status()
                    return await resp.json()
            except Exception as e:
                if attempt == MAX_RETRIES:
                    print(f"🚨 요청 실패({url}): {e}")
                    return None
                await asyncio.sleep(1.5 * attempt)


def classify_rarity(is_legendary: bool, is_mythical: bool, capture_rate: int, bst: int) -> str:
    if is_mythical:
        return "환상"
    if is_legendary:
        return "전설"
    if bst >= 500:
        return "에픽"
    if capture_rate <= 45:
        return "희귀"
    return "일반"


async def resolve_evolution(
    session: aiohttp.ClientSession, sem: asyncio.Semaphore, chain_url: str,
    species_name: str, chain_cache: dict,
):
    """진화 체인을 조회해 (다음 진화 종 id, 필요 레벨) 을 반환합니다. 없으면 (None, None)."""
    if chain_url not in chain_cache:
        chain_cache[chain_url] = await fetch_json(session, chain_url, sem)
    chain_data = chain_cache[chain_url]
    if not chain_data:
        return None, None

    def find_node(node):
        if node["species"]["name"] == species_name:
            return node
        for child in node["evolves_to"]:
            found = find_node(child)
            if found:
                return found
        return None

    node = find_node(chain_data["chain"])
    if not node or not node["evolves_to"]:
        return None, None

    next_node = node["evolves_to"][0]
    next_species_url = next_node["species"]["url"]
    next_id = int(next_species_url.rstrip("/").split("/")[-1])

    min_level = None
    details = next_node.get("evolution_details") or []
    if details and details[0].get("min_level"):
        min_level = details[0]["min_level"]

    return next_id, min_level


async def seed_one(session, sem, species_id: int, chain_cache: dict):
    """한 종의 데이터를 수집해 DB 행(dict)으로 반환합니다. 기록은 호출자가 일괄 처리합니다."""
    species_data = await fetch_json(session, f"{API_BASE}/pokemon-species/{species_id}/", sem)
    if not species_data:
        print(f"⚠️ species {species_id} 조회 실패, 건너뜀")
        return None

    pokemon_data = await fetch_json(session, f"{API_BASE}/pokemon/{species_id}/", sem)
    if not pokemon_data:
        default_variety = next(
            (v for v in species_data.get("varieties", []) if v.get("is_default")), None
        )
        if default_variety:
            pokemon_data = await fetch_json(session, default_variety["pokemon"]["url"], sem)
    if not pokemon_data:
        print(f"⚠️ pokemon {species_id} 조회 실패, 건너뜀")
        return None

    name_ko = next(
        (n["name"] for n in species_data.get("names", []) if n["language"]["name"] == "ko"),
        species_data["name"].capitalize(),
    )

    types = sorted(pokemon_data["types"], key=lambda t: t["slot"])
    type1 = types[0]["type"]["name"]
    type2 = types[1]["type"]["name"] if len(types) > 1 else None

    stats = {STAT_KEY_MAP[s["stat"]["name"]]: s["base_stat"] for s in pokemon_data["stats"]}
    bst = sum(stats.values())

    is_legendary = bool(species_data.get("is_legendary"))
    is_mythical = bool(species_data.get("is_mythical"))
    capture_rate = species_data.get("capture_rate", 45)
    rarity = classify_rarity(is_legendary, is_mythical, capture_rate, bst)

    sprites = pokemon_data.get("sprites", {})
    sprite_url = (
        (sprites.get("other", {}).get("official-artwork", {}) or {}).get("front_default")
        or sprites.get("front_default")
    )

    evolves_to, evolve_level = (None, None)
    chain_url = (species_data.get("evolution_chain") or {}).get("url")
    if chain_url:
        evolves_to, evolve_level = await resolve_evolution(
            session, sem, chain_url, species_data["name"], chain_cache
        )

    row = {
        "id": species_id,
        "name_en": species_data["name"],
        "name_ko": name_ko,
        "type1": type1,
        "type2": type2,
        "capture_rate": capture_rate,
        "is_legendary": int(is_legendary),
        "is_mythical": int(is_mythical),
        "rarity": rarity,
        "sprite_url": sprite_url,
        "evolves_to": evolves_to,
        "evolve_level": evolve_level,
        **stats,
    }
    return row


async def main():
    await db.init_db()

    async with aiohttp.ClientSession() as session:
        count_data = await fetch_json(session, f"{API_BASE}/pokemon-species?limit=1", asyncio.Semaphore(1))
        total = count_data["count"] if count_data else 1025
        print(f"📖 전국도감 {total}마리 시딩을 시작합니다...")

        sem = asyncio.Semaphore(CONCURRENCY)
        chain_cache: dict = {}
        done = 0

        async def run_one(species_id):
            nonlocal done
            row = await seed_one(session, sem, species_id, chain_cache)
            done += 1
            if done % 50 == 0:
                print(f"  ...{done}/{total}")
            return row

        rows = await asyncio.gather(*(run_one(i) for i in range(1, total + 1)))

    # 수집이 끝난 뒤 한 번에 기록 (SQLite 는 동시 writer 불가)
    rows = [r for r in rows if r]
    print(f"💾 {len(rows)}행 기록 중...")
    for i in range(0, len(rows), 200):
        await db.upsert_species_many(rows[i:i + 200])

    final_count = await db.species_count()
    print(f"✅ 시딩 완료: species 테이블 {final_count}행")


if __name__ == "__main__":
    asyncio.run(main())
