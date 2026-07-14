import discord
from discord.ext import commands
from discord import app_commands
import time
import traceback
import aiosqlite

from utils.data import PET_POOLS, EXP_TABLE
from utils.database import get_or_migrate_data, save_legend_data, add_item, consume_item, update_max_star
from utils.logs import (
    send_log_embed,
    EGG_GIVE_LOG_CH, EGG_TAKE_LOG_CH,
    ITEM_GIVE_LOG_CH, ITEM_TAKE_LOG_CH,
)

class AdminEggGiveView(discord.ui.View):
    def __init__(self, admin: discord.Member, target: discord.Member, rarity: str, pet_name: str):
        super().__init__(timeout=60)
        self.admin = admin
        self.target = target
        self.rarity = rarity
        self.pet_name = pet_name

        options = [discord.SelectOption(label=p, value=p) for p in PET_POOLS[rarity][:25]]
        self.select = discord.ui.Select(placeholder=f"지급할 {rarity}급 전설이를 선택하세요", options=options)
        self.select.callback = self.on_select
        self.add_item(self.select)

    async def on_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.admin.id: return
        pet_type = self.select.values[0]
        wrapper = await get_or_migrate_data(self.target.id)
        if 'pets' not in wrapper: wrapper['pets'] = []

        if len(wrapper['pets']) >= 5:
            return await interaction.response.edit_message(content=f"❌ {self.target.display_name}님은 이미 5마리의 전설이를 보유하고 있습니다.", view=None)

        new_pet_data = {
            'name': self.pet_name, 'type': pet_type, 'rarity': self.rarity, 'level': 0, 'exp': 0, 'fullness': 100,
            'intimacy': 50, 'fatigue': 0, 'cleanliness': 100, 'walk_count': 0, 'total_walk_count': 0, 'last_fatigue_calc': time.time()
        }
        wrapper['pets'].append(new_pet_data)
        if len(wrapper['pets']) == 1: wrapper['active_idx'] = 0

        await save_legend_data(self.target.id, wrapper)
        await interaction.response.edit_message(content=f"✅ {self.target.display_name}님에게 `{self.pet_name}` ({self.rarity} - {pet_type}) 알을 성공적으로 지급했습니다!", view=None)
        await send_log_embed(interaction.client, EGG_GIVE_LOG_CH, "🛠️ [관리자] 알 지급", f"대상: {self.target.mention}\n지급된 알: {self.pet_name} ({pet_type} - {self.rarity}급)", interaction.user, discord.Color.green())

class AdminEggTakeView(discord.ui.View):
    def __init__(self, admin: discord.Member, target: discord.Member, pets_found: list, wrapper: dict):
        super().__init__(timeout=60)
        self.admin = admin
        self.target = target
        self.pets_found = pets_found
        self.wrapper = wrapper

        options = [discord.SelectOption(label=f"{p['name']} ({p['type']})", value=str(i)) for i, p in enumerate(pets_found)]
        self.select = discord.ui.Select(placeholder="회수할 전설이를 선택하세요", options=options)
        self.select.callback = self.on_select
        self.add_item(self.select)

    async def on_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.admin.id: return
        target_idx = int(self.select.values[0])
        pet_to_remove = self.pets_found[target_idx]

        real_idx = self.wrapper['pets'].index(pet_to_remove)
        removed = self.wrapper['pets'].pop(real_idx)
        self.wrapper['active_idx'] = max(0, len(self.wrapper['pets']) - 1)

        await save_legend_data(self.target.id, self.wrapper)
        await interaction.response.edit_message(content=f"✅ {self.target.display_name}님의 `{removed['name']} ({removed['rarity']} - {removed['type']})`(을)를 강제 회수했습니다.", view=None)
        await send_log_embed(interaction.client, EGG_TAKE_LOG_CH, "🛠️ [관리자] 알 회수", f"대상: {self.target.mention}\n회수된 알: {removed['name']} ({removed['type']} - {removed['rarity']}급)", interaction.user, discord.Color.red())

