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
