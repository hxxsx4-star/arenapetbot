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
    legendary: bool = False     # 특별 조우 여부 (표시/타임아웃이 달라짐)


def _kst_now():
    from datetime import datetime, timedelta, timezone
    return datetime.now(timezone(timedelta(hours=9)))


def _plan_today(day_start_epoch: float, now_epoch: float | None = None) -> list[float]:
    """오늘의 특별 조우 시각을 정한다. (지정 시간대 안에서 무작위, 서로 30분 이상 간격)

    봇이 한낮에 처음 켜지면 시간대 앞부분은 이미 지나 있다. 그대로 뽑으면 전부
    '지난 시각'이 되어 그날은 조우가 한 번도 안 뜬다. 남은 시간 안에서만 고른다.
    """
    start = day_start_epoch + config.LEGENDARY_WINDOW_START_HOUR * 3600
    end = day_start_epoch + config.LEGENDARY_WINDOW_END_HOUR * 3600
    if now_epoch is not None:
        start = max(start, now_epoch + 300)     # 최소 5분 뒤부터
    if start >= end:
        return []                                # 오늘은 시간대가 끝남
    # 남은 시간이 짧으면 간격 조건을 줄여서라도 잡는다.
    min_gap = min(1800, max(0, (end - start) / max(1, config.LEGENDARY_SPAWNS_PER_DAY)))
    times = []
    for _ in range(config.LEGENDARY_SPAWNS_PER_DAY):
        for _try in range(80):
            t = random.uniform(start, end)
            if all(abs(t - o) >= min_gap for o in times):
                times.append(t)
                break
    return sorted(times)


def _format_types(sp: dict) -> str:
    names = [species.TYPE_KO.get(sp["type1"], sp["type1"])]
    if sp.get("type2"):
        names.append(species.TYPE_KO.get(sp["type2"], sp["type2"]))
    return " / ".join(names)


def _build_spawn_embed(sp: dict, legendary: bool = False) -> discord.Embed:
    if legendary:
        embed = discord.Embed(
            title="🌟 전설의 포켓몬이 모습을 드러냈다!",
            description=(
                f"**{sp['name_ko']}** (No.{sp['id']:04d})\n"
                f"타입: {_format_types(sp)}\n\n"
                "좀처럼 만날 수 없는 포켓몬입니다. 포획률이 매우 낮으니 "
                "**하이퍼볼**이나 **마스터볼**을 준비하세요!\n"
                f"기회는 {config.LEGENDARY_TIMEOUT_SEC // 60}분입니다."
            ),
            color=discord.Color.gold(),
        )
        embed.set_footer(text=f"⭐ 특별 조우 · 등급: {sp['rarity']}")
    else:
        embed = discord.Embed(
            title="🌿 야생 포켓몬이 나타났다!",
            description=(
                f"**{sp['name_ko']}** (No.{sp['id']:04d})\n"
                f"타입: {_format_types(sp)}\n\n"
                "먼저 아래 **포획하기** 버튼을 누르거나 `/포획`을 입력한 트레이너가 데려갑니다!"
            ),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"등급: {sp['rarity']}")
    if sp.get("sprite_url"):
        embed.set_image(url=sp["sprite_url"])
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


class BallChoiceView(discord.ui.View):
    """어떤 볼을 던질지 고르는 개인용(에페메랄) 화면."""

    def __init__(self, cog: "SpawnCatchCog", parent: "CatchView", owned: dict[str, int]):
        super().__init__(timeout=60)
        self.cog = cog
        self.parent = parent
        options = []
        for name in config.BALL_ORDER:
            info = config.BALLS[name]
            n = owned.get(name, 0)
            options.append(discord.SelectOption(
                label=f"{name} — {n}개",
                value=name,
                emoji=info["emoji"],
                description=info["desc"] + ("" if n else " (보유 없음)"),
            ))
        self.select = discord.ui.Select(placeholder="던질 볼을 고르세요", options=options)
        self.select.callback = self.on_select
        self.add_item(self.select)

    async def on_select(self, interaction: discord.Interaction):
        ball = self.select.values[0]
        have = await db.get_item_amount(interaction.user.id, ball)
        if have <= 0:
            return await interaction.response.edit_message(
                content=f"❌ **{ball}**이(가) 없습니다!\n"
                        "`/볼받기` 로 하루 한 번 무료로 받거나 `/볼상점` 에서 구매하세요.",
                view=None)
        success, msg = await self.cog.attempt_catch(
            interaction.channel, interaction.user, ball=ball)
        await interaction.response.edit_message(content=msg, view=None)
        if success:
            self.parent.stop()


