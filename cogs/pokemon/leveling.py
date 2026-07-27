"""포켓몬 레벨 · 진화.

주인이 채팅하면 파티(최대 6마리) 전원이 경험치를 얻고, 파트너는 더 받는다.
레벨이 진화 레벨에 도달하면 자동으로 진화한다.
"""
import random
import time

import discord
from discord import app_commands
from discord.ext import commands

from . import config, db
from utils.logs import CATCH_LOG_CH, enqueue_embed, is_target_guild


def xp_to_next(level: int) -> int:
    """다음 레벨까지 필요한 경험치."""
    return int(12 * (level ** 1.45)) + 25


def total_xp_for(level: int) -> int:
    """1레벨부터 해당 레벨 도달까지 필요한 누적 경험치."""
    return sum(xp_to_next(l) for l in range(1, level))


def apply_gain(level: int, exp: int, gain: int) -> tuple[int, int, int]:
    """경험치를 더하고 레벨업을 처리한다. (새 레벨, 남은 exp, 오른 레벨 수)"""
    exp += gain
    gained = 0
    while level < config.MAX_LEVEL:
        need = xp_to_next(level)
        if exp < need:
            break
        exp -= need
        level += 1
        gained += 1
    if level >= config.MAX_LEVEL:
        exp = 0
    return level, exp, gained


def evolve_level_of(row: dict) -> int | None:
    """이 포켓몬이 몇 레벨에 진화하는지. 진화처가 없으면 None."""
    if not row.get("evolves_to"):
        return None
    return row.get("evolve_level") or config.DEFAULT_EVOLVE_LEVEL


