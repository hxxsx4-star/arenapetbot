import discord
from discord.ext import commands, tasks
from discord import app_commands
import random
import time
import aiosqlite

from utils.data import PET_POOLS, EXP_TABLE
from utils.database import get_or_migrate_data, get_active_buffs, save_legend_data, update_max_star
# 변경된 모듈 임포트
from .ui_action import LegendActionView, get_pet_stats
from utils.image_generator import generate_status_image
from utils.logs import HATCH_LOG_CH, send_log_embed
from utils.stats import get_points, add_points

class HatchView(discord.ui.View):
    def __init__(self, bot, user_id, rarity, pet_name, is_first_time):
        super().__init__(timeout=60)
        self.bot = bot
        self.user_id = user_id
        self.rarity = rarity
        self.pet_name = pet_name
        self.is_first_time = is_first_time
        self.chosen = False
        self.message = None

        options = [discord.SelectOption(label=p, value=p) for p in PET_POOLS[rarity][:25]]
        self.select = discord.ui.Select(placeholder=f"원하는 {rarity}급 전설이를 선택하세요!", options=options)
        self.select.callback = self.on_select
        self.add_item(self.select)

    async def on_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ 본인의 알만 선택할 수 있습니다.", ephemeral=True)

        self.chosen = True
        selected_type = self.select.values[0]

        wrapper = await get_or_migrate_data(self.user_id)
        if 'pets' not in wrapper: wrapper['pets'] = []

        new_pet_data = {
            'name': self.pet_name, 'type': selected_type, 'rarity': self.rarity, 'level': 0, 'exp': 0, 'fullness': 100,
            'intimacy': 50, 'fatigue': 0, 'cleanliness': 100, 'walk_count': 0, 'total_walk_count': 0,
            'last_fatigue_calc': time.time()
        }

        wrapper['pets'].append(new_pet_data)
        wrapper['active_idx'] = len(wrapper['pets']) - 1
        await save_legend_data(self.user_id, wrapper)

        embed = discord.Embed(title="🥚 알 부화 성공!", description=f"[{self.rarity}급] {selected_type} 알을 얻었습니다!\n이름: `{self.pet_name}`\n`/상태창`으로 돌봐주세요.", color=discord.Color.green())
        await interaction.response.edit_message(embed=embed, view=None)

        cost = 0 if self.is_first_time else 1000
        await send_log_embed(interaction.client, HATCH_LOG_CH, "🥚 알까기 로그", f"{self.pet_name} ({selected_type} - {self.rarity}급) 부화 완료!\n💸 소모 비용: {cost}P", interaction.user, discord.Color.purple(), guild=interaction.guild)

    async def on_timeout(self):
        if not self.chosen:
            try:
                wrapper = await get_or_migrate_data(self.user_id)
                selected_type = random.choice(PET_POOLS[self.rarity])

                if 'pets' not in wrapper: wrapper['pets'] = []
                new_pet_data = {
                    'name': self.pet_name, 'type': selected_type, 'rarity': self.rarity, 'level': 0, 'exp': 0, 'fullness': 100,
                    'intimacy': 50, 'fatigue': 0, 'cleanliness': 100, 'walk_count': 0, 'total_walk_count': 0,
                    'last_fatigue_calc': time.time()
                }
                wrapper['pets'].append(new_pet_data)
                wrapper['active_idx'] = len(wrapper['pets']) - 1
                await save_legend_data(self.user_id, wrapper)

                embed = discord.Embed(title="⏰ 선택 시간 초과!", description=f"자동으로 [{self.rarity}급] {selected_type} 알이 선택되었습니다!\n이름: `{self.pet_name}`", color=discord.Color.orange())
                if self.message:
                    await self.message.edit(embed=embed, view=None)
            except Exception as e: print(f"Hatch timeout error: {e}")

class PetSystemCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.voice_sessions = {}
        self.bot.loop.create_task(self.init_voice_sessions())
        self.voice_exp_loop.start()

    async def init_voice_sessions(self):
        await self.bot.wait_until_ready()
        now = time.time()
        for guild in self.bot.guilds:
            for vc in guild.voice_channels:
                for member in vc.members:
                    if not member.bot:
                        self.voice_sessions[member.id] = now

    def cog_unload(self):
        self.voice_exp_loop.cancel()

    @tasks.loop(seconds=60)
    async def voice_exp_loop(self):
        now = time.time()
        for user_id, last_reward_time in list(self.voice_sessions.items()):
            elapsed = now - last_reward_time
            if elapsed >= 60:
                minutes_passed = int(elapsed // 60)
                self.voice_sessions[user_id] = last_reward_time + (minutes_passed * 60)
                await self.add_exp_to_pet(user_id, minutes_passed * 60)

    async def evaluate_pet_status(self, user_id, wrapper, idx=None):
        if not wrapper.get('pets'): return None, [], False, False
        if idx is None: idx = wrapper.get('active_idx', 0)
        if idx >= len(wrapper['pets']): idx = 0

        data = wrapper['pets'][idx]
        if data.get('level', 0) == 0: return data, [], False, False

        now = time.time()
        active_buffs = await get_active_buffs(user_id)
        buffs = {b[0] for b in active_buffs}
        last_calc = data.get('last_fatigue_calc', now)
        elapsed_minutes = int((now - last_calc) // 60)

        if elapsed_minutes > 0:
            fatigue_drop = elapsed_minutes * 20
            data['fatigue'] = max(0, data.get('fatigue', 0) - fatigue_drop)
            data['last_fatigue_calc'] = last_calc + (elapsed_minutes * 60)
        elif 'last_fatigue_calc' not in data:
            data['last_fatigue_calc'] = now

        if "신비한 알약" in buffs:
            data['fullness'] = 100; data['fatigue'] = 0; data['intimacy'] = 100; data['cleanliness'] = 100
        else:
            if "배부름을 부르는 약" in buffs: data['fullness'] = 100
            if "쌩쌩한약" in buffs: data['fatigue'] = 0
            if "트위치 나가라약" in buffs: data['cleanliness'] = 100
            if "아무무도 인싸로 만드는 약" in buffs: data['intimacy'] = 100

        if data.get('fullness', 100) <= 20:
            if data.get('low_full_since', 0) == 0: data['low_full_since'] = now
        else: data['low_full_since'] = 0

        if data.get('cleanliness', 100) <= 20:
            if data.get('low_clean_since', 0) == 0: data['low_clean_since'] = now
        else: data['low_clean_since'] = 0

        is_annoyed = (data.get('low_full_since', 0) > 0 and now - data['low_full_since'] >= 86400)
        is_diseased = (data.get('low_clean_since', 0) > 0 and now - data['low_clean_since'] >= 86400)

        wrapper['pets'][idx] = data
        await save_legend_data(user_id, wrapper)
        return data, buffs, is_annoyed, is_diseased

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot: return
        if before.channel is None and after.channel is not None:
            self.voice_sessions[member.id] = time.time()
        elif before.channel is not None and after.channel is None:
            if member.id in self.voice_sessions:
                last_reward_time = self.voice_sessions.pop(member.id)
                duration_sec = time.time() - last_reward_time
                if duration_sec >= 60: await self.add_exp_to_pet(member.id, duration_sec)

    async def add_exp_to_pet(self, user_id, duration_sec):
        wrapper = await get_or_migrate_data(user_id)
        if not wrapper.get('pets'): return
        active_idx = wrapper.get('active_idx', 0)
        if active_idx >= len(wrapper['pets']): active_idx = 0; wrapper['active_idx'] = active_idx

        data = wrapper['pets'][active_idx]
        current_level = data.get('level', 0)
        if current_level >= 3: return

        if current_level == 0:
            earned_exp = int(duration_sec / 60)
            used_booster = None
        else:
            active_buffs = await get_active_buffs(user_id)
            buffs = {b[0]: b for b in active_buffs}

            exp_multiplier = 1
            if data.get('intimacy', 0) >= 80: exp_multiplier *= 2

            used_booster = None
            if "경험치 부스터 X10" in buffs: exp_multiplier *= 10; used_booster = "경험치 부스터 X10"
            elif "경험치 부스터 X5" in buffs: exp_multiplier *= 5; used_booster = "경험치 부스터 X5"
            elif "경험치 부스터 X2" in buffs: exp_multiplier *= 2; used_booster = "경험치 부스터 X2"

            earned_exp = int(duration_sec / 60 * exp_multiplier)

            if used_booster:
                vc_seconds_left = buffs[used_booster][2]
                new_vc_seconds = vc_seconds_left - duration_sec
                async with aiosqlite.connect('legends.db') as db:
                    if new_vc_seconds <= 0:
                        await db.execute("DELETE FROM active_buffs WHERE user_id = ? AND buff_name = ?", (user_id, used_booster))
                    else:
                        await db.execute("UPDATE active_buffs SET vc_seconds_left = ? WHERE user_id = ? AND buff_name = ?", (new_vc_seconds, user_id, used_booster))
                    await db.commit()

        if earned_exp <= 0: return

        data['exp'] = data.get('exp', 0) + earned_exp
        rarity = data.get('rarity', '서사')

        while data.get('level', 0) < 3:
            current_lvl = data.get('level', 0)
            required_exp = EXP_TABLE.get(rarity, {}).get(current_lvl, 100)
            if data.get('exp', 0) >= required_exp:
                data['level'] = current_lvl + 1
                data['exp'] -= required_exp
            else: break

        if data.get('level', 0) >= 3:
            await update_max_star(user_id, 3)

        wrapper['pets'][active_idx] = data
        await save_legend_data(user_id, wrapper)

    @app_commands.command(name="알까기", description="새로운 전설이 등급을 먼저 뽑고 원하는 전설이를 선택합니다.")
    async def hatch_egg(self, interaction: discord.Interaction, 이름: str):
        user_id = interaction.user.id
        wrapper = await get_or_migrate_data(user_id)
        is_first_time = (len(wrapper.get('pets', [])) == 0)

        if len(wrapper.get('pets', [])) >= 5:
            return await interaction.response.send_message("❌ 전설이는 최대 5마리까지만 키울 수 있습니다! (박스에 보관하세요)", ephemeral=True)

        current_points = await get_points(user_id)
        cost = 0 if is_first_time else 1000
        if current_points < cost: return await interaction.response.send_message(f"가챠 비용이 부족합니다! (필요: {cost}P)", ephemeral=True)

        if not is_first_time: await add_points(user_id, -cost)

        rarity = random.choices(list(PET_POOLS.keys()), weights=[85, 14, 0.9, 0.1, 0.0, 0.0], k=1)[0]
        embed = discord.Embed(title="🎉 알까기 당첨!", description=f"[{rarity}급] 알이 당첨되었습니다!\n아래 메뉴에서 원하는 종류의 전설이를 선택하세요.", color=discord.Color.gold())

        view = HatchView(self.bot, user_id, rarity, 이름, is_first_time)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()

    @app_commands.command(name="순서변경", description="보유 중인 전설이들의 파티 배치 순서를 변경합니다.")
    @app_commands.choices(기존슬롯=[
        app_commands.Choice(name="1번 슬롯", value=0), app_commands.Choice(name="2번 슬롯", value=1),
        app_commands.Choice(name="3번 슬롯", value=2), app_commands.Choice(name="4번 슬롯", value=3),
        app_commands.Choice(name="5번 슬롯", value=4)
    ], 새슬롯=[
        app_commands.Choice(name="1번 슬롯", value=0), app_commands.Choice(name="2번 슬롯", value=1),
        app_commands.Choice(name="3번 슬롯", value=2), app_commands.Choice(name="4번 슬롯", value=3),
        app_commands.Choice(name="5번 슬롯", value=4)
    ])
    async def change_pet_order(self, interaction: discord.Interaction, 기존슬롯: int, 새슬롯: int):
        if 기존슬롯 == 새슬롯:
            return await interaction.response.send_message("❌ 기존 슬롯과 변경할 슬롯이 같습니다.", ephemeral=True)

        wrapper = await get_or_migrate_data(interaction.user.id)
        pets = wrapper.get('pets', [])

        if 기존슬롯 >= len(pets) or 새슬롯 >= len(pets):
            return await interaction.response.send_message(f"❌ 선택한 슬롯에 전설이가 존재하지 않습니다. (현재 보유 전설이 수: {len(pets)}마리)", ephemeral=True)

        active_idx = wrapper.get('active_idx', 0)
        if active_idx >= len(pets):
            active_idx = 0
        current_active_pet = pets[active_idx]

        pets[기존슬롯], pets[새슬롯] = pets[새슬롯], pets[기존슬롯]

        wrapper['active_idx'] = pets.index(current_active_pet)
        wrapper['pets'] = pets

        await save_legend_data(interaction.user.id, wrapper)

        p1_name = pets[새슬롯].get('name', '이름없음')
        p2_name = pets[기존슬롯].get('name', '이름없음')

        await interaction.response.send_message(
            f"🔄 전설이들의 배치 순서가 성공적으로 변경되었습니다!\n"
            f"▪️ {기존슬롯 + 1}번 슬롯 ➡️ {새슬롯 + 1}번 슬롯: `{p1_name}`\n"
            f"▪️ {새슬롯 + 1}번 슬롯 ➡️ {기존슬롯 + 1}번 슬롯: `{p2_name}`",
            ephemeral=True
        )

    @app_commands.command(name="스탯", description="내 전설이(또는 다른 유저)의 스탯을 확인합니다.")
    async def pet_stats_cmd(self, interaction: discord.Interaction, 유저: discord.Member = None):
        target = 유저 or interaction.user
        wrapper = await get_or_migrate_data(target.id)

        if not wrapper or not wrapper.get('pets'): return await interaction.response.send_message(f"❌ {target.display_name}님은 아직 전설이가 없습니다.", ephemeral=False)
        embed = discord.Embed(title=f"📊 {target.display_name}님의 전설이 스탯", color=discord.Color.blue())

        for i, pet in enumerate(wrapper['pets']):
            pet_name = pet.get('name', '이름없음')
            pet_type = pet.get('type', '알 수 없음')
            level = pet.get('level', 0)

            if level == 0: embed.add_field(name=f"[{i+1}] 🥚 {pet_name} (알)", value="아직 부화하지 않아 스탯이 없습니다.", inline=False)
            else:
                stats = get_pet_stats(pet_type, level)
                stats_str = f"⚔️ 공격력(AD): {stats['AD']} | 🛡️ 방어력(DF): {stats['DF']}\n✨ 주문력(AP): {stats['AP']} | 🌀 마법저항력(MR): {stats['MR']}"
                embed.add_field(name=f"[{i+1}] {pet_name} ({level}성 {pet_type})", value=stats_str, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="상태창", description="내 전설이의 상태를 확인하고 돌봅니다.")
    async def status_window(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)

        wrapper = await get_or_migrate_data(interaction.user.id)
        if not wrapper.get('pets'):
            return await interaction.followup.send("아직 전설이가 없습니다. `/알까기`로 시작하세요!", ephemeral=True)

        active_idx = wrapper.get('active_idx', 0)
        total_pets = len(wrapper['pets'])
        if active_idx >= total_pets:
            active_idx = 0; wrapper['active_idx'] = 0
            await save_legend_data(interaction.user.id, wrapper)

        data, buffs, is_annoyed, is_diseased = await self.evaluate_pet_status(interaction.user.id, wrapper, active_idx)
        current_points = await get_points(interaction.user.id)

        status_image_file = await generate_status_image(
            data, current_points, buffs, is_annoyed, is_diseased, active_idx, total_pets
        )

        view = LegendActionView(interaction.user.id, current_idx=active_idx, total_pets=total_pets, pet_level=data.get('level', 0))
        await interaction.followup.send(file=status_image_file, view=view)

async def setup(bot):
    await bot.add_cog(PetSystemCog(bot))