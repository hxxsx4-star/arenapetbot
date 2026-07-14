# arenapetbot

종합게임 아레나 **펫봇** (전설이 펫 시스템).

- `cogs/petsystem/*` : 알까기/보관함/도감/배틀/합성/관리자 등 펫 시스템 전체
- 로그는 직접 올리지 않고 공유 큐(`utils/logs.py`)에 적재 → **로그봇**이 채널에 기록
  - 알까기 → 펫 알까기 로그
  - 알 지급/회수 → 펫 알지급/회수 로그
  - 아이템 지급/회수 → 아이템 지급/회수 로그
- `assets/` : 펫 상태 이미지 생성용 배경/폰트

## 실행
```
cp config.ini.example config.ini   # 토큰 입력
pip install -r requirements.txt
python main.py
```
