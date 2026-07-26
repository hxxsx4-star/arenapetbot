from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from . import config, db
from utils import stats
from utils.logs import SHOP_LOG_CH, enqueue_embed, is_target_guild

KST = timezone(timedelta(hours=9))
DAILY_KIND = "balls"


def _today_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def _label(name: str) -> str:
    return f"{config.BALLS[name]['emoji']} {name}"


class BallShopCog(commands.Cog):
    """볼 상점 — 공유 포인트(stats.json)로 볼을 사고, 하루 한 번 무료로 받습니다."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None or not is_target_guild(interaction.guild):
            await interaction.response.send_message(
                "이 명령어는 지정된 서버에서만 사용할 수 있습니다.", ephemeral=True
            )
            return False
        return True

    @app_commands.command(name="볼상점", description="포인트로 몬스터볼을 구매합니다.")
    @app_commands.describe(볼="구매할 볼", 개수="구매 개수 (기본 1)")
    @app_commands.choices(볼=[
        app_commands.Choice(name=b, value=b)
        for b in config.BALL_ORDER if config.BALLS[b]["price"] is not None
    ])
    async def shop_command(self, interaction: discord.Interaction,
                           볼: app_commands.Choice[str] | None = None,
                           개수: int = 1):
        if not await self._guard(interaction):
            return

        points = await stats.get_points(interaction.user.id)

        # 볼을 고르지 않으면 상점 목록만 보여준다.
        # 한 메시지에 임베드를 여러 개 넣을 수 있어(최대 10) 볼마다 사진을 붙인다.
        if 볼 is None:
            owned = await db.list_items(interaction.user.id)
            header = discord.Embed(
                title="🛒 볼 상점",
                description=f"보유 포인트: **{stats.format_num(points)}P**\n"
                            "`/볼상점 볼:<종류> 개수:<수량>` 으로 구매하세요.",
                color=discord.Color.blurple(),
            )
            header.set_footer(text="무료 지급은 /볼받기 · 소지품 확인은 /가방")

            embeds = [header]
            for name in config.BALL_ORDER:
                info = config.BALLS[name]
                if info["price"] is None:
                    continue
                e = discord.Embed(
                    title=f"{_label(name)} — {stats.format_num(info['price'])}P",
                    description=f"{info['desc']} · 보유 **{owned.get(name, 0)}개**",
                    color=discord.Color.blurple(),
                )
                e.set_thumbnail(url=info["sprite"])
                embeds.append(e)
            await interaction.response.send_message(embeds=embeds, ephemeral=True)
            return

        name = 볼.value
        if 개수 < 1 or 개수 > config.MAX_BUY_AMOUNT:
            await interaction.response.send_message(
                f"개수는 1 ~ {config.MAX_BUY_AMOUNT} 사이로 입력하세요.", ephemeral=True
            )
            return

        cost = config.BALLS[name]["price"] * 개수
        if points < cost:
            await interaction.response.send_message(
                f"포인트가 부족합니다. (필요 {stats.format_num(cost)}P / 보유 "
                f"{stats.format_num(points)}P)", ephemeral=True
            )
            return

        # 포인트를 먼저 차감하고, 성공했을 때만 볼을 지급한다.
        if not await stats.spend_points(interaction.user.id, cost):
            await interaction.response.send_message(
                "포인트 차감에 실패했습니다. 잠시 후 다시 시도해주세요.", ephemeral=True
            )
            return
        await db.add_item(interaction.user.id, name, 개수)

        owned = await db.get_item_amount(interaction.user.id, name)
        left = await stats.get_points(interaction.user.id)
        bought = discord.Embed(
            title=f"✅ {name} {개수}개 구매 완료",
            description=f"-{stats.format_num(cost)}P · 남은 포인트 **{stats.format_num(left)}P**\n"
                        f"보유 {name}: **{owned}개**",
            color=discord.Color.green(),
        )
        bought.set_thumbnail(url=config.BALLS[name]["sprite"])
        await interaction.response.send_message(embed=bought, ephemeral=True)

        log_embed = discord.Embed(
            title="볼 상점 구매",
            description=f"{name} × {개수} (-{stats.format_num(cost)}P)",
            color=discord.Color.blurple(),
        )
        icon = (interaction.user.display_avatar.url
                if getattr(interaction.user, "display_avatar", None) else None)
        log_embed.set_footer(
            text=f"유저: {interaction.user.display_name} ({interaction.user.id})", icon_url=icon
        )
        enqueue_embed(SHOP_LOG_CH, log_embed.to_dict(), guild=interaction.guild)

    @app_commands.command(name="볼받기", description="하루 한 번 무료로 몬스터볼을 받습니다.")
    async def daily_command(self, interaction: discord.Interaction):
        if not await self._guard(interaction):
            return

        today = _today_kst()
        if not await db.try_claim_daily(interaction.user.id, DAILY_KIND, today):
            await interaction.response.send_message(
                "오늘은 이미 받았습니다. 내일 자정(KST) 이후에 다시 받을 수 있어요!", ephemeral=True
            )
            return

        name = config.DEFAULT_BALL
        await db.add_item(interaction.user.id, name, config.DAILY_BALL_AMOUNT)
        owned = await db.get_item_amount(interaction.user.id, name)
        embed = discord.Embed(
            title=f"🎁 {name} {config.DAILY_BALL_AMOUNT}개 지급!",
            description=f"보유 {name}: **{owned}개**\n내일 자정(KST) 이후 다시 받을 수 있어요.",
            color=discord.Color.green(),
        )
        embed.set_thumbnail(url=config.BALLS[name]["sprite"])
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="가방", description="보유한 볼과 아이템을 확인합니다.")
    async def bag_command(self, interaction: discord.Interaction):
        if not await self._guard(interaction):
            return

        items = await db.list_items(interaction.user.id)
        points = await stats.get_points(interaction.user.id)

        embed = discord.Embed(
            title=f"🎒 {interaction.user.display_name}의 가방",
            description=f"보유 포인트: **{stats.format_num(points)}P**",
            color=discord.Color.gold(),
        )
        balls = [f"{_label(n)} × {items[n]}" for n in config.BALL_ORDER if items.get(n)]
        embed.add_field(name="몬스터볼", value="\n".join(balls) or "없음 — `/볼받기` 로 무료 지급!",
                        inline=False)
        # 가진 것 중 가장 좋은 볼을 썸네일로 (없으면 기본 볼)
        best = next((n for n in reversed(config.BALL_ORDER) if items.get(n)), config.DEFAULT_BALL)
        embed.set_thumbnail(url=config.BALLS[best]["sprite"])

        others = {k: v for k, v in items.items() if k not in config.BALLS}
        if others:
            embed.add_field(name="기타 아이템",
                            value="\n".join(f"{k} × {v}" for k, v in others.items()), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(BallShopCog(bot))