class CatchView(discord.ui.View):
    def __init__(self, cog: "SpawnCatchCog", channel_id: int, spawn: ActiveSpawn):
        super().__init__(timeout=config.SPAWN_TIMEOUT_SEC)
        self.cog = cog
        self.channel_id = channel_id
        self.spawn = spawn

    @discord.ui.button(label="포획하기", style=discord.ButtonStyle.green, emoji="🎯")
    async def catch_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.spawn.resolved:
            return await interaction.response.send_message(
                "이미 다른 트레이너가 포획했습니다.", ephemeral=True)
        # 첫 참여자에게만 스타터 볼을 지급한다.
        await db.ensure_starter_balls(
            interaction.user.id, config.DEFAULT_BALL, config.STARTER_BALL_AMOUNT)
        owned = await db.list_items(interaction.user.id)
        if not any(owned.get(b) for b in config.BALL_ORDER):
            return await interaction.response.send_message(
                "❌ 던질 볼이 하나도 없습니다!\n"
                "`/볼받기` 로 하루 한 번 무료로 받거나 `/볼상점` 에서 구매하세요.", ephemeral=True)
        await interaction.response.send_message(
            f"어떤 볼을 던질까요? (야생 **{self.spawn.species['name_ko']}**)",
            view=BallChoiceView(self.cog, self, owned), ephemeral=True)

    async def on_timeout(self):
        await self.cog.expire_spawn(self.channel_id, self.spawn)


class SpawnCatchCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_spawns: dict[int, ActiveSpawn] = {}
        if config.SPAWN_CHANNEL_IDS:
            self.spawn_loop.change_interval(minutes=config.SPAWN_INTERVAL_MINUTES)
            self.spawn_loop.start()
            self.legendary_loop.start()
        # 웹 요청 큐는 스폰 채널 설정과 무관하게 항상 처리한다.
        self.request_loop.start()

    def cog_unload(self):
        self.spawn_loop.cancel()
        self.legendary_loop.cancel()
        self.request_loop.cancel()

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

    async def _spawn_wild(self, channel: discord.abc.Messageable, legendary: bool = False):
        sp = await (species.get_random_legendary() if legendary else species.get_random_wild())
        if not sp:
            return
        spawn = ActiveSpawn(species=sp, legendary=legendary)
        view = CatchView(self, channel.id, spawn)
        if legendary:
            view.timeout = config.LEGENDARY_TIMEOUT_SEC
        embed = _build_spawn_embed(sp, legendary)
        content = None
        if legendary and config.LEGENDARY_PING_ROLE:
            content = f"<@&{config.LEGENDARY_PING_ROLE}>"
        msg = await channel.send(content=content, embed=embed, view=view)
        spawn.message = msg
        self.active_spawns[channel.id] = spawn

    # ----- 전설·환상 특별 조우 -----
    @tasks.loop(minutes=1)
    async def legendary_loop(self):
        """정해진 시각이 되면 전설/환상 포켓몬을 등장시킨다."""
        now = _kst_now()
        day = now.strftime("%Y-%m-%d")
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

        rows = await db.get_day_schedule(day)
        if not rows:
            from datetime import datetime
            times = _plan_today(day_start, now.timestamp())
            if not times:
                return          # 오늘 시간대가 이미 끝남 — 내일 다시 계획
            await db.set_day_schedule(day, times)
            rows = await db.get_day_schedule(day)
            when = ", ".join(
                datetime.fromtimestamp(t, now.tzinfo).strftime("%H:%M") for t in times)
            print(f"🌟 [전설 조우] 오늘({day}) 예정 시각: {when} (KST)")
            await db.purge_old_legendary(day)      # 지난 날짜 기록 정리

        ts = now.timestamp()
        for row in rows:
            if row["done"] or ts < row["at"]:
                continue
            # 시각이 지났는데 너무 오래 지났으면(봇이 꺼져 있었음) 건너뛴다
            if ts - row["at"] > 1800:
                await db.mark_legendary_done(day, row["idx"])
                continue
            for channel_id in config.SPAWN_CHANNEL_IDS:
                channel = self.bot.get_channel(channel_id)
                if channel is None or not is_target_guild(getattr(channel, "guild", None)):
                    continue
                # 일반 스폰이 떠 있으면 정리하고 특별 조우를 올린다.
                cur = self.active_spawns.get(channel_id)
                if cur is not None:
                    await self.expire_spawn(channel_id, cur)
                try:
                    await self._spawn_wild(channel, legendary=True)
                except discord.HTTPException as e:
                    print(f"🚨 전설 조우 실패 (ch={channel_id}): {e}")
            await db.mark_legendary_done(day, row["idx"])

    @legendary_loop.before_loop
    async def before_legendary_loop(self):
        await self.bot.wait_until_ready()
        await db.init_legendary_table()

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

            # 트레이너가 된 첫 순간에만 스타터 몬스터볼 지급 (한 번뿐)
            await db.ensure_starter_balls(
                user.id, config.DEFAULT_BALL, config.STARTER_BALL_AMOUNT
            )

            if not ball:
                return False, "던질 볼을 선택해주세요. (`/포획 볼:<종류>`)"
            if not await db.consume_item(user.id, ball, 1):
                return False, (f"❌ **{ball}**이(가) 없습니다!\n"
                               "`/볼받기` 로 하루 한 번 무료로 받거나 `/볼상점` 에서 구매하세요.")

            if not _roll_catch(spawn.species, ball):
                remaining = await db.get_item_amount(user.id, ball)
                return False, f"🌀 {ball}을(를) 던졌지만 도망쳤습니다! (남은 {ball}: {remaining}개)"

            spawn.resolved = True
            self.active_spawns.pop(channel_id, None)

            existing = await db.get_user_pokemon_count(user.id)
            new_uid = await db.add_user_pokemon(
                user.id, spawn.species["id"], is_partner=(existing == 0),
                party_size=config.PARTY_SIZE)
            # 잡자마자 약간의 경험치를 준다.
            await db.add_exp(new_uid, config.CATCH_XP)

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

    # ----- 관리자 소환 -----
    async def summon(self, species_name: str | None = None,
                     legendary: bool = True) -> tuple[bool, str]:
        """전설/환상(또는 지정 종)을 즉시 등장시킨다. (명령어·웹 공용)"""
        sp = None
        if species_name:
            found = await db.find_species_by_name(species_name)
            if not found:
                return False, f"'{species_name}' 이름의 포켓몬을 찾지 못했습니다."
            sp = found[0]
        channels = []
        for cid in config.SPAWN_CHANNEL_IDS:
            ch = self.bot.get_channel(cid)
            if ch is not None and is_target_guild(getattr(ch, "guild", None)):
                channels.append(ch)
        if not channels:
            return False, "스폰 채널을 찾을 수 없습니다."

        names = []
        for ch in channels:
            cur = self.active_spawns.get(ch.id)
            if cur is not None:
                await self.expire_spawn(ch.id, cur)
            try:
                if sp:
                    spawn = ActiveSpawn(species=sp, legendary=legendary)
                    view = CatchView(self, ch.id, spawn)
                    if legendary:
                        view.timeout = config.LEGENDARY_TIMEOUT_SEC
                    msg = await ch.send(embed=_build_spawn_embed(sp, legendary), view=view)
                    spawn.message = msg
                    self.active_spawns[ch.id] = spawn
                    names.append(sp["name_ko"])
                else:
                    await self._spawn_wild(ch, legendary=legendary)
                    cur = self.active_spawns.get(ch.id)
                    if cur:
                        names.append(cur.species["name_ko"])
            except discord.HTTPException as e:
                return False, f"소환 실패: {e}"
        return True, f"✨ {', '.join(names)} 등장! ({len(channels)}개 채널)"

    @app_commands.command(name="전설소환",
                          description="[관리자] 전설/환상 포켓몬을 즉시 등장시킵니다.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(이름="특정 포켓몬 이름 (비우면 전설·환상 중 무작위)")
    async def summon_cmd(self, interaction: discord.Interaction, 이름: str | None = None):
        if interaction.guild is None or not is_target_guild(interaction.guild):
            return await interaction.response.send_message(
                "이 명령어는 지정된 서버에서만 사용할 수 있습니다.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        ok, msg = await self.summon(이름, legendary=True)
        await interaction.followup.send(("✅ " if ok else "❌ ") + msg, ephemeral=True)

    # ----- 웹에서 들어온 요청 처리 -----
    @tasks.loop(seconds=10)
    async def request_loop(self):
        try:
            reqs = await db.fetch_pending_requests()
        except Exception as e:
            print(f"🚨 [요청 큐] 조회 실패: {e}")
            return
        for r in reqs:
            try:
                if r["kind"] == "summon":
                    ok, msg = await self.summon(r["payload"] or None, legendary=True)
                    await db.complete_request(r["id"], ("OK: " if ok else "FAIL: ") + msg)
                    print(f"🌟 [웹 소환] {r['actor']} → {msg}")
                else:
                    await db.complete_request(r["id"], "알 수 없는 요청")
            except Exception as e:
                await db.complete_request(r["id"], f"오류: {e}")
                print(f"🚨 [요청 큐] 처리 실패 id={r['id']}: {e}")

    @request_loop.before_loop
    async def before_request_loop(self):
        await self.bot.wait_until_ready()
        await db.init_request_queue()

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