class LevelingCog(commands.Cog):
    """채팅으로 파티 포켓몬을 키우고, 조건이 되면 진화시킨다."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._cooldown: dict[int, float] = {}

    # ----- 경험치 획득 -----
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        if not is_target_guild(message.guild):
            return

        uid = message.author.id
        now = time.time()
        if now - self._cooldown.get(uid, 0) < config.CHAT_XP_COOLDOWN_SEC:
            return
        party = await db.get_party(uid)
        if not party:
            return
        self._cooldown[uid] = now

        base = random.randint(config.CHAT_XP_MIN, config.CHAT_XP_MAX)
        for mon in party:
            gain = int(base * config.PARTNER_XP_MULTIPLIER) if mon["is_partner"] else base
            await self._grant(message.channel, message.author, mon, gain)

    async def _grant(self, channel, user, mon: dict, gain: int):
        """경험치 지급 → 레벨업 → 진화까지 처리하고, 변화가 있으면 알린다."""
        level, exp, gained = apply_gain(mon["level"], mon["exp"], gain)
        await db.apply_level(mon["uid"], level, exp)
        if not gained:
            return

        name = mon["nickname"] or mon["name_ko"]
        evolved_to = None
        need = evolve_level_of(mon)
        if need and level >= need:
            target = await db.get_species(mon["evolves_to"])
            if target:
                await db.evolve(mon["uid"], target["id"])
                evolved_to = target

        try:
            if evolved_to:
                embed = discord.Embed(
                    title="✨ 축하합니다! 포켓몬이 진화했습니다!",
                    description=(f"{user.mention} 님의 **{name}**이(가) "
                                 f"**{evolved_to['name_ko']}**(으)로 진화했습니다!\n"
                                 f"`Lv.{level}`"),
                    color=discord.Color.gold())
                if evolved_to.get("sprite_url"):
                    embed.set_thumbnail(url=evolved_to["sprite_url"])
                await channel.send(embed=embed)
                self._log_evolution(channel, user, mon, evolved_to, level)
            elif level % 5 == 0 or (mon["is_partner"] and gained):
                # 알림이 도배되지 않도록 파트너이거나 5의 배수 레벨일 때만
                embed = discord.Embed(
                    description=(f"🎉 {user.mention} 님의 **{name}**이(가) "
                                 f"**Lv.{level}** 이 되었습니다!"),
                    color=discord.Color.green())
                if mon.get("sprite_url"):
                    embed.set_thumbnail(url=mon["sprite_url"])
                await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    def _log_evolution(self, channel, user, mon, target, level):
        guild = getattr(channel, "guild", None)
        if guild is None:
            return
        e = discord.Embed(
            title="포켓몬 진화",
            description=f"{mon['name_ko']} → **{target['name_ko']}** (Lv.{level})",
            color=discord.Color.gold())
        if target.get("sprite_url"):
            e.set_thumbnail(url=target["sprite_url"])
        icon = user.display_avatar.url if getattr(user, "display_avatar", None) else None
        e.set_footer(text=f"트레이너: {user.display_name} ({user.id})", icon_url=icon)
        enqueue_embed(CATCH_LOG_CH, e.to_dict(), guild=guild)

    # ----- 명령어 -----
    async def _guard(self, interaction) -> bool:
        if interaction.guild is None or not is_target_guild(interaction.guild):
            await interaction.response.send_message(
                "이 명령어는 지정된 서버에서만 사용할 수 있습니다.", ephemeral=True)
            return False
        return True

    @app_commands.command(name="파티", description="데리고 다니는 포켓몬(최대 6마리)을 확인합니다.")
    async def party_cmd(self, interaction: discord.Interaction):
        if not await self._guard(interaction):
            return
        party = await db.get_party(interaction.user.id)
        embed = discord.Embed(
            title=f"🎒 {interaction.user.display_name}의 파티",
            description=(f"파티에 있는 포켓몬만 경험치를 얻습니다. "
                         f"(⭐파트너는 {config.PARTNER_XP_MULTIPLIER:g}배)\n"
                         f"`/파티등록` `/파티해제` `/파트너` 로 바꿀 수 있습니다."),
            color=discord.Color.gold())
        if not party:
            embed.add_field(name="비어 있음",
                            value="`/포켓몬함` 에서 번호를 확인해 `/파티등록` 하세요.", inline=False)
        for mon in party:
            need = xp_to_next(mon["level"])
            ev = evolve_level_of(mon)
            tail = f" · 진화 Lv.{ev}" if ev and mon["level"] < ev else ""
            embed.add_field(
                name=f"{'⭐ ' if mon['is_partner'] else ''}{mon['nickname'] or mon['name_ko']}"
                     f"  (#{mon['uid']})",
                value=f"Lv.**{mon['level']}** · {mon['exp']}/{need} EXP · {mon['rarity']}{tail}",
                inline=False)
        embed.set_footer(text=f"{len(party)}/{config.PARTY_SIZE}마리")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="파티등록", description="박스의 포켓몬을 파티에 넣습니다.")
    @app_commands.describe(번호="포켓몬함에 표시된 번호(#)")
    async def party_add(self, interaction: discord.Interaction, 번호: int):
        if not await self._guard(interaction):
            return
        mon = await db.get_pokemon(번호, interaction.user.id)
        if not mon:
            return await interaction.response.send_message(
                "❌ 본인의 포켓몬 중에 그 번호가 없습니다. `/포켓몬함` 에서 확인하세요.", ephemeral=True)
        if mon["in_party"]:
            return await interaction.response.send_message("이미 파티에 있습니다.", ephemeral=True)
        party = await db.get_party(interaction.user.id)
        if len(party) >= config.PARTY_SIZE:
            return await interaction.response.send_message(
                f"❌ 파티는 최대 {config.PARTY_SIZE}마리입니다. `/파티해제` 로 한 마리를 빼주세요.",
                ephemeral=True)
        await db.set_party(번호, interaction.user.id, True)
        await interaction.response.send_message(
            f"✅ **{mon['nickname'] or mon['name_ko']}**을(를) 파티에 넣었습니다. "
            f"({len(party) + 1}/{config.PARTY_SIZE})", ephemeral=True)

    @app_commands.command(name="파티해제", description="파티의 포켓몬을 박스로 보냅니다.")
    @app_commands.describe(번호="포켓몬함에 표시된 번호(#)")
    async def party_remove(self, interaction: discord.Interaction, 번호: int):
        if not await self._guard(interaction):
            return
        mon = await db.get_pokemon(번호, interaction.user.id)
        if not mon:
            return await interaction.response.send_message(
                "❌ 본인의 포켓몬 중에 그 번호가 없습니다.", ephemeral=True)
        if not mon["in_party"]:
            return await interaction.response.send_message("이미 박스에 있습니다.", ephemeral=True)
        await db.set_party(번호, interaction.user.id, False)
        await interaction.response.send_message(
            f"📦 **{mon['nickname'] or mon['name_ko']}**을(를) 박스로 보냈습니다.", ephemeral=True)

    @app_commands.command(name="파트너", description="파트너 포켓몬을 지정합니다. (경험치 추가 획득)")
    @app_commands.describe(번호="포켓몬함에 표시된 번호(#)")
    async def partner_cmd(self, interaction: discord.Interaction, 번호: int):
        if not await self._guard(interaction):
            return
        mon = await db.get_pokemon(번호, interaction.user.id)
        if not mon:
            return await interaction.response.send_message(
                "❌ 본인의 포켓몬 중에 그 번호가 없습니다.", ephemeral=True)
        party = await db.get_party(interaction.user.id)
        if not mon["in_party"] and len(party) >= config.PARTY_SIZE:
            return await interaction.response.send_message(
                f"❌ 파티가 가득 찼습니다({config.PARTY_SIZE}마리). 먼저 `/파티해제` 를 해주세요.",
                ephemeral=True)
        await db.set_partner(번호, interaction.user.id)
        await interaction.response.send_message(
            f"⭐ **{mon['nickname'] or mon['name_ko']}**을(를) 파트너로 지정했습니다! "
            f"(경험치 {config.PARTNER_XP_MULTIPLIER:g}배)", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(LevelingCog(bot))
