import discord
from utils.database import get_legend_data, get_or_migrate_data, save_legend_data, consume_item, add_buff, get_active_buffs
from utils.data import ITEMS_INFO
from utils.logs import ITEM_USE_LOG_CH, send_log_embed
from utils.stats import add_points

class NameChangeModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="전설이 이름 변경")
        self.new_name = discord.ui.TextInput(label="새로운 전설이의 이름을 입력하세요", placeholder="예: 멍멍이", min_length=1, max_length=20, required=True)
        self.add_item(self.new_name)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        wrapper = await get_or_migrate_data(user_id)
        if not wrapper.get('pets'): return await interaction.response.send_message("❌ 아직 돌보고 있는 전설이가 없습니다.", ephemeral=True)
        success = await consume_item(user_id, "전설이 이름 변경권", 1)
        if not success: return await interaction.response.send_message("❌ '전설이 이름 변경권' 아이템이 부족합니다.", ephemeral=True)
        data = wrapper['pets'][wrapper['active_idx']]
        old_name = data.get('name', '이름없음')
        data['name'] = self.new_name.value
        await save_legend_data(user_id, wrapper)
        await interaction.response.send_message(f"✨ 뾰로롱! 전설이의 이름이 `{old_name}`에서 `{self.new_name.value}`(으)로 변경되었습니다!", ephemeral=True)

class ItemQuantityModal(discord.ui.Modal):
    def __init__(self, item_name: str, max_amount: int):
        self.item_name = item_name
        self.max_amount = max_amount
        super().__init__(title=f"{item_name} 사용")
        self.amount_input = discord.ui.TextInput(label=f"수량을 입력하세요 (보유량: {max_amount}개)", placeholder=f"1 ~ {max_amount} 사이의 숫자를 입력", min_length=1, max_length=5, required=True)
        self.add_item(self.amount_input)

    async def on_submit(self, interaction: discord.Interaction):
        try: amount = int(self.amount_input.value)
        except ValueError: return await interaction.response.send_message("❌ 올바른 숫자를 입력해주세요.", ephemeral=True)
        if amount <= 0 or amount > self.max_amount:
            return await interaction.response.send_message(f"❌ 보유하신 수량(1~{self.max_amount}개) 내에서 입력해주세요.", ephemeral=True)
        user_id = interaction.user.id
        await self.handle_use(interaction, user_id, amount)

    async def handle_use(self, interaction: discord.Interaction, user_id: int, amount: int):
        item_name = self.item_name

        # 청결도 100% 조건문 전면 삭제 처리
        if "경험치 부스터" in item_name:
            active_buffs = await get_active_buffs(user_id)
            buffs = {b[0] for b in active_buffs}

            # 경험치 부스터 종류가 버프 목록에 하나라도 존재하면 중복 실행 방지
            if any("경험치 부스터" in b for b in buffs):
                return await interaction.response.send_message("❌ 이미 적용 중인 경험치 부스터가 있습니다! 기존 부스터 효과가 끝난 후 사용해주세요.", ephemeral=True)

        success = await consume_item(user_id, item_name, amount)
        if not success: return await interaction.response.send_message("❌ 아이템을 보유하고 있지 않거나 부족합니다.", ephemeral=True)

        msg = f"✅ `{item_name}` {amount}개를 사용했습니다!\n"
        if item_name in ["배부름을 부르는 약", "쌩쌩한약", "트위치 나가라약", "아무무도 인싸로 만드는 약"]:
            await add_buff(user_id, buff_name=item_name, duration_sec=86400 * amount, vc_sec=0)
            msg += f"✨ 효과: {24 * amount}시간 동안 해당 스탯이 고정됩니다."
        elif item_name == "신비한 알약":
            await add_buff(user_id, buff_name=item_name, duration_sec=1209600 * amount, vc_sec=0)
            msg += f"✨ 효과: {14 * amount}일 동안 모든 스탯이 최상으로 고정됩니다."
        elif item_name in ["경험치 부스터 X2", "경험치 부스터 X5", "경험치 부스터 X10"]:
            await add_buff(user_id, buff_name=item_name, duration_sec=0, vc_sec=10800 * amount)
            msg += f"📈 효과: 통화방에 있는 동안 {3 * amount}시간 동안 경험치 획득량이 증가합니다."

        await interaction.response.send_message(msg, ephemeral=True)
        await send_log_embed(interaction.client, ITEM_USE_LOG_CH, "🎒 아이템 다중 사용 로그", f"사용 아이템: {item_name} x {amount}개", interaction.user, discord.Color.blue())

class InventoryView(discord.ui.View):
    def __init__(self, user_id, items):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.items = items
        self.selected_item = None
        options = [discord.SelectOption(label=name, description=f"보유량: {amt}개") for name, amt in list(items.items())[:25]]
        self.select_menu = discord.ui.Select(placeholder="여기를 눌러 조작할 아이템/알을 선택하세요", options=options)
        self.select_menu.callback = self.on_select
        self.add_item(self.select_menu)
        self.use_btn = discord.ui.Button(label="사용하기", style=discord.ButtonStyle.success, emoji="✨", disabled=True)
        self.use_btn.callback = self.on_use_click
        self.add_item(self.use_btn)

    async def on_select(self, interaction: discord.Interaction):
        self.selected_item = self.select_menu.values[0]
        self.use_btn.disabled = False
        await interaction.response.edit_message(view=self)

    async def on_use_click(self, interaction: discord.Interaction):
        if self.selected_item == "100회 산책 할인권":
            return await interaction.response.send_message("💡 이 아이템은 100회 산책 시 자동으로 사용됩니다!", ephemeral=True)
        elif self.selected_item == "전설이 이름 변경권":
            modal = NameChangeModal()
            return await interaction.response.send_modal(modal)
        elif "급 알" in self.selected_item:
            success = await consume_item(self.user_id, self.selected_item, 1)
            if not success: return await interaction.response.send_message("❌ 알이 부족합니다.", ephemeral=True)
            app_info = await interaction.client.application_info()
            try: await app_info.owner.send(f"🚨 알림: {interaction.user.display_name}님이 보관함에서 `{self.selected_item}`을(를) 사용했습니다!")
            except Exception as e: print(f"DM 전송 실패: {e}")
            return await interaction.response.send_message("✅ 봇 관리자에게 DM을 보냈습니다. (해당 알 1개 소모됨)", ephemeral=True)

        modal = ItemQuantityModal(self.selected_item, self.items[self.selected_item])
        await interaction.response.send_modal(modal)