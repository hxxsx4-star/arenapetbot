import asyncio
import random
from dataclasses import dataclass, field
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from . import config, db, species
from utils.logs import CATCH_LOG_CH, enqueue_embed, is_target_guild


@dataclass
class ActiveSpawn:
    species: dict
    message: Optional[discord.Message] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    resolved: bool = False


def _format_types(sp: dict) -> str:
    names = [species.TYPE_KO.get(sp["type1"], sp["type1"])]
    if sp.get("type2"):
        names.append(species.TYPE_KO.get(sp["type2"], sp["type2"]))
    return " / ".join(names)


def _build_spawn_embed(sp: dict) -> discord.Embed:
    embed = discord.Embed(
        title="🌿 야생 포켓몬이 나타났다!",
        description=(
            f"**{sp['name_ko']}** (No.{sp['id']:04d})\n"
            f"타입: {_format_types(sp)}\n\n"
            "먼저 아래 **포획하기** 버튼을 누르거나 `/포획`을 입력한 트레이너가 데려갑니다!"
        ),
        color=discord.Color.blurple(),
    )
    if sp.get("sprite_url"):
        embed.set_image(url=sp["sprite_url"])
    embed.set_footer(text=f"등급: {sp['rarity']}")
    return embed


def _roll_catch(sp: dict, ball: str) -> bool:
    info = config.BALLS.get(ball) or {}
    multiplier = info.get("multiplier", 1.0)
    if multiplier is None:      # 마스터볼: 무조건 성공
        return True
    # 하한은 배율을 곱하기 '전에' 적용한다. 곱한 뒤에 걸면 잡기 어려운 종일수록
    # max() 가 배율을 삼켜서 좋은 볼과 몬스터볼의 확률이 똑같아진다.
    base = max(0.05, sp["capture_rate"] / 255)
    chance = min(0.95, base * multiplier)
    return random.random() < chance


class CatchView(discord.ui.View):
    def __init__(self, cog: "SpawnCatchCog", channel_id: int, spawn: ActiveSpawn):
        super().__init__(timeout=config.SPAWN_TIMEOUT_SEC)
        self.cog = cog
        self.channel_id = channel_id
        self.spawn = spawn

    @discord.ui.button(label="포획하기", style=discord.ButtonStyle.green, emoji="🎯")
    async def catch_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        success, msg = await self.cog.attempt_catch(interaction.channel, interaction.user)
        await interaction.response.send_message(msg, ephemeral=True)
        if success:
            self.stop()

    async def on_timeout(self):
        await self.cog.expire_spawn(self.channel_id, self.spawn)


class SpawnCatchCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_spawns: dict[int, ActiveSpawn] = {}
        if config.SPAWN_CHANNEL_IDS:
            self.spawn_loop.change_interval(minutes=config.SPAWN_INTERVAL_MINUTES)
            self.spawn_loop.start()

    def cog_unload(self):
        self.spawn_loop.cancel()

    @tasks.loop(minutes=5)
    async def spawn_loop(self):
        """스폰 채널마다 일정 주기로 야생 포켓몬을 한 마리씩 등장시킵니다."""
        for channel_id in config.SPAWN_CHANNEL_IDS:
            if channel_id in self.active_spawns:
                continue  # 아직 안 잡힌 개체가 남아 있으면 건너뜀
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                continue
            if not is_target_guild(getattr(channel, "guild", None)):
                continue
            try:
                await self._spawn_wild(channel)
            except discord.HTTPException as e:
                print(f"🚨 스폰 실패 (ch={channel_id}): {e}")

    @spawn_loop.before_loop
    async def before_spawn_loop(self):
        await self.bot.wait_until_ready()

    async def _spawn_wild(self, channel: discord.abc.Messageable):
        sp = await species.get_random_wild()
        if not sp:
            return
        spawn = ActiveSpawn(species=sp)
        view = CatchView(self, channel.id, spawn)
        embed = _build_spawn_embed(sp)
        msg = await channel.send(embed=embed, view=view)
        spawn.message = msg
        self.active_spawns[channel.id] = spawn

    async def expire_spawn(self, channel_id: int, spawn: ActiveSpawn):
        current = self.active_spawns.get(channel_id)
        if current is not spawn or spawn.resolved:
            return
        spawn.resolved = True
        self.active_spawns.pop(channel_id, None)
        if spawn.message:
            try:
                embed = spawn.message.embeds[0]
                embed.color = discord.Color.dark_gray()
                embed.description = f"야생 **{spawn.species['name_ko']}**이(가) 도망갔습니다..."
                await spawn.message.edit(embed=embed, view=None)
            except discord.HTTPException:
                pass

    async def attempt_catch(self, channel, user, ball: str | None = None) -> tuple[bool, str]:
        """포획 시도를 처리합니다. (성공 여부, 유저에게 보여줄 메시지) 를 반환합니다.

        ball 을 지정하지 않으면 낮은 등급 볼부터 자동으로 사용합니다.
        """
        channel_id = channel.id
        spawn = self.active_spawns.get(channel_id)
        if not spawn or spawn.resolved:
            return False, "지금 이 채널에는 잡을 수 있는 야생 포켓몬이 없습니다."

        async with spawn.lock:
            if spawn.resolved:
                return False, "이미 다른 트레이너가 포획했습니다."

            # 첫 포획 시도라면 스타터 몬스터볼 지급
            await db.ensure_starter_balls(
                user.id, config.DEFAULT_BALL, config.STARTER_BALL_AMOUNT
            )

            if ball:
                if not await db.consume_item(user.id, ball, 1):
                    return False, f"{ball}이(가) 없습니다! `/볼상점` 에서 구매하거나 `/볼받기` 로 무료 지급받으세요."
            else:
                for candidate in config.AUTO_BALL_ORDER:
                    if await db.consume_item(user.id, candidate, 1):
                        ball = candidate
                        break
                else:
                    return False, (
                        "볼이 없습니다! `/볼받기` 로 하루 한 번 무료로 받거나 "
                        "`/볼상점` 에서 포인트로 구매하세요."
                    )

            if not _roll_catch(spawn.species, ball):
                remaining = await db.get_item_amount(user.id, ball)
                return False, f"🌀 {ball}을(를) 던졌지만 도망쳤습니다! (남은 {ball}: {remaining}개)"

            spawn.resolved = True
            self.active_spawns.pop(channel_id, None)

            existing = await db.get_user_pokemon_count(user.id)
            await db.add_user_pokemon(user.id, spawn.species["id"], is_partner=(existing == 0))

            sp = spawn.species
            if spawn.message:
                try:
                    embed = spawn.message.embeds[0]
                    embed.color = discord.Color.green()
                    embed.description = (
                        f"🎉 **{user.display_name}**님이 야생 **{sp['name_ko']}**을(를) 포획했습니다!"
                    )
                    await spawn.message.edit(embed=embed, view=None)
                except discord.HTTPException:
                    pass

            guild = getattr(channel, "guild", None)
            if guild is not None:
                log_embed = discord.Embed(
                    title="포켓몬 포획",
                    description=f"{sp['name_ko']} (No.{sp['id']:04d} / {sp['rarity']}) · {ball} 사용",
                    color=discord.Color.green(),
                )
                if sp.get("sprite_url"):
                    log_embed.set_thumbnail(url=sp["sprite_url"])
                ball_sprite = (config.BALLS.get(ball) or {}).get("sprite")
                if ball_sprite:
                    log_embed.set_author(name=f"{ball} 사용", icon_url=ball_sprite)
                icon = user.display_avatar.url if getattr(user, "display_avatar", None) else None
                log_embed.set_footer(text=f"트레이너: {user.display_name} ({user.id})", icon_url=icon)
                enqueue_embed(CATCH_LOG_CH, log_embed.to_dict(), guild=guild)

            remaining = await db.get_item_amount(user.id, ball)
            return True, f"✅ {ball}로 야생 **{sp['name_ko']}**을(를) 포획했습니다! (남은 {ball}: {remaining}개)"

    @app_commands.command(name="포획", description="현재 채널에 나타난 야생 포켓몬을 포획합니다.")
    @app_commands.describe(볼="사용할 볼 (지정하지 않으면 낮은 등급부터 자동 사용)")
    @app_commands.choices(볼=[
        app_commands.Choice(name=b, value=b) for b in config.BALL_ORDER
    ])
    async def catch_command(self, interaction: discord.Interaction,
                            볼: app_commands.Choice[str] | None = None):
        if interaction.guild is None or not is_target_guild(interaction.guild):
            await interaction.response.send_message(
                "이 명령어는 지정된 서버에서만 사용할 수 있습니다.", ephemeral=True
            )
            return
        success, msg = await self.attempt_catch(
            interaction.channel, interaction.user, ball=볼.value if 볼 else None
        )
        await interaction.response.send_message(msg, ephemeral=True)