class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ 관리자 권한이 없습니다.", ephemeral=True)
        else: await interaction.response.send_message(f"❌ 오류: {error}", ephemeral=True)

    @app_commands.command(name="알지급", description="[관리자] 유저에게 알을 지급합니다.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.choices(등급=[app_commands.Choice(name=k, value=k) for k in PET_POOLS.keys()])
    async def give_egg(self, interaction: discord.Interaction, 유저: discord.Member, 알이름: str, 등급: str):
        view = AdminEggGiveView(interaction.user, 유저, 등급, 알이름)
        await interaction.response.send_message(f"👇 지급할 {등급}급 전설이 종류를 선택하세요.", view=view, ephemeral=True)

    @app_commands.command(name="알회수", description="[관리자] 유저의 전설이를 회수합니다.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.choices(등급=[app_commands.Choice(name=k, value=k) for k in PET_POOLS.keys()])
    async def remove_egg(self, interaction: discord.Interaction, 유저: discord.Member, 알이름: str, 등급: str):
        wrapper = await get_or_migrate_data(유저.id)
        if not wrapper.get('pets'): return await interaction.response.send_message("❌ 보유한 전설이가 없습니다.", ephemeral=True)

        pets_found = [p for p in wrapper['pets'] if p.get('name') == 알이름 and p.get('rarity') == 등급]
        if not pets_found:
            return await interaction.response.send_message(f"❌ 조건에 맞는 펫이 없습니다.", ephemeral=True)
        elif len(pets_found) == 1:
            removed = pets_found[0]
            wrapper['pets'].remove(removed)
            wrapper['active_idx'] = max(0, len(wrapper['pets']) - 1)
            await save_legend_data(유저.id, wrapper)
            await send_log_embed(interaction.client, EGG_TAKE_LOG_CH, "🛠️ [관리자] 알 회수", f"대상: {유저.mention}\n회수된 알: {removed['name']} ({removed['type']} - {removed['rarity']}급)", interaction.user, discord.Color.red())
            return await interaction.response.send_message(f"✅ `{removed['name']}`(을)를 강제 회수했습니다.", ephemeral=True)
        else:
            view = AdminEggTakeView(interaction.user, 유저, pets_found, wrapper)
            await interaction.response.send_message(f"👇 중복된 펫이 있습니다. 회수할 펫을 정확히 선택하세요.", view=view, ephemeral=True)

    @app_commands.command(name="아이템지급", description="[관리자] 유저에게 아이템을 지급합니다.")
    @app_commands.default_permissions(administrator=True)
    async def admin_add_item(self, interaction: discord.Interaction, 유저: discord.Member, 종류: str, 개수: int):
        if 개수 <= 0: return await interaction.response.send_message("개수는 1개 이상이어야 합니다.", ephemeral=True)
        await add_item(유저.id, 종류, 개수)
        await interaction.response.send_message(f"✅ {유저.display_name}님에게 `{종류}` {개수}개를 지급했습니다.", ephemeral=True)
        await send_log_embed(interaction.client, ITEM_GIVE_LOG_CH, "🛠️ [관리자] 아이템 지급", f"대상: {유저.mention}\n아이템: {종류} x{개수}", interaction.user, discord.Color.green())

    @app_commands.command(name="아이템회수", description="[관리자] 유저의 아이템을 회수합니다.")
    @app_commands.default_permissions(administrator=True)
    async def admin_remove_item(self, interaction: discord.Interaction, 유저: discord.Member, 종류: str, 개수: int):
        if 개수 <= 0: return await interaction.response.send_message("개수는 1개 이상이어야 합니다.", ephemeral=True)
        success = await consume_item(유저.id, 종류, 개수)
        if success:
            await interaction.response.send_message(f"✅ 회수 완료", ephemeral=True)
            await send_log_embed(interaction.client, ITEM_TAKE_LOG_CH, "🛠️ [관리자] 아이템 회수", f"대상: {유저.mention}\n아이템: {종류} x{개수}", interaction.user, discord.Color.red())
        else: await interaction.response.send_message(f"❌ 부족합니다.", ephemeral=True)

    @app_commands.command(name="아이템확인", description="[관리자] 유저의 보관함을 확인합니다.")
    @app_commands.default_permissions(administrator=True)
    async def admin_check_item(self, interaction: discord.Interaction, 유저: discord.Member):
        async with aiosqlite.connect('legends.db') as db:
            async with db.execute("SELECT item_name, amount FROM user_items WHERE user_id = ? AND amount > 0", (유저.id,)) as cursor:
                rows = await cursor.fetchall()
        if not rows: return await interaction.response.send_message(f"🎒 {유저.display_name}님의 보관함이 비어있습니다.", ephemeral=True)
        embed = discord.Embed(title=f"🎒 {유저.display_name}님의 보관함", color=discord.Color.purple())
        for item_name, amount in rows: embed.add_field(name=item_name, value=f"{amount}개", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="아이템초기화", description="[관리자] 유저의 모든 아이템을 영구 삭제합니다.")
    @app_commands.default_permissions(administrator=True)
    async def admin_reset_item(self, interaction: discord.Interaction, 유저: discord.Member):
        async with aiosqlite.connect('legends.db') as db:
            await db.execute("DELETE FROM user_items WHERE user_id = ?", (유저.id,))
            await db.commit()
        await interaction.response.send_message(f"💥 초기화 완료", ephemeral=True)

    @app_commands.command(name="강제부화", description="[관리자] 유저의 활성화된 알을 즉시 1성으로 부화시킵니다.")
    @app_commands.default_permissions(administrator=True)
    async def force_hatch_cmd(self, interaction: discord.Interaction, 유저: discord.Member):
        await interaction.response.defer(ephemeral=True)
        try:
            wrapper = await get_or_migrate_data(유저.id)
            if not wrapper.get('pets'): return await interaction.followup.send("❌ 해당 유저는 보유한 전설이가 없습니다.")
            active_idx = wrapper.get('active_idx', 0)
            if active_idx >= len(wrapper['pets']): active_idx = 0
            data = wrapper['pets'][active_idx]
            if data.get('level', 0) > 0: return await interaction.followup.send(f"해당 펫은 이미 부화했습니다.")
            data['level'] = 1; data['exp'] = 0
            wrapper['pets'][active_idx] = data
            await save_legend_data(유저.id, wrapper)
            await interaction.followup.send(f"✅ 강제부화 성공!")
        except Exception: traceback.print_exc(); await interaction.followup.send("❌ 오류")

    @app_commands.command(name="성급상승", description="[관리자] 전설이 성급을 1단계 올립니다.")
    @app_commands.default_permissions(administrator=True)
    async def level_up_pet(self, interaction: discord.Interaction, 유저: discord.Member, 알이름: str):
        await interaction.response.defer(ephemeral=True)
        wrapper = await get_or_migrate_data(유저.id)
        target_idx = next((i for i, p in enumerate(wrapper.get('pets', [])) if p.get('name') == 알이름), -1)
        if target_idx == -1: return await interaction.followup.send("❌ 펫을 찾을 수 없습니다.")
        if wrapper['pets'][target_idx].get('level', 0) >= 3: return await interaction.followup.send("❌ 이미 역할 최대성급입니다.")
        wrapper['pets'][target_idx]['level'] += 1; wrapper['pets'][target_idx]['exp'] = 0

        if wrapper['pets'][target_idx]['level'] >= 3:
            await update_max_star(유저.id, 3)

        await save_legend_data(유저.id, wrapper)
        await interaction.followup.send(f"✅ 성급 상승 완료!")

    @app_commands.command(name="성급하락", description="[관리자] 전설이 성급을 1단계 내립니다.")
    @app_commands.default_permissions(administrator=True)
    async def level_down_pet(self, interaction: discord.Interaction, 유저: discord.Member, 알이름: str):
        await interaction.response.defer(ephemeral=True)
        wrapper = await get_or_migrate_data(유저.id)
        target_idx = next((i for i, p in enumerate(wrapper.get('pets', [])) if p.get('name') == 알이름), -1)
        if target_idx == -1: return await interaction.followup.send("❌ 펫을 찾을 수 없습니다.")
        if wrapper['pets'][target_idx].get('level', 0) <= 0: return await interaction.followup.send("❌ 이미 알입니다.")
        wrapper['pets'][target_idx]['level'] -= 1; wrapper['pets'][target_idx]['exp'] = 0
        await save_legend_data(유저.id, wrapper)
        await interaction.followup.send(f"✅ 성급 하락 완료!")

    @app_commands.command(name="이름변경", description="[관리자] 펫의 이름을 변경합니다.")
    @app_commands.default_permissions(administrator=True)
    async def admin_rename_pet(self, interaction: discord.Interaction, 유저: discord.Member, 알이름: str, 변경할이름: str):
        await interaction.response.defer(ephemeral=True)
        wrapper = await get_or_migrate_data(유저.id)
        target_idx = next((i for i, p in enumerate(wrapper.get('pets', [])) if p.get('name') == 알이름), -1)
        if target_idx == -1: return await interaction.followup.send("❌ 펫을 찾을 수 없습니다.")
        wrapper['pets'][target_idx]['name'] = 변경할이름
        await save_legend_data(유저.id, wrapper)
        await interaction.followup.send(f"✅ 이름 변경 완료!")

    @app_commands.command(name="경험치지급", description="[관리자] 유저의 특정 전설이에게 경험치를 지급합니다.")
    @app_commands.default_permissions(administrator=True)
    async def admin_give_exp(self, interaction: discord.Interaction, 유저: discord.Member, 알이름: str, 수량: int):
        if 수량 <= 0:
            return await interaction.response.send_message("❌ 지급할 경험치는 1 이상이어야 합니다.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        try:
            wrapper = await get_or_migrate_data(유저.id)
            if not wrapper.get('pets'):
                return await interaction.followup.send("❌ 해당 유저는 보유한 전설이가 없습니다.")

            target_idx = next((i for i, p in enumerate(wrapper.get('pets', [])) if p.get('name') == 알이름), -1)
            if target_idx == -1:
                return await interaction.followup.send("❌ 해당 이름의 전설이를 찾을 수 없습니다.")

            data = wrapper['pets'][target_idx]
            current_level = data.get('level', 0)
            if current_level >= 3:
                return await interaction.followup.send("❌ 이미 최대 성급(3성)에 도달한 전설이입니다.")

            # 경험치 가산
            data['exp'] = data.get('exp', 0) + 수량
            rarity = data.get('rarity', '서사')

            initial_level = current_level
            # 💡 [핵심 수정] 하드코딩 사전을 전면 철거하고 data.py의 글로벌 EXP_TABLE을 추적 및 연동
            while data.get('level', 0) < 3:
                curr_lvl = data.get('level', 0)
                req_exp = EXP_TABLE.get(rarity, {}).get(curr_lvl, 100)
                if data.get('exp', 0) >= req_exp:
                    data['level'] = curr_lvl + 1
                    data['exp'] -= req_exp
                else:
                    break

            if data.get('level', 0) >= 3:
                await update_max_star(유저.id, 3)

            wrapper['pets'][target_idx] = data
            await save_legend_data(유저.id, wrapper)

            msg = f"✅ {유저.display_name}님의 `{알이름}`에게 경험치 {수량:,} XP를 지급했습니다!"
            if data['level'] > initial_level:
                msg += f" 🎉 성급 상승: {initial_level}성 ➡️ {data['level']}성"

            await interaction.followup.send(msg)

            await send_log_embed(
                interaction.client,
                ITEM_GIVE_LOG_CH,
                "🛠️ [관리자] 경험치 지급",
                f"대상: {유저.mention}\n전설이: {알이름} ({data.get('type', '알 수 없음')} - {rarity}급)\n지급량: +{수량:,} XP\n결과 상태: {data['level']}성 ({data['exp']:,} XP)",
                interaction.user,
                discord.Color.green()
            )
        except Exception:
            traceback.print_exc()
            await interaction.followup.send("❌ 경험치 지급 중 내부 오류가 발생했습니다.")

async def setup(bot):
    await bot.add_cog(AdminCog(bot))