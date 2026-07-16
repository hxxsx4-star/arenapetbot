# main.py — 종합게임 아레나 펫봇 (초기화됨 / 독자 시스템용 뼈대)
import configparser

import discord
from discord.ext import commands

from utils.logs import init_log_queue

# --- 설정 로드 ---
config = configparser.ConfigParser()
config.read("config.ini", encoding="utf-8")
TOKEN = config.get("Settings", "token", fallback="").strip()
# config.ini 가 없으면 환경변수(DISCORD_TOKEN)에서 토큰을 읽습니다.
if not TOKEN:
    import os
    TOKEN = os.environ.get("DISCORD_TOKEN", "").strip()


class PetBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        init_log_queue()
        print("✅ 로그 큐 초기화 완료")

        # 새 펫 시스템 cog를 여기에 추가하세요. 예: "cogs.mypet"
        cogs_to_load: list[str] = []
        for ext in cogs_to_load:
            try:
                await self.load_extension(ext)
                print(f"▶️ {ext} 로드 완료")
            except Exception as e:
                print(f"🚨 {ext} 로드 실패 : {e}")

        synced = await self.tree.sync()
        print(f"🌀 총 {len(synced)}개의 커맨드를 동기화했습니다!")

    async def on_ready(self):
        print(f"✅ 펫봇 로그인 성공: {self.user} (ID: {self.user.id})")
        print("ℹ️ 초기화된 상태입니다. cogs/ 에 새 시스템을 추가하세요.")


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("🚨 토큰이 비어 있습니다. config.ini 파일을 확인하세요.")
    PetBot().run(TOKEN)
