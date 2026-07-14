import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import random

from utils.database import get_or_migrate_data, add_item, consume_item, get_item_amount, set_item_amount
from .ui_action import get_pet_stats
from utils.stats import add_points

class BetView(discord.ui.View):
    def __init__(self, p1: discord.Member, p2: discord.Member):
        super().__init__(timeout=15)
        self.p1 = p1
        self.p2 = p2
        self.bets = {}

    @discord.ui.button(label="응원하기 (베팅)", style=discord.ButtonStyle.success, emoji="📣")
    async def bet_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in [self.p1.id, self.p2.id]:
            return await interaction.response.send_message("❌ 배틀 당사자는 베팅할 수 없습니다!", ephemeral=True)

        options = [
            discord.SelectOption(label=f"{self.p1.display_name} 응원", value="p1", description="승리시 서사급 알 10개 획득!"),
            discord.SelectOption(label=f"{self.p2.display_name} 응원", value="p2", description="패배시 서사급 알 10개(또는 전설1) 압수!")
        ]
        select = discord.ui.Select(placeholder="누가 이길지 선택하세요!", options=options)

        async def select_callback(inter: discord.Interaction):
            is_p1 = (select.values[0] == "p1")
            self.bets[inter.user.id] = {"member": inter.user, "bet_p1": is_p1}
            await inter.response.edit_message(content=f"✅ 베팅 완료! 결과를 기다려주세요.", view=None)

        select.callback = select_callback
        view = discord.ui.View()
        view.add_item(select)
        await interaction.response.send_message("👇 베팅할 대상을 고르세요! (한 번만 선택 가능)", view=view, ephemeral=True)

class BattleCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_battles = set()

    def calc_pet_power(self, pet_data):
        if pet_data.get('level', 0) == 0: return 0
        stats = get_pet_stats(pet_data['type'], pet_data['level'])
        return stats['AD'] + stats['DF'] + stats['AP'] + stats['MR']

    @app_commands.command(name="배틀1vs1", description="내 전설이 한 마리를 선택해 상대방과 1vs1 배틀을 벌입니다.")
    async def battle_1v1(self, interaction: discord.Interaction, 상대: discord.Member):
        if interaction.user == 상대 or 상대.bot: return await interaction.response.send_message("❌ 불가", ephemeral=True)
        if interaction.user.id in self.active_battles or 상대.id in self.active_battles: return await interaction.response.send_message("❌ 다른 배틀 중입니다.", ephemeral=True)

        p1_data = await get_or_migrate_data(interaction.user.id)
        p2_data = await get_or_migrate_data(상대.id)
        p1_pets = [p for p in p1_data.get('pets', []) if p.get('level', 0) > 0]
        p2_pets = [p for p in p2_data.get('pets', []) if p.get('level', 0) > 0]

        if not p1_pets: return await interaction.response.send_message("❌ 배틀에 내보낼 부화한 펫이 없습니다.", ephemeral=True)
        if not p2_pets: return await interaction.response.send_message(f"❌ {상대.display_name}님은 부화한 펫이 없습니다.", ephemeral=True)

        options = [discord.SelectOption(label=f"{p['name']} ({p['type']})", value=str(i)) for i, p in enumerate(p1_pets)]
        select = discord.ui.Select(placeholder="출전시킬 전설이를 선택하세요.", options=options)
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.response.send_message("⚔️ 내보낼 전설이를 선택해주세요.", view=view, ephemeral=True)

        async def p1_callback(inter: discord.Interaction):
            p1_chosen_pet = p1_pets[int(select.values[0])]
            p2_options = [discord.SelectOption(label=f"{p['name']} ({p['type']})", value=str(i)) for i, p in enumerate(p2_pets)]
            p2_select = discord.ui.Select(placeholder="방어에 나설 전설이를 선택하세요.", options=p2_options)
            p2_view = discord.ui.View(timeout=60)
            p2_view.add_item(p2_select)

            await inter.response.edit_message(content=f"✅ {p1_chosen_pet['name']} 출전 대기 완료!", view=None)
            req_msg = await inter.channel.send(f"⚔️ {상대.mention}! {interaction.user.mention}님의 1vs1 배틀 신청이 도착했습니다. 방어할 펫을 고르세요!", view=p2_view)

            async def p2_callback(p2_inter: discord.Interaction):
                if p2_inter.user.id != 상대.id: return await p2_inter.response.send_message("❌ 권한 없음", ephemeral=True)

                # 상호작용 오류 예방을 위해 즉시 봇이 생각 중인 상태로 전환(3초 대기 해제)
                await p2_inter.response.defer()

                p2_chosen_pet = p2_pets[int(p2_select.values[0])]

                # defer 이후이므로 response.edit_message 대신에 부모 메시지를 직접 수정합니다.
                await p2_inter.message.edit(content="✅ 방어 전설이 선택 완료! 배틀을 시작합니다.", view=None)
                await self.run_battle(inter.channel, interaction.user, 상대, [p1_chosen_pet], [p2_chosen_pet], is_5v5=False)
            p2_select.callback = p2_callback
        select.callback = p1_callback

    @app_commands.command(name="배틀5vs5", description="보유한 서로 다른 종류의 전설이 5마리로 총력전을 펼칩니다.")
    async def battle_5v5(self, interaction: discord.Interaction, 상대: discord.Member):
        if interaction.user == 상대 or 상대.bot: return await interaction.response.send_message("❌ 봇/자신 배틀 불가", ephemeral=True)
        if interaction.user.id in self.active_battles or 상대.id in self.active_battles: return await interaction.response.send_message("❌ 다른 배틀 중", ephemeral=True)

        p1_data = await get_or_migrate_data(interaction.user.id)
        p2_data = await get_or_migrate_data(상대.id)

        def get_best_unique_5(pets):
            grown_pets = [p for p in pets if p.get('level', 0) > 0]
            grown_pets.sort(key=lambda p: self.calc_pet_power(p), reverse=True)
            unique_team, seen_types = [], set()
            for p in grown_pets:
                if p['type'] not in seen_types:
                    unique_team.append(p)
                    seen_types.add(p['type'])
                if len(unique_team) == 5: break
            return unique_team

        p1_team = get_best_unique_5(p1_data.get('pets', []))
        p2_team = get_best_unique_5(p2_data.get('pets', []))

        if len(p1_team) < 5: return await interaction.response.send_message("❌ 부화한 서로 다른 종류의 전설이가 5마리 이상 필요합니다.", ephemeral=True)
        if len(p2_team) < 5: return await interaction.response.send_message(f"❌ {상대.display_name}님이 배틀 조건을 충족하지 못했습니다.", ephemeral=True)

        class AcceptView(discord.ui.View):
            def __init__(self, cog):
                super().__init__(timeout=60)
                self.cog = cog

            @discord.ui.button(label="총력전 수락!", style=discord.ButtonStyle.danger, emoji="⚔️")
            async def accept(self, inter: discord.Interaction, button: discord.ui.Button):
                if inter.user.id != 상대.id: return await inter.response.send_message("❌ 권한 없음", ephemeral=True)

                # 상호작용 제한시간(3초) 초기화 처리
                await inter.response.defer()

                await inter.message.edit(content="🔥 배틀이 시작됩니다!", view=None)
                await self.cog.run_battle(inter.channel, interaction.user, 상대, p1_team, p2_team, is_5v5=True)

        await interaction.response.send_message(f"⚔️ {상대.mention}! {interaction.user.mention}님이 5vs5 총력전을 신청했습니다!\n*(규칙: 서로 다른 펫 5마리 출전)*", view=AcceptView(self))

    async def run_battle(self, channel, p1, p2, p1_team, p2_team, is_5v5):
        self.active_battles.add(p1.id); self.active_battles.add(p2.id)
        try:
            p1_power = sum(self.calc_pet_power(p) for p in p1_team)
            p2_power = sum(self.calc_pet_power(p) for p in p2_team)

            battle_title = f"⚔️ {'5vs5 총력전' if is_5v5 else '1vs1 배틀'}: {p1.display_name} VS {p2.display_name} ⚔️"
            total_power = p1_power + p2_power or 1
            p1_win_rate = p1_power / total_power
            winner = p1 if random.random() < p1_win_rate else p2
            p1_won = (winner == p1)

            embed = discord.Embed(title=battle_title, description="🔥 양측 전설이들이 격돌합니다! (결과 계산 중... 15초)\n관전자들은 아래 버튼으로 응원(베팅)하세요!", color=discord.Color.orange())
            embed.add_field(name=f"🔵 {p1.display_name}", value=f"합산 전투력: {p1_power}", inline=True)
            embed.add_field(name="VS", value="⚡", inline=True)
            embed.add_field(name=f"🔴 {p2.display_name}", value=f"합산 전투력: {p2_power}", inline=True)

            bet_view = BetView(p1, p2)
            battle_msg = await channel.send(embed=embed, view=bet_view)

            await asyncio.sleep(15)

            bet_results = []
            for uid, bet_info in bet_view.bets.items():
                member = bet_info['member']
                if bet_info['bet_p1'] == p1_won:
                    await add_item(uid, "서사급 알", 10)
                    bet_results.append(f"🟢 {member.display_name} (서사알 +10)")
                else:
                    epic_amount = await get_item_amount(uid, "서사급 알")
                    if epic_amount >= 10:
                        await consume_item(uid, "서사급 알", 10)
                        bet_results.append(f"🔴 {member.display_name} (서사알 -10)")
                    else:
                        leg_amount = await get_item_amount(uid, "전설급 알")
                        if leg_amount >= 1:
                            await consume_item(uid, "전설급 알", 1)
                            bet_results.append(f"🔴 {member.display_name} (전설알 -1)")
                        else:
                            await set_item_amount(uid, "서사급 알", 0)
                            bet_results.append(f"🔴 {member.display_name} (서사알 전부 파산!)")

            result_embed = discord.Embed(title=battle_title, color=discord.Color.green())
            result_embed.description = f"🎉 치열한 접전 끝에 {winner.mention}님의 승리! (전리품 10P 획득)\n"
            if bet_results: result_embed.add_field(name="📊 베팅 결과", value="\n".join(bet_results), inline=False)

            await add_points(winner.id, 10)
            await battle_msg.edit(embed=result_embed, view=None)

        finally:
            self.active_battles.discard(p1.id); self.active_battles.discard(p2.id)

async def setup(bot):
    await bot.add_cog(BattleCog(bot))