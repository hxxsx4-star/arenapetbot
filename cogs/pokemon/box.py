import discord
from discord import app_commands
from discord.ext import commands

from . import db
from utils.logs import is_target_guild

PAGE_SIZE = 10


def _build_box_embed(display_name: str, rows: list[dict], page: int, total: int) -> discord.Embed:
    embed = discord.Embed(title=f"{display_name}의 포켓몬함", color=discord.Color.gold())
    if not rows:
        embed.description = "아직 포획한 포켓몬이 없습니다. 스폰 채널에서 야생 포켓몬을 잡아보세요!"
        return embed

    lines = []
    for r in rows:
        mark = "⭐ " if r["is_partner"] else ""
        nickname = f" 「{r['nickname']}」" if r["nickname"] else ""
        lines.append(f"{mark}**{r['name_ko']}**{nickname} · Lv.{r['level']} · {r['rarity']} (#{r['uid']})")
    embed.description = "\n".join(lines)

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    embed.set_footer(text=f"페이지 {page + 1}/{total_pages} · 총 {total}마리")
    return embed


class BoxView(discord.ui.View):
    def __init__(self, owner_id: int, display_name: str, page: int, total: int):
        super().__init__(timeout=120)
        self.owner_id = owner_id
        self.display_name = display_name
        self.page = page
        self.total = total
        self._update_buttons()

    def _update_buttons(self):
        self.prev_button.disabled = self.page <= 0
        self.next_button.disabled = (self.page + 1) * PAGE_SIZE >= self.total

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "본인의 포켓몬함만 조작할 수 있습니다.", ephemeral=True
            )
            return False
        return True

    async def _refresh(self, interaction: discord.Interaction):
        rows = await db.list_user_pokemon(self.owner_id, limit=PAGE_SIZE, offset=self.page * PAGE_SIZE)
        self._update_buttons()
        embed = _build_box_embed(self.display_name, rows, self.page, self.total)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        self.page -= 1
        await self._refresh(interaction)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        self.page += 1
        await self._refresh(interaction)


class BoxCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="포켓몬함", description="보유한 포켓몬 목록을 확인합니다.")
    async def box_command(self, interaction: discord.Interaction):
        if interaction.guild is None or not is_target_guild(interaction.guild):
            await interaction.response.send_message(
                "이 명령어는 지정된 서버에서만 사용할 수 있습니다.", ephemeral=True
            )
            return

        total = await db.get_user_pokemon_count(interaction.user.id)
        rows = await db.list_user_pokemon(interaction.user.id, limit=PAGE_SIZE, offset=0)
        embed = _build_box_embed(interaction.user.display_name, rows, 0, total)
        view = BoxView(interaction.user.id, interaction.user.display_name, 0, total) if total > PAGE_SIZE else None
        await interaction.response.send_message(embed=embed, view=view)
