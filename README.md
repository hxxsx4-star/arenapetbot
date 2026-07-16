# arenapetbot

종합게임 아레나 **펫봇** — 초기화된 빈 상태입니다.
기존 전설이/펫 시스템은 모두 제거했고, 이 봇 위에 **독자적인 펫 시스템**을 새로 만들 수 있습니다.

- `main.py` : 봇 뼈대 (config.ini 또는 DISCORD_TOKEN 으로 실행)
- `cogs/` : 여기에 새 기능(cog)을 추가하세요. (main.py의 `cogs_to_load`에 등록)
- `utils/logs.py` : 4개 봇 공유 로그 채널 + 큐 (로그봇이 최종 기록)
- `utils/stats.py` : 공유 포인트/경험치 (stats.json)

## 실행
```
cp config.ini.example config.ini   # 토큰 입력
pip install -r requirements.txt
python main.py
```
