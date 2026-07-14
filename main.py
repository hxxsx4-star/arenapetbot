# main.py — 종합게임 아레나 펫봇
import asyncio
import configparser

import discord
from discord.ext import commands

from utils.database import init_db
from utils.logs import init_log_queue

# --- 설정 로드 ---
config = configparser.ConfigParser()
config.read("config.ini", encoding="utf-8")
TOKEN = config.get("Settings", "token", fallback="").strip()
# config.ini 가 없으면 환경변수(DISCORD_TOKEN)에서 토큰을 읽습니다. (도커/CI 배포용)
if not TOKEN:
    import os
    TOKEN = os.environ.get("DISCORD_TOKEN", "").strip()


class PetBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await init_db()
        print("✅ 데이터베이스 초기화 완료")
        init_log_queue()
        print("✅ 로그 큐 초기화 완료")

        extensions = [
            "cogs.help",
            "cogs.petsystem.core",          # 펫 코어 (알까기, 상태창)
            "cogs.petsystem.inventory",     # 보관함/도감/상점(알환전/분해)
            "cogs.petsystem.admin",         # 관리자 (알/아이템 지급·회수 로그)
            "cogs.petsystem.battle",        # 배틀
            "cogs.petsystem.achievement",   # 업적
            "cogs.petsystem.cog_synthetis", # 합성
            "cogs.petsystem.cog_box",       # 박스
        ]
        for ext in extensions:
            try:
                await self.load_extension(ext)
                print(f"▶️ {ext} 로드 완료")
            except Exception as e:
                print(f"🚨 {ext} 로드 실패 : {e}")

        synced = await self.tree.sync()
        print(f"🌀 총 {len(synced)}개의 커맨드를 동기화했습니다!")

    async def on_ready(self):
        print(f"✅ 펫봇 로그인 성공: {self.user} (ID: {self.user.id})")


async def main():
    if not TOKEN:
        raise SystemExit("🚨 토큰이 비어 있습니다. config.ini 파일을 확인하세요.")
    bot = PetBot()
    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
