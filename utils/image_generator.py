import io
import asyncio  # 💡 재시도 대기(sleep)를 위해 추가됨
import aiohttp
from PIL import Image, ImageDraw, ImageFont
import discord
import textwrap
from utils.data import PET_IMAGES, EXP_TABLE, PET_STATS, RARITY_IMAGES

# 다운로드한 이미지를 저장해둘 캐시 메모리 딕셔너리 생성 (속도 최적화)
IMAGE_CACHE = {}

async def fetch_image(url):
    """URL에서 이미지를 다운로드하거나, 이미 다운받은 경우 캐시에서 바로 꺼냅니다. (재시도 로직 추가)"""
    if url in IMAGE_CACHE:
        return IMAGE_CACHE[url].copy()

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    # 💡 일시적인 네트워크 오류를 대비해 최대 3번까지 다운로드를 재시도합니다.
    for attempt in range(1, 4):
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        img = Image.open(io.BytesIO(data)).convert("RGBA")
                        IMAGE_CACHE[url] = img
                        return img.copy()
                    else:
                        print(f"⚠️ [시도 {attempt}/3] 이미지 다운로드 실패 (상태 코드 {resp.status}): {url}")
        except Exception as e:
            print(f"⚠️ [시도 {attempt}/3] 이미지 다운로드 에러 발생: {e}")

        # 실패 시 1초 대기 후 재시도 (마지막 시도 제외)
        if attempt < 3:
            await asyncio.sleep(1)

    print(f"❌ [최종 실패] 이미지 로드 실패: {url}")
    return None

def draw_progress_bar(draw, x, y, width, height, progress, bg_color, fill_color):
    """체력바/경험치바 같은 게이지를 그립니다."""
    draw.rectangle([x, y, x + width, y + height], fill=bg_color, outline=(255, 255, 255), width=2)
    fill_width = int(width * (progress / 100))
    if fill_width > 0:
        draw.rectangle([x, y, x + fill_width, y + height], fill=fill_color)

