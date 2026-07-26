from . import db

# PokeAPI 타입 슬러그 → 한글 표기
TYPE_KO = {
    "normal": "노말", "fire": "불꽃", "water": "물", "electric": "전기",
    "grass": "풀", "ice": "얼음", "fighting": "격투", "poison": "독",
    "ground": "땅", "flying": "비행", "psychic": "에스퍼", "bug": "벌레",
    "rock": "바위", "ghost": "고스트", "dragon": "드래곤", "dark": "악",
    "steel": "강철", "fairy": "페어리",
}

# 등급별 야생 스폰 가중치 (숫자가 클수록 더 자주 나옵니다)
# 전설·환상은 원작에서도 야생에서 그냥 잡히는 포켓몬이 아니므로 스폰 대상에서 제외한다.
# (여기에 없는 등급은 아예 뽑히지 않는다 — get_random_species_id 가 이 키만 조회함)
RARITY_SPAWN_WEIGHTS = {
    "일반": 100,
    "희귀": 35,
    "에픽": 12,
}


async def get_random_wild():
    """야생에 스폰될 종을 등급 가중치에 따라 무작위로 뽑아 상세 정보를 반환합니다."""
    species_id = await db.get_random_species_id(RARITY_SPAWN_WEIGHTS)
    if species_id is None:
        return None
    return await db.get_species(species_id)


async def get_by_id(species_id: int):
    return await db.get_species(species_id)
