import discord
import io
import time
import random
from datetime import datetime

from utils.database import get_legend_data, save_legend_data, get_active_buffs, consume_item, add_item, update_max_star
from utils.data import ITEMS_INFO, EXP_TABLE, PET_STATS
from utils.logs import WALK_LOG_CH, send_log_embed
from utils.stats import get_points, add_points, spend_points
from utils.image_generator import generate_status_image

def get_pet_stats(pet_type, level):
    base_stats = PET_STATS.get(pet_type, {"AD": 5, "DF": 5, "AP": 5, "MR": 5})
    multiplier = (1.5+max(0, level - 1)) if level > 0 else 1
    return {
        "AD": int(base_stats["AD"] * multiplier),
        "DF": int(base_stats["DF"] * multiplier),
        "AP": int(base_stats["AP"] * multiplier),
        "MR": int(base_stats["MR"] * multiplier)
    }

class LegendActionView(discord.ui.View):
    def __init__(self, user_id, current_idx=0, total_pets=1, pet_level=1):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.current_idx = current_idx
        self.total_pets = total_pets

        if pet_level == 0:
            self.feed.disabled = True
            self.shower.disabled = True
            self.walk_1.disabled = True
            self.walk_10.disabled = True
            self.walk_100.disabled = True

        if self.total_pets <= 1:
            self.prev_btn.disabled = True
            self.next_btn.disabled = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ 남의 전설이 상태창은 조작할 수 없습니다!", ephemeral=True)
            return False
        return True

    async def get_pet_data(self):
        wrapper = await get_legend_data(self.user_id)
        if not wrapper or 'pets' not in wrapper: return None, None
        if self.current_idx >= len(wrapper['pets']): self.current_idx = 0
        return wrapper, wrapper['pets'][self.current_idx]

    async def update_status_message(self, interaction: discord.Interaction, data, popup_msg=None, popup_embed=None):
        current_points = await get_points(self.user_id)
        active_buffs = await get_active_buffs(self.user_id)
        buffs = {b[0] for b in active_buffs}

        now = time.time()
        is_annoyed = (data.get('low_full_since', 0) > 0 and now - data['low_full_since'] >= 86400)
        is_diseased = (data.get('low_clean_since', 0) > 0 and now - data['low_clean_since'] >= 86400)

        pet_level = data.get('level', 0)
        self.feed.disabled = (pet_level == 0)
        self.shower.disabled = (pet_level == 0)
        self.walk_1.disabled = (pet_level == 0)
        self.walk_10.disabled = (pet_level == 0)
        self.walk_100.disabled = (pet_level == 0)

        status_image_file = await generate_status_image(
            data, current_points, buffs, is_annoyed, is_diseased, self.current_idx, self.total_pets
        )

        # defer된 상태이므로 followup을 사용해 팝업 전송
        if popup_embed:
            await interaction.followup.send(embed=popup_embed, ephemeral=True)
        elif popup_msg:
            await interaction.followup.send(popup_msg, ephemeral=True)

        # 원본 메시지의 첨부파일과 뷰 업데이트
        await interaction.message.edit(attachments=[status_image_file], embed=None, view=self)

    @discord.ui.button(label="밥주기 (5P)", style=discord.ButtonStyle.primary, emoji="🍚", row=0)
    async def feed(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer() # 🌟 3초 타임아웃 방지
        wrapper, data = await self.get_pet_data()
        if not data: return await interaction.followup.send("펫 데이터가 없습니다.", ephemeral=True)
        success = await spend_points(self.user_id, 5)
        if not success: return await interaction.followup.send("❌ 밥값(5P)이 부족합니다!", ephemeral=True)
        data['fullness'] = min(100, data.get('fullness', 0) + 20)
        await save_legend_data(self.user_id, wrapper)
        await self.update_status_message(interaction, data, popup_msg=f"🍚 {data['name']}(이)가 맛있게 밥을 먹었습니다! (포만도 +20, 밥값 -5P)")

    @discord.ui.button(label="샤워하기 (10P)", style=discord.ButtonStyle.primary, emoji="🚿", row=0)
    async def shower(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer() # 🌟 3초 타임아웃 방지
        wrapper, data = await self.get_pet_data()
        if not data: return await interaction.followup.send("펫 데이터가 없습니다.", ephemeral=True)
        success = await spend_points(self.user_id, 10)
        if not success: return await interaction.followup.send("❌ 수도세(10P)가 부족합니다!", ephemeral=True)
        data['cleanliness'] = min(100, data.get('cleanliness', 0) + 20)
        await save_legend_data(self.user_id, wrapper)
        await self.update_status_message(interaction, data, popup_msg=f"🚿 {data['name']}(이)가 깨끗해졌습니다! (청결도 +20, 수도세 -10P)")

    async def handle_walk(self, interaction: discord.Interaction, num_walks: int):
        await interaction.response.defer() # 🌟 3초 타임아웃 방지
        wrapper, data = await self.get_pet_data()
        if not data: return await interaction.followup.send("펫 데이터가 없습니다.", ephemeral=True)
        user_id = self.user_id

        if num_walks == 100:
            has_ticket = await consume_item(user_id, "100회 산책 할인권", 1)
            cost = 30 if has_ticket else 100
        else:
            has_ticket = False; cost = num_walks * 1

        success = await spend_points(user_id, cost)
        if not success:
            if has_ticket: await add_item(user_id, "100회 산책 할인권", 1)
            return await interaction.followup.send(f"❌ 산책 유지비({cost}P)가 부족합니다!", ephemeral=True)

        active_buffs = await get_active_buffs(user_id)
        buffs = {b[0] for b in active_buffs}

        data['total_walk_count'] = data.get('total_walk_count', 0) + num_walks
        old_walk_count = data.get('walk_count', 0)
        data['walk_count'] = old_walk_count + num_walks
        stat_triggers = data['walk_count'] // 20
        data['walk_count'] = data['walk_count'] % 20
        stat_msg = ""

        if stat_triggers > 0:
            stat_msg += f"✨ {stat_triggers * 20}회 산책 분량 달성!\n"
            if "신비한 알약" in buffs or "배부름을 부르는 약" in buffs:
                data['fullness'] = 100; stat_msg += "💊 [배부름 약] 효과로 포만도가 100으로 유지되었습니다!\n"
            else: data['fullness'] = max(0, data.get('fullness', 100) - (20 * stat_triggers))

            if "신비한 알약" in buffs or "트위치 나가라약" in buffs:
                data['cleanliness'] = 100; stat_msg += "💊 [나가라 약] 효과로 청결도가 100으로 유지되었습니다!\n"
            else: data['cleanliness'] = max(0, data.get('cleanliness', 100) - (20 * stat_triggers))

            if "신비한 알약" in buffs or "아무무도 인싸로 만드는 약" in buffs:
                data['intimacy'] = 100; stat_msg += "💊 [인싸 약] 효과로 친밀도가 100으로 유지되었습니다!\n"
            else: data['intimacy'] = min(100, data.get('intimacy', 50) + (20 * stat_triggers))

            if "신비한 알약" in buffs or "쌩쌩한약" in buffs:
                data['fatigue'] = 0; stat_msg += "💊 [쌩쌩한약] 효과로 피로도가 0으로 유지되었습니다!\n"
            else: data['fatigue'] = min(100, data.get('fatigue', 0) + (20 * stat_triggers))

        found_eggs = []; found_items = []
        epic_items = [k for k, v in ITEMS_INFO.items() if v['rarity'] == '서사']
        legend_items = [k for k, v in ITEMS_INFO.items() if v['rarity'] == '전설']
        mythic_items = [k for k, v in ITEMS_INFO.items() if v['rarity'] == '신화']
        prestige_items = [k for k, v in ITEMS_INFO.items() if v['rarity'] == '프레스티지']

        for _ in range(num_walks):
            r_egg = random.random()
            if r_egg < 0.0001: found_eggs.append("프레스티지")
            elif r_egg < 0.0021: found_eggs.append("신화")
            elif r_egg < 0.0221: found_eggs.append("전설")
            elif r_egg < 0.1221: found_eggs.append("서사")

            r_item = random.random()
            if r_item < 0.0001 and prestige_items: found_items.append(("프레스티지", random.choice(prestige_items)))
            elif r_item < 0.0005 and mythic_items: found_items.append(("신화", random.choice(mythic_items)))
            elif r_item < 0.0015 and legend_items: found_items.append(("전설", random.choice(legend_items)))
            elif r_item < 0.1015 and epic_items: found_items.append(("서사", random.choice(epic_items)))

        gained_exp = 0
        if 0 < data.get('level', 0) < 3:
            gained_exp = num_walks
            data['exp'] = data.get('exp', 0) + gained_exp
            rarity = data.get('rarity', '서사')
            EXP_REQ = {0: 100, 1: {"서사": 5000, "전설": 10000, "신화": 20000, "프레스티지": 30000}, 2: {"서사": 10000, "전설": 20000, "신화": 40000, "프레스티지": 70000}}

            while data.get('level', 0) < 3:
                curr_level = data.get('level', 0)
                req_exp = EXP_REQ[curr_level].get(rarity, EXP_REQ[curr_level]["서사"])
                if data.get('exp', 0) >= req_exp:
                    data['level'] = curr_level + 1
                    data['exp'] -= req_exp
                else: break

            if data.get('level', 0) >= 3:
                await update_max_star(user_id, 3)

        for egg in found_eggs: await add_item(user_id, f"{egg}급 알", 1)
        for rarity, item_name in found_items: await add_item(user_id, item_name, 1)

        await save_legend_data(self.user_id, wrapper)

        result_embed = discord.Embed(title="🐾 산책 결과", color=discord.Color.green())
        desc = f"{data['name']}(와)과 {num_walks}회 산책했습니다!\n"
        if has_ticket: desc += "🎫 `100회 산책 할인권`이 적용되어 30P만 소모되었습니다.\n"
        else: desc += f"💸 소모된 유지비: -{cost}P\n"
        desc += "━━━━━━━━━━━━━━━━━━━━\n"
        if gained_exp > 0: desc += f"📈 산책을 하며 경험치를 얻었다! (+{gained_exp} XP)\n"
        for egg in found_eggs: desc += f"🥚 {egg}급 알을 발견했다!\n"
        for rarity, item_name in found_items: desc += f"🎁 {rarity}급 아이템 [{item_name}]을 발견했다!\n"
        if stat_msg: desc += f"\n{stat_msg}"

        result_embed.description = desc
        result_embed.set_footer(text=f"사용자 ID: {user_id} | 실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        await self.update_status_message(interaction, data, popup_embed=result_embed)

        log_desc = f"🐾 {data['name']} 산책\n💸 소모 유지비: -{cost}P\n"
        if gained_exp > 0: log_desc += f"📈 획득 경험치: +{gained_exp} XP\n"
        if found_eggs: log_desc += f"🥚 획득한 알: {', '.join(found_eggs)}급 알\n"
        if found_items: log_desc += f"🎁 획득한 아이템: {', '.join([i[1] for i in found_items])}\n"
        await send_log_embed(interaction.client, WALK_LOG_CH, "👟 산책 로그", log_desc.strip(), interaction.user, discord.Color.green(), f"구분: {num_walks}회 산책", guild=interaction.guild)

    @discord.ui.button(label="1회 산책 (1P)", style=discord.ButtonStyle.success, emoji="🚶", row=1)
    async def walk_1(self, interaction: discord.Interaction, button: discord.ui.Button): await self.handle_walk(interaction, 1)

    @discord.ui.button(label="10회 산책 (10P)", style=discord.ButtonStyle.success, emoji="🚶‍♂️", row=1)
    async def walk_10(self, interaction: discord.Interaction, button: discord.ui.Button): await self.handle_walk(interaction, 10)

    @discord.ui.button(label="100회 산책 (100P)", style=discord.ButtonStyle.success, emoji="🏃", row=1)
    async def walk_100(self, interaction: discord.Interaction, button: discord.ui.Button): await self.handle_walk(interaction, 100)

    @discord.ui.button(label="이전 펫", style=discord.ButtonStyle.secondary, emoji="◀️", row=2)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_idx = (self.current_idx - 1) % self.total_pets
        await self._change_pet(interaction)

    @discord.ui.button(label="다음 펫", style=discord.ButtonStyle.secondary, emoji="▶️", row=2)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_idx = (self.current_idx + 1) % self.total_pets
        await self._change_pet(interaction)

    async def _change_pet(self, interaction: discord.Interaction):
        await interaction.response.defer() # 🌟 제일 중요! 여기서 3초 타임아웃을 막아줍니다.
        wrapper = await get_legend_data(self.user_id)
        if not wrapper or not wrapper.get('pets'): return
        wrapper['active_idx'] = self.current_idx
        data = wrapper['pets'][self.current_idx]

        now = time.time()
        active_buffs = await get_active_buffs(self.user_id)
        buffs = {b[0] for b in active_buffs}

        last_calc = data.get('last_fatigue_calc', now)
        elapsed_minutes = int((now - last_calc) // 60)
        if elapsed_minutes > 0 and data.get('level', 0) > 0:
            fatigue_drop = elapsed_minutes * 20
            data['fatigue'] = max(0, data.get('fatigue', 0) - fatigue_drop)
            data['last_fatigue_calc'] = last_calc + (elapsed_minutes * 60)
        elif 'last_fatigue_calc' not in data: data['last_fatigue_calc'] = now

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

        wrapper['pets'][self.current_idx] = data
        await save_legend_data(self.user_id, wrapper)
        await self.update_status_message(interaction, data)