async def generate_status_image(data, points, buffs, is_annoyed, is_diseased, current_idx, total_pets):
    # 1. 1200x700 해상도로 캔버스 강제 고정
    try:
        bg = Image.open("assets/profile_bg.png").convert("RGBA")
        bg = bg.resize((1200, 700))
    except FileNotFoundError:
        bg = Image.new("RGBA", (1200, 700), (30, 30, 40, 255))

    draw = ImageDraw.Draw(bg)

    # 2. 폰트 크기 세팅
    try:
        font_title = ImageFont.truetype("assets/font.ttf", 25)
        font_large = ImageFont.truetype("assets/font.ttf", 40)
        font_medium = ImageFont.truetype("assets/font.ttf", 22)
        font_small = ImageFont.truetype("assets/font.ttf", 15)
    except IOError:
        font_title = font_large = font_medium = font_small = ImageFont.load_default()

    # --- 데이터 추출 ---
    pet_name = data.get('name', '이름없음')
    pet_type = data.get('type', '알 수 없음')
    rarity = data.get('rarity', '서사')
    level = data.get('level', 0)
    current_exp = data.get('exp', 0)
    max_exp = EXP_TABLE.get(rarity, {}).get(level, 100) if level < 3 else 1
    exp_percent = min(100, (current_exp / max_exp) * 100) if level < 3 else 100
    stats = PET_STATS.get(pet_type, {"AD": 0, "DF": 0, "AP": 0, "MR": 0})

    # 깨지는 이모지(특수문자) 제거: 첫 띄어쓰기를 기준으로 뒤쪽 텍스트만 사용
    pet_type_clean = pet_type.split(" ", 1)[-1] if " " in pet_type else pet_type

    # 이름이 길면 ... 으로 자르지 않고, 대신 '의 상태창' 문구를 생략하여 공간 확보
    if len(pet_type_clean) > 8:
        title_text = f"[{rarity}급] {pet_type_clean} ({current_idx + 1}/{total_pets})"
    else:
        title_text = f"[{rarity}급] {pet_type_clean}의 상태창 ({current_idx + 1}/{total_pets})"

    # --- 1. 등급 아이콘 & 상단 제목 ---
    rarity_url = RARITY_IMAGES.get(rarity)
    if rarity_url:
        rarity_img = await fetch_image(rarity_url)
        if rarity_img:
            rarity_img = rarity_img.resize((40, 40))
            bg.paste(rarity_img, (300, 137), rarity_img)
            draw.text((350, 142), title_text, font=font_title, fill=(255, 230, 150), stroke_width=1, stroke_fill="black")
        else:
            draw.text((300, 142), title_text, font=font_title, fill=(255, 230, 150), stroke_width=1, stroke_fill="black")
    else:
        draw.text((300, 142), title_text, font=font_title, fill=(255, 230, 150), stroke_width=1, stroke_fill="black")

    # --- 2. 펫 이름 및 레벨 (말줄임표 없이 전체 출력) ---
    draw.text((500, 197), pet_name, font=font_large, fill=(255, 255, 255), stroke_width=1, stroke_fill="black")
    draw.text((500, 247), f"레벨: {level}성", font=font_medium, fill=(180, 200, 255), stroke_width=1, stroke_fill="black")

    if is_annoyed or is_diseased:
        draw.text((720, 247), "⚠️ 상태 이상 발생!", font=font_medium, fill=(255, 50, 50), stroke_width=1, stroke_fill="black")

    # --- 3. EXP 바 수치화 표기 (겹치지 않게 수정됨) ---
    if level >= 3:
        exp_text = "EXP (MAX)"
    else:
        exp_text = f"EXP ({int(current_exp):,} / {int(max_exp):,})"

    # 텍스트는 위로(y=277), 바는 아래로(y=302), 너비는 355로 늘려 이름과 좌측 정렬되게 맞춤
    draw.text((500, 277), exp_text, font=font_medium, fill=(255, 200, 100), stroke_width=1, stroke_fill="black")
    draw_progress_bar(draw, 500, 302, 355, 15, exp_percent, (50, 50, 50), (255, 150, 50))
    if level >= 3:
        draw.text((865, 302), "MAX", font=font_small, fill=(255, 255, 255), stroke_width=1, stroke_fill="black")

    # --- 4. 스탯 (2x2) ---
    draw.text((500, 327), f"⚔️ AD: {stats.get('AD', 0)}", font=font_medium, fill=(255, 150, 150), stroke_width=1, stroke_fill="black")
    draw.text((680, 327), f"✨ AP: {stats.get('AP', 0)}", font=font_medium, fill=(150, 200, 255), stroke_width=1, stroke_fill="black")
    draw.text((500, 362), f"🛡️ DF: {stats.get('DF', 0)}", font=font_medium, fill=(200, 200, 200), stroke_width=1, stroke_fill="black")
    draw.text((680, 362), f"🌀 MR: {stats.get('MR', 0)}", font=font_medium, fill=(180, 150, 255), stroke_width=1, stroke_fill="black")

    # --- 5. 하단 게이지 4종 수치 표기 (n/100) ---
    # 1열
    draw.text((300, 407), f"🍗 포만도 ({data.get('fullness', 0)}/100)", font=font_small, fill=(255, 255, 255), stroke_width=1, stroke_fill="black")
    draw_progress_bar(draw, 300, 432, 270, 15, data.get('fullness', 0), (50, 50, 50), (255, 100, 100))

    draw.text((580, 407), f"😴 피로도 ({data.get('fatigue', 0)}/100)", font=font_small, fill=(255, 255, 255), stroke_width=1, stroke_fill="black")
    draw_progress_bar(draw, 580, 432, 270, 15, data.get('fatigue', 0), (50, 50, 50), (100, 100, 255))

    # 2열
    draw.text((300, 472), f"🚿 청결도 ({data.get('cleanliness', 0)}/100)", font=font_small, fill=(255, 255, 255), stroke_width=1, stroke_fill="black")
    draw_progress_bar(draw, 300, 497, 270, 15, data.get('cleanliness', 0), (50, 50, 50), (100, 255, 255))

    draw.text((580, 472), f"💖 친밀도 ({data.get('intimacy', 0)}/100)", font=font_small, fill=(255, 255, 255), stroke_width=1, stroke_fill="black")
    draw_progress_bar(draw, 580, 497, 270, 15, data.get('intimacy', 0), (50, 50, 50), (255, 100, 200))

    # --- 6. 하단 텍스트 (포인트 & 버프) ---
    bottom_text = f"보유 포인트 : {points:,} P  |  누적 산책 : {data.get('total_walk_count', 0)} 회"
    draw.text((300, 542), bottom_text, font=font_small, fill=(200, 255, 200), stroke_width=1, stroke_fill="black")

    if buffs:
        buff_str = f"활성화 버프: {', '.join(buffs)}"
        wrapped_buffs = textwrap.fill(buff_str, width=22)
        draw.text((580, 532), wrapped_buffs, font=font_small, fill=(150, 255, 150), stroke_width=1, stroke_fill="black")

    # --- 7. 메인 펫 이미지 (원본 pet_type으로 캐싱 및 다운로드) ---
    pet_url = PET_IMAGES.get(pet_type)
    if pet_url:
        pet_img_downloaded = await fetch_image(pet_url)
        if pet_img_downloaded:
            pet_img_downloaded = pet_img_downloaded.resize((180, 180))
            bg.paste(pet_img_downloaded, (300, 192), pet_img_downloaded)

    # --- 이미지를 discord.File 형태로 변환 ---
    buffer = io.BytesIO()
    bg.save(buffer, format="PNG")
    buffer.seek(0)

    return discord.File(fp=buffer, filename="status.png")