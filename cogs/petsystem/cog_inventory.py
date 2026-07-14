import discord
from discord.ext import commands
from discord import app_commands
import aiosqlite

from utils.data import PET_POOLS, ITEMS_INFO
from .ui_inventory import InventoryView

class InventoryCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # 💡 [수정됨] 설명에서 '판매' 단어 제거
    @app_commands.command(name="보관함", description="내 아이템을 확인하고 사용합니다.")
    async def inventory(self, interaction: discord.Interaction):
        async with aiosqlite.connect('legends.db') as db:
            async with db.execute("SELECT item_name, amount FROM user_items WHERE user_id = ? AND amount > 0", (interaction.user.id,)) as cursor:
                rows = await cursor.fetchall()

        items = dict(rows)
        if not items: return await interaction.response.send_message("보관함이 비어있습니다.", ephemeral=True)

        embed = discord.Embed(title="🎒 내 보관함", description="아래 메뉴에서 아이템을 선택한 후 사용 버튼을 눌러주세요.", color=discord.Color.blurple())
        for item_name, amount in items.items():
            embed.add_field(name=f"▪️ {item_name}", value=f"{amount}개 보유", inline=False)

        view = InventoryView(interaction.user.id, items)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="전설이목록", description="등급별 획득 가능한 전설이 목록을 확인합니다.")
    async def legend_list(self, interaction: discord.Interaction):
        embed = discord.Embed(title="📜 전설이 목록", color=discord.Color.blue())
        for rarity, pets in PET_POOLS.items():
            embed.add_field(name=f"[{rarity}급]", value=", ".join(pets), inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="아이템목록", description="모든 아이템의 효과와 등급을 확인합니다.")
    async def item_list(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🎒 아이템 도감", color=discord.Color.green())
        for name, info in ITEMS_INFO.items():
            embed.add_field(name=f"[{info['rarity']}] {name}", value=info['desc'], inline=False)
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(InventoryCog(bot))