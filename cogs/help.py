import discord
from discord.ext import commands
from discord import app_commands

class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    help_group = app_commands.Group(name="도움말", description="봇의 명령어 목록을 확인합니다.")

    @help_group.command(name="일반", description="일반 사용자를 위한 명령어 목록을 확인합니다.")
    async def help_general(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🎲 전설이 키우기 가이드 & 도움말 🎲",
            description="새로운 기능들이 추가된 명령어 목록입니다.",
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=self.bot.user.avatar.url if self.bot.user.avatar else None)

        embed.add_field(name="🐾 전설이 키우기",
                        value="`/알까기 <이름>`: 새로운 전설이를 얻습니다.\n"
                              "`/상태창`: 전설이를 돌보고 스탯을 확인합니다.\n"
                              "`/펫교체 <슬롯>`: 돌볼 전설이를 바꿉니다.\n"
                              "`/스탯 [유저]`: 전설이 스탯을 확인합니다.\n"
                              "`/보관함`: 아이템과 알을 확인하고 사용/분해합니다.\n"
                              "`/알환전`, `/알분해`: 알 등급을 변경합니다.", inline=False)

        embed.add_field(name="⚔️ 배틀 및 베팅 시스템",
                        value="`/배틀1vs1 <유저>`: 1:1 진검승부를 펼칩니다.\n"
                              "`/배틀5vs5 <유저>`: 서로 다른 종류 5마리로 총력전을 합니다.\n"
                              "📢 응원(베팅) 규칙: 배틀이 열리면 관전자는 `응원하기`를 눌러 이길 것 같은 쪽에 걸 수 있습니다. 맞추면 서사알 10개 획득, 틀리면 압수!", inline=False)

        embed.add_field(name="🏆 업적 및 도감",
                        value="`/업적`: 나의 수집 현황과 업적 달성도를 봅니다.\n"
                              "`/알개수`: 서버 내 서사급 알 부자 TOP 5를 확인합니다.\n"
                              "`/전설이목록`, `/아이템목록`: 게임 내 정보를 봅니다.\n"
                              "✨ 특정 조건 달성 시 특별한 역할(Role)이 부여됩니다!", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @help_group.command(name="관리자", description="[관리자] 관리자를 위한 명령어 목록을 확인합니다.")
    @app_commands.default_permissions(administrator=True)
    async def help_admin(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🛠️ 관리자 명령어 가이드", color=discord.Color.red())

        embed.add_field(name="📦 아이템/알 관리 (UI 지원)",
                        value="`/알지급` / `/알회수`: UI 드롭다운을 통해 쉽고 정확하게 알을 지급/회수합니다.\n"
                              "`/아이템지급` / `/아이템회수`: 아이템 수량을 조절합니다.\n"
                              "`/아이템확인` / `/아이템초기화`: 유저의 보관함을 관리합니다.", inline=False)

        embed.add_field(name="🐾 전설이 즉각 조작",
                        value="`/강제부화`: 알을 즉시 1성으로 부화시킵니다.\n"
                              "`/성급상승` / `/성급하락`: 전설이의 레벨(성)을 강제 조정합니다.\n"
                              "`/이름변경`: 펫의 이름을 변경합니다.\n"
                              "`/사용법게시 <채널>`: 채널에 가이드를 게시합니다.", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="사용법게시", description="[관리자] 지정된 채널에 전설이 시스템 사용법 안내를 게시합니다.")
    @app_commands.default_permissions(manage_guild=True)
    async def post_guide(self, interaction: discord.Interaction, channel: discord.TextChannel):
        guide_embed = discord.Embed(title="🐾 전설이 키우기 가이드 🐾", description="나만의 작은 전설이를 키워보세요!", color=discord.Color.gold())
        guide_embed.add_field(name="1️⃣ 시작하기", value="`/알까기`로 첫 전설이 알을 받으세요. 음성 채널에 접속해 경험치를 모으면 알이 부화합니다.", inline=False)
        guide_embed.add_field(name="2️⃣ 돌보기", value="`/상태창`에서 전설이를 돌보세요. 샤워(10P), 밥주기(5P), 산책(10P)이 가능합니다.", inline=False)
        guide_embed.add_field(name="3️⃣ 성장과 버프", value="음성 채널에 접속하면 시간이 지남에 따라 경험치가 오릅니다. 친밀도가 높으면 획득량이 2배가 됩니다.", inline=False)
        guide_embed.add_field(name="4️⃣ 업적과 배틀", value="`/업적`을 달성해 역할을 얻고, `/배틀5vs5`를 통해 친구들과 승부를 겨뤄보세요!", inline=False)

        try:
            await channel.send(embed=guide_embed)
            await interaction.response.send_message(f"✅ {channel.mention} 채널에 안내를 게시했습니다.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ 오류 발생: {e}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(HelpCog(bot))