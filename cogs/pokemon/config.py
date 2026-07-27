# 포켓몬 시스템 설정값
# 야생 포켓몬이 스폰될 채널. 비어 있으면 스폰이 꺼집니다. (여러 개 지정 가능)
SPAWN_CHANNEL_IDS: list[int] = [
    1530586085313216593,   # 포켓몬 스폰 채널
]

# 스폰 주기(분). 채팅량과 무관하게 이 간격으로 각 스폰 채널에 한 마리씩 나타납니다.
SPAWN_INTERVAL_MINUTES = 5

# 야생 포켓몬이 방치될 때 도망가기까지의 시간(초)
# 스폰 주기보다 짧아야 다음 스폰 전에 정리됩니다.
SPAWN_TIMEOUT_SEC = 120

# 볼 아이템 스프라이트 (PokeAPI 공개 이미지, 키 불필요)
_SPRITE = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/items/{}.png"

# 볼 종류별 설정. 이름은 PokeAPI 공식 한글명과 동일하다.
#   multiplier : 포획 확률 배율 (None 이면 무조건 성공 = 마스터볼)
#   price      : 상점 판매가(포인트). None 이면 판매하지 않음.
#   emoji/desc : 표시용
#   sprite     : 임베드 썸네일용 이미지 URL
BALLS = {
    "몬스터볼": {"multiplier": 1.0, "price": 50, "emoji": "⚪", "desc": "기본 볼",
                "sprite": _SPRITE.format("poke-ball")},
    "슈퍼볼":   {"multiplier": 1.5, "price": 150, "emoji": "🔵", "desc": "포획률 1.5배",
                "sprite": _SPRITE.format("great-ball")},
    "하이퍼볼": {"multiplier": 2.0, "price": 400, "emoji": "🟡", "desc": "포획률 2배",
                "sprite": _SPRITE.format("ultra-ball")},
    "마스터볼": {"multiplier": None, "price": 5000, "emoji": "🟣", "desc": "반드시 포획",
                "sprite": _SPRITE.format("master-ball")},
}
BALL_ORDER = ["몬스터볼", "슈퍼볼", "하이퍼볼", "마스터볼"]

# 포획 시 자동으로 사용할 볼의 우선순위.
# 낮은 등급부터 써서 좋은 볼을 아껴 둔다. 마스터볼은 자동 사용하지 않는다(직접 지정해야 함).
AUTO_BALL_ORDER = ["몬스터볼", "슈퍼볼", "하이퍼볼"]

DEFAULT_BALL = "몬스터볼"

# 신규 트레이너가 처음 받는 몬스터볼 개수
STARTER_BALL_AMOUNT = 5

# 하루 한 번 무료로 받는 몬스터볼 개수 (/볼받기)
DAILY_BALL_AMOUNT = 10

# 한 번에 살 수 있는 최대 개수 (오타로 전 재산 날리는 것 방지)
MAX_BUY_AMOUNT = 99

# ───────── 레벨 / 파티 ─────────
# 원작처럼 데리고 다니는 인원은 6마리. 나머지는 박스에 보관된다.
PARTY_SIZE = 6
MAX_LEVEL = 100

# 주인이 채팅하면 파티 전원이 경험치를 얻는다. (쿨다운으로 도배 방지)
CHAT_XP_MIN, CHAT_XP_MAX = 8, 14
CHAT_XP_COOLDOWN_SEC = 60
# 파트너(⭐)는 더 많이 받는다.
PARTNER_XP_MULTIPLIER = 2.0

# 레벨업·진화 알림을 보낼 채널. 유저가 대화 중인 채널을 어지럽히지 않도록 한곳에 모은다.
# 0 이면 알림을 보내지 않는다.
LEVELUP_LOG_CH = 1531310908536524892
# 포획 시 그 포켓몬이 받는 보너스 경험치
CATCH_XP = 30

# 진화 레벨이 정해지지 않은 종(진화의돌·교환 등 특수 조건)의 기본 진화 레벨.
# 이걸 두지 않으면 이브이·피카츄 같은 인기종이 영영 진화하지 못한다.
DEFAULT_EVOLVE_LEVEL = 36

# ───────── 일반 아이템 상점 ─────────
# 볼과 달리 포켓몬에게 '사용'하는 아이템들. (/아이템상점 · /아이템사용)
_ITEM_SPRITE = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/items/{}.png"
ITEMS = {
    "이상한사탕": {
        "price": 1500, "emoji": "🍬", "kind": "level",
        "desc": "포켓몬의 레벨을 1 올립니다",
        "sprite": _ITEM_SPRITE.format("rare-candy"),
    },
    "경험치사탕": {
        "price": 400, "emoji": "🍭", "kind": "exp", "value": 300,
        "desc": "경험치를 300 지급합니다",
        "sprite": _ITEM_SPRITE.format("exp-candy-m"),
    },
    "이름표": {
        "price": 300, "emoji": "🏷️", "kind": "nickname",
        "desc": "포켓몬에게 별명을 붙입니다",
        "sprite": _ITEM_SPRITE.format("name-tag"),
    },
}
ITEM_ORDER = ["이상한사탕", "경험치사탕", "이름표"]
MAX_NICKNAME_LEN = 12

# ───────── 전설·환상 특별 조우 ─────────
# 전설(71종)·환상(23종)은 평소 야생에 나오지 않는다. 하루 몇 번 정해진 시각에만
# 특별 조우로 등장시켜, 이때만 잡을 수 있게 한다.
LEGENDARY_SPAWNS_PER_DAY = 2
# 등장 가능 시간대(KST). 새벽에 떠서 아무도 못 잡는 일이 없도록 제한한다.
LEGENDARY_WINDOW_START_HOUR = 13
LEGENDARY_WINDOW_END_HOUR = 24
# 특별 조우는 도전 기회를 넉넉히 준다. (일반 스폰은 120초)
LEGENDARY_TIMEOUT_SEC = 600
# 등급별 등장 가중치 — 환상이 전설보다 훨씬 귀하다.
LEGENDARY_SPAWN_WEIGHTS = {
    "전설": 10,
    "환상": 1,
}
# 특별 조우 알림에 붙일 역할 멘션 (0 이면 멘션 없음)
LEGENDARY_PING_ROLE = 0
