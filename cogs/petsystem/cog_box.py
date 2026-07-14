import discord
from discord.ext import commands
from discord import app_commands
import time

from utils.database import get_or_migrate_data, save_legend_data

class BoxActionView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=120)
        self.user_id = user_id

    @discord.ui.button(label="📥 보관하기", style=discord.ButtonStyle.primary, emoji="📦")
    async def store_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ 본인의 박스만 조작할 수 있습니다.", ephemeral=True)

        wrapper = await get_or_migrate_data(self.user_id)
        pets = wrapper.get('pets', [])

        if not pets:
            return await interaction.response.send_message("❌ 현재 보관할 전설이가 없습니다.", ephemeral=True)

        # 셀렉트 뷰 생성
        options = [discord.SelectOption(label=f"{p['name']} ({p['rarity']} {p['type']})", value=str(i)) for i, p in enumerate(pets)]
        select = discord.ui.Select(placeholder="박스에 보관할 전설이를 선택하세요.", options=options)

        async def select_callback(sel_inter: discord.Interaction):
            idx = int(select.values[0])
            wrapper = await get_or_migrate_data(self.user_id)

            # 박스 리스트 생성 (없을 경우)
            wrapper.setdefault('box', [])

            pet_to_store = wrapper['pets'].pop(idx)

            # 💡 [요청사항] 보관 시 상태 완충
            pet_to_store['fullness'] = 100
            pet_to_store['cleanliness'] = 100
            pet_to_store['fatigue'] = 0
            pet_to_store['intimacy'] = 100
            pet_to_store['last_fatigue_calc'] = time.time()

            wrapper['box'].append(pet_to_store)
            wrapper['active_idx'] = max(0, len(wrapper['pets']) - 1)

            await save_legend_data(self.user_id, wrapper)
            await sel_inter.response.edit_message(content=f"✅ `{pet_to_store['name']}`(을)를 박스에 안전하게 보관했습니다! (모든 스탯이 최대치로 고정됩니다)", view=None, embed=None)

        select.callback = select_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)

        await interaction.response.send_message("보관할 전설이를 골라주세요:", view=view, ephemeral=True)

    @discord.ui.button(label="📤 복귀하기", style=discord.ButtonStyle.success, emoji="🐾")
    async def retrieve_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ 본인의 박스만 조작할 수 있습니다.", ephemeral=True)

        wrapper = await get_or_migrate_data(self.user_id)
        box_pets = wrapper.get('box', [])

        if not box_pets:
            return await interaction.response.send_message("❌ 박스에 보관된 전설이가 없습니다.", ephemeral=True)

        if len(wrapper.get('pets', [])) >= 5:
            return await interaction.response.send_message("❌ 파티가 꽉 찼습니다! (최대 5마리) 자리를 비우고 복귀시켜주세요.", ephemeral=True)

        # 박스 내 최대 25마리까지만 표시 (Discord Select Menu 한계)
        options = [discord.SelectOption(label=f"{p['name']} ({p['rarity']} {p['type']})", value=str(i)) for i, p in enumerate(box_pets[:25])]
        select = discord.ui.Select(placeholder="파티로 복귀시킬 전설이를 선택하세요.", options=options)

        async def select_callback(sel_inter: discord.Interaction):
            idx = int(select.values[0])
            wrapper = await get_or_migrate_data(self.user_id)

            pet_to_retrieve = wrapper['box'].pop(idx)
            pet_to_retrieve['last_fatigue_calc'] = time.time() # 복귀한 시점부터 피로도 다시 계산

            wrapper['pets'].append(pet_to_retrieve)
            wrapper['active_idx'] = len(wrapper['pets']) - 1

            await save_legend_data(self.user_id, wrapper)
            await sel_inter.response.edit_message(content=f"✅ `{pet_to_retrieve['name']}`(이)가 파티에 합류했습니다!", view=None, embed=None)

        select.callback = select_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)

        await interaction.response.send_message("복귀시킬 전설이를 골라주세요:", view=view, ephemeral=True)

class BoxSystemCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="박스", description="전설이를 안전한 박스에 임시로 보관하거나 다시 데려옵니다.")
    async def pc_box(self, interaction: discord.Interaction):
        wrapper = await get_or_migrate_data(interaction.user.id)
        party_count = len(wrapper.get('pets', []))
        box_count = len(wrapper.get('box', []))

        embed = discord.Embed(title="📦 전설이 임시 보관 박스", color=discord.Color.teal())
        embed.description = "전설이를 박스에 넣으면 배고픔과 피로함을 느끼지 않고 편안하게 쉴 수 있습니다.\n(모든 스탯이 최고 상태로 보존됩니다)"
        embed.add_field(name="현재 파티", value=f"{party_count} / 5 마리", inline=True)
        embed.add_field(name="박스에 있는 수", value=f"{box_count} 마리", inline=True)

        view = BoxActionView(interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

async def setup(bot):
    await bot.add_cog(BoxSystemCog(bot))