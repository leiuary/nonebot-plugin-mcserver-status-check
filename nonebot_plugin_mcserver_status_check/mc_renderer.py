"""
Minecraft 服务器状态渲染器
==========================

此模块负责将 Minecraft 服务器状态数据（JSON）渲染为图像。
它处理颜色代码解析、MOTD 格式化、图标处理和布局计算。

主要功能：
- 解析 Minecraft 颜色代码 (§a, §b 等) 和 JSON 颜色格式。
- 将 MOTD 渲染为带有正确颜色的文本。
- 生成包含服务器图标、名称、MOTD、玩家数量、版本和延迟的卡片图像。
- 支持自动计算宽度以对齐多个服务器卡片。
"""

import base64
import json
import math
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
from PIL import Image, ImageDraw, ImageFont

# --- 颜色常量 ---
BG_COLOR = (30, 30, 30)
# The card uses 36-pixel text rows, matching Minecraft's 9-unit line height
# rendered at GUI scale 4. Keeping this integral avoids resampling unevenness.
MINECRAFT_GUI_SCALE = 4
MC_COLORS = {
    'black': (0, 0, 0),        'dark_blue': (0, 0, 170),
    'dark_green': (0, 170, 0), 'dark_aqua': (0, 170, 170),
    'dark_red': (170, 0, 0),   'dark_purple': (170, 0, 170),
    'gold': (255, 170, 0),     'gray': (170, 170, 170),
    'dark_gray': (85, 85, 85), 'blue': (85, 85, 255),
    'green': (85, 255, 85),    'aqua': (85, 255, 255),
    'red': (255, 85, 85),      'light_purple': (255, 85, 255),
    'yellow': (255, 255, 85),  'white': (255, 255, 255),
    '0': (0, 0, 0),       '1': (0, 0, 170),     '2': (0, 170, 0),     '3': (0, 170, 170),
    '4': (170, 0, 0),     '5': (170, 0, 170),   '6': (255, 170, 0),   '7': (170, 170, 170),
    '8': (85, 85, 85),    '9': (85, 85, 255),   'a': (85, 255, 85),   'b': (85, 255, 255),
    'c': (255, 85, 85),   'd': (255, 85, 255),  'e': (255, 255, 85),  'f': (255, 255, 255),
}


# --- 辅助函数 ---

def resolve_color(color_obj):
    """将颜色名称或十六进制代码解析为 RGB 元组。"""
    if not color_obj: return (170, 170, 170)
    if isinstance(color_obj, str):
        c = color_obj.lower()
        if c in MC_COLORS: return MC_COLORS[c]
        if c.startswith('#') and len(c) == 7:
            try: return tuple(int(c[i:i+2], 16) for i in (1, 3, 5))
            except: pass
    return (170, 170, 170)

def parse_inner_legacy(text, start_color, start_bold=False):
    """解析字符串中的旧版 Minecraft 颜色代码和粗体代码。"""
    if not text: return []
    if '§' not in text: return [(text, start_color, start_bold)]
    result = []
    buffer = ""
    current_color = start_color
    current_bold = start_bold
    i = 0
    while i < len(text):
        if text[i] == '§' and i + 1 < len(text):
            if buffer:
                result.append((buffer, current_color, current_bold))
                buffer = ""
            code = text[i+1].lower()
            if code in MC_COLORS:
                current_color = MC_COLORS[code]
                current_bold = False
            elif code == 'l': current_bold = True
            elif code == 'r':
                current_color = (170, 170, 170)
                current_bold = False
            i += 2
        else:
            buffer += text[i]
            i += 1
    if buffer: result.append((buffer, current_color, current_bold))
    return result

def strip_mc_codes(text):
    """从文本中移除所有 Minecraft 颜色代码 (§a)。"""
    if not text: return ""
    if '§' not in text: return text
    result = ""
    i = 0
    while i < len(text):
        if text[i] == '§' and i + 1 < len(text):
            i += 2
        else:
            result += text[i]
            i += 1
    return result

def flatten_json_motd(data, inherited_color='gray', inherited_bold=False):
    """将分层的 JSON MOTD 结构展平为 (文本, 颜色, 粗体) 段列表。"""
    result = []
    text = ""
    if isinstance(data, dict):
        text = data.get('text', "")
        color_name = data.get('color', inherited_color)
        bold = data.get('bold', inherited_bold)
    elif isinstance(data, str):
        text = data
        color_name = inherited_color
        bold = inherited_bold
    else:
        return []
    base_rgb = resolve_color(color_name)
    if text: result.extend(parse_inner_legacy(text, base_rgb, bold))
    if isinstance(data, dict) and 'extra' in data:
        for item in data['extra']:
            result.extend(flatten_json_motd(item, color_name, bold))
    return result


def _iter_codepoints(text):
    """Iterate Unicode code points, combining surrogate pairs from JSON."""
    index = 0
    while index < len(text):
        first = ord(text[index])
        if 0xD800 <= first <= 0xDBFF and index + 1 < len(text):
            second = ord(text[index + 1])
            if 0xDC00 <= second <= 0xDFFF:
                yield chr(0x10000 + ((first - 0xD800) << 10) + second - 0xDC00)
                index += 2
                continue
        yield text[index]
        index += 1


@lru_cache(maxsize=1)
def _vanilla_unifont_size_overrides():
    """Read the size ranges from Minecraft's Unifont provider definition."""
    data = json.loads(
        Path(__file__).with_name("vanilla_unifont.json").read_text(encoding="utf-8")
    )
    provider = next(item for item in data["providers"] if not item.get("filter"))
    return tuple(
        (ord(entry["from"]), ord(entry["to"]), entry["left"], entry["right"])
        for entry in provider.get("size_overrides", [])
    )


_VANILLA_UNIFONT_CACHE = {}
_VANILLA_UNIFONT_MISSING = set()


def _load_vanilla_unifont_glyphs(codepoints):
    """Read requested glyphs from the game's bundled Unifont hex archive."""
    needed = {
        codepoint for codepoint in codepoints
        if codepoint not in _VANILLA_UNIFONT_CACHE
        and codepoint not in _VANILLA_UNIFONT_MISSING
    }
    if not needed:
        return

    package_dir = Path(__file__).parent
    overrides = _vanilla_unifont_size_overrides()
    font_archive = package_dir / "vanilla_unifont.zip"
    with ZipFile(font_archive) as archive:
        hex_name = next(name for name in archive.namelist() if name.endswith(".hex"))
        with archive.open(hex_name) as glyph_stream:
            for line in glyph_stream:
                code_text, bitmap_bytes = line.rstrip().split(b":", 1)
                codepoint = int(code_text, 16)
                if codepoint in needed:
                    bitmap = bitmap_bytes.decode("ascii")
                    hex_digits_per_row = len(bitmap) // 16
                    bit_width = hex_digits_per_row * 4
                    left, right = 0, bit_width - 1
                    for range_start, range_end, range_left, range_right in overrides:
                        if range_start <= codepoint <= range_end:
                            left, right = range_left, range_right
                            break
                    glyph_width = right - left + 1
                    pixels = Image.new("L", (glyph_width, 16), 0)
                    for y in range(16):
                        row_start = y * hex_digits_per_row
                        row = int(bitmap[row_start:row_start + hex_digits_per_row], 16)
                        for x in range(glyph_width):
                            source_column = left + x
                            if source_column >= bit_width:
                                continue
                            bit_index = bit_width - 1 - source_column
                            if row & (1 << bit_index):
                                pixels.putpixel((x, y), 255)
                    _VANILLA_UNIFONT_CACHE[codepoint] = {
                        "mask": pixels,
                        "pixel_scale": 0.5,
                        "advance": glyph_width // 2 + 1,
                        "bold_offset": 0.5,
                        "shadow_offset": 0.5,
                    }
                    needed.remove(codepoint)
                    if not needed:
                        break
    _VANILLA_UNIFONT_MISSING.update(needed)


def _vanilla_glyphs_for_text(text):
    """Resolve glyphs with the game's uniform font (forceUnicodeFont=true)."""
    codepoints = [ord(character) for character in _iter_codepoints(text)]
    _load_vanilla_unifont_glyphs(
        codepoint for codepoint in codepoints
        if codepoint not in (ord(" "), 0x200C)
    )
    _load_vanilla_unifont_glyphs((0xFFFD,))
    replacement = _VANILLA_UNIFONT_CACHE.get(0xFFFD)
    return {
        codepoint: _VANILLA_UNIFONT_CACHE.get(codepoint) or replacement
        for codepoint in codepoints
    }


def _draw_vanilla_glyph(draw, x, y, glyph, color, scale, bold=False):
    """Draw a default Minecraft font glyph with native bold/shadow geometry."""
    shadow_color = tuple(channel // 4 for channel in color)
    shadow_offset = glyph["shadow_offset"] * scale
    bold_offset = (glyph["bold_offset"] * scale) if bold else 0
    pixel_scale = glyph["pixel_scale"] * scale
    thickness = (0.1 * scale) if bold else 0
    source_mask = glyph["mask"]

    def draw_instance(origin_x, origin_y, instance_color):
        glyph_x0 = math.floor(origin_x - thickness)
        glyph_y0 = math.floor(origin_y - thickness)
        glyph_width = source_mask.width * pixel_scale + 2 * thickness
        glyph_height = source_mask.height * pixel_scale + 2 * thickness
        glyph_x1 = math.ceil(origin_x + source_mask.width * pixel_scale + thickness)
        glyph_y1 = math.ceil(origin_y + source_mask.height * pixel_scale + thickness)
        pixel_scale_x = glyph_width / source_mask.width
        pixel_scale_y = glyph_height / source_mask.height
        mask = Image.new("L", (glyph_x1 - glyph_x0, glyph_y1 - glyph_y0), 0)
        mask_pixels = mask.load()
        source_pixels = source_mask.load()
        for target_y in range(glyph_y0, glyph_y1):
            source_y = math.floor((target_y + 0.5 - (origin_y - thickness)) / pixel_scale_y)
            if not 0 <= source_y < source_mask.height:
                continue
            for target_x in range(glyph_x0, glyph_x1):
                source_x = math.floor((target_x + 0.5 - (origin_x - thickness)) / pixel_scale_x)
                if 0 <= source_x < source_mask.width:
                    mask_pixels[target_x - glyph_x0, target_y - glyph_y0] = source_pixels[source_x, source_y]
        draw.bitmap((glyph_x0, glyph_y0), mask, fill=instance_color)

    draw_instance(x + shadow_offset, y + shadow_offset, shadow_color)
    if bold:
        draw_instance(x + bold_offset + shadow_offset, y + shadow_offset, shadow_color)
    draw_instance(x, y, color)
    if bold:
        draw_instance(x + bold_offset, y, color)
    return glyph["advance"] + (glyph["bold_offset"] if bold else 0)


def _vanilla_render_scale(scale):
    """Return the integer GUI scale used to rasterize Minecraft's glyph atlas."""
    return MINECRAFT_GUI_SCALE if scale is None else scale


def _vanilla_glyph_advance(character, glyph, bold, scale):
    if character == " ":
        return (4 + (1 if bold else 0)) * scale
    if character == "\u200c":
        return (1 if bold else 0) * scale
    if glyph is None:
        return None
    return (glyph["advance"] + (glyph["bold_offset"] if bold else 0)) * scale


def draw_text_with_shadow(draw, pos, text, color, font, bold=False, scale=None):
    """绘制带有阴影效果的文本。"""
    x, y = pos
    start_x = x
    vanilla_glyphs = _vanilla_glyphs_for_text(text)
    vanilla_scale = _vanilla_render_scale(scale)
    for character in _iter_codepoints(text):
        codepoint = ord(character)
        vanilla_glyph = vanilla_glyphs.get(codepoint)
        vanilla_advance = _vanilla_glyph_advance(
            character, vanilla_glyph, bold, vanilla_scale
        )
        if vanilla_advance is not None:
            if character not in (" ", "\u200c") and vanilla_glyph is not None:
                _draw_vanilla_glyph(
                    draw, x, y, vanilla_glyph, color, vanilla_scale, bold
                )
            x += vanilla_advance
            continue
    return x - start_x

def measure_text_width(text, draw, font, bold=False, scale=None):
    """按字形计算文本宽度，并计入 Minecraft 粗体字形偏移。"""
    vanilla_glyphs = _vanilla_glyphs_for_text(text)
    vanilla_scale = _vanilla_render_scale(scale)
    width = 0
    for character in _iter_codepoints(text):
        vanilla_glyph = vanilla_glyphs.get(ord(character))
        vanilla_advance = _vanilla_glyph_advance(
            character, vanilla_glyph, bold, vanilla_scale
        )
        if vanilla_advance is not None:
            width += vanilla_advance
    return width

def measure_segments_width(segments, draw, font, scale=None):
    """测量一系列文本段的总宽度。"""
    return sum(measure_text_width(text, draw, font, bold, scale)
               for text, _, bold in segments)


def extract_render_data(server_addr, status, alias=None):
    """
    从状态对象中提取并预处理渲染所需的数据。
    
    参数:
        server_addr (str): 服务器地址字符串。
        status (MixedStatus): 包含原始 JSON 响应和延迟数据的状态对象。
        alias (str, optional): 服务器别名。
        
    返回:
        dict: 包含结构化渲染数据的字典，包括左侧文本、右侧统计信息和图标数据。
    """
    raw = status.raw
    
    # --- 提取右侧统计数据 (在线人数, 版本, 延迟) ---
    players = raw.get("players", {})
    online, max_p = players.get('online', 0), players.get('max', 0)
    txt_players = f"{online}/{max_p}"
    # 在线且有延迟数据时显示绿色，否则显示灰色
    color_players = (85, 255, 85) if (online > 0 and status.latency >= 0) else (170, 170, 170)
    
    txt_version = "Unknown"
    if "version" in raw:
        v = raw["version"]
        if isinstance(v, dict): txt_version = v.get("name", "Unknown")
        elif isinstance(v, str): txt_version = v
    elif hasattr(status, 'version') and status.version:
        txt_version = status.version.name
    
    # 移除版本字符串中的颜色代码以保持整洁
    txt_version = strip_mc_codes(txt_version)
    
    lat = status.latency if hasattr(status, 'latency') else -1
    fail_count = getattr(status, 'fail_count', 0)
    
    txt_ping = f"{int(lat)}ms"
    if fail_count > 0:
        txt_ping = f"Loss:{fail_count} {txt_ping}"

    if lat < 0: color_ping = (170, 170, 170)      # 离线/未知
    elif lat < 150: color_ping = (85, 255, 85)    # 良好 (绿色)
    elif lat < 300: color_ping = (255, 170, 0)    # 一般 (金色)
    else: color_ping = (170, 0, 0)                # 较差 (红色)

    # --- 提取左侧文本数据 (服务器标题, MOTD) ---
    desc_data = raw.get("description", "")
    motd_parts = flatten_json_motd(desc_data)
    motd_lines = [[]]
    for text, color, bold in motd_parts:
        if not text: continue
        segs = text.split('\n')
        for i, seg in enumerate(segs):
            if i > 0: motd_lines.append([])
            if seg: motd_lines[-1].append((seg, color, bold))
    
    # 仅保留前两行 MOTD
    line1 = motd_lines[0] if len(motd_lines) > 0 else []
    line2 = motd_lines[1] if len(motd_lines) > 1 else []
    
    title_text = server_addr
    if alias:
        title_text = f"{alias} ({server_addr})"

    return {
        "right": {
            "p_txt": txt_players, "p_col": color_players,
            "v_txt": txt_version, "v_col": (170, 170, 170),
            "ping_txt": txt_ping, "ping_col": color_ping
        },
        "left": {
            "title": title_text,
            "line1": line1,
            "line2": line2
        },
        "favicon": raw.get("favicon")
    }

def calculate_required_width(server_addr, status, font_path="minecraft.ttf", alias=None):
    """
    计算渲染该服务器卡片所需的最小宽度。
    此函数用于在批量渲染前确定全局统一的宽度，以确保对齐。
    """
    data = extract_render_data(server_addr, status, alias)
    
    # 创建临时画布用于测量文本宽度
    temp_draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    try:
        font_title = ImageFont.truetype(font_path, 30) 
        font_desc = ImageFont.truetype(font_path, 26)  
        font_info = ImageFont.truetype(font_path, 26)  
    except:
        font_title = ImageFont.load_default()
        font_desc = ImageFont.load_default()
        font_info = ImageFont.load_default()

    # 计算右侧统计信息区域宽度 (取最大值)
    r = data["right"]
    w_p = measure_text_width(r["p_txt"], temp_draw, font_info)
    w_v = measure_text_width(r["v_txt"], temp_draw, font_info)
    w_ping = measure_text_width(r["ping_txt"], temp_draw, font_info)
    max_stats_w = max(w_p, w_v, w_ping) + 10

    # 计算左侧文本区域宽度 (标题和 MOTD)
    l = data["left"]
    w_title = measure_text_width(l["title"], temp_draw, font_title)
    w_m1 = measure_segments_width(l["line1"], temp_draw, font_desc)
    w_m2 = measure_segments_width(l["line2"], temp_draw, font_desc)
    max_text_w = max(w_title, w_m1, w_m2)
    
    GAP = 40     # 左右内容区域之间的间隙
    PADDING = 40 # 左右两侧的总边距
    
    return int(max_text_w + GAP + max_stats_w + PADDING)

def generate_server_card(server_addr, status, fixed_width=None, font_path="minecraft.ttf", alias=None):
    """
    生成单个服务器的状态卡片图像。
    
    参数:
        server_addr (str): 服务器地址。
        status (MixedStatus): 状态对象。
        fixed_width (int, optional): 指定图像宽度。若为 None，则自动计算最小宽度。
        font_path (str, optional): 字体文件路径。
        alias (str, optional): 服务器别名。
        
    返回:
        tuple: (icon_image, info_image) - 返回包含图标和信息卡片的元组。
    """
    # 1. 基础配置与数据提取
    FIXED_HEIGHT = 128
    data = extract_render_data(server_addr, status, alias)
    
    # 2. 生成服务器图标
    ICON_SIZE = 128
    icon_img = None
    if data["favicon"] and "," in data["favicon"]:
        try:
            b64 = data["favicon"].split(",", 1)[1]
            real_icon = Image.open(BytesIO(base64.b64decode(b64))).resize((ICON_SIZE, ICON_SIZE), Image.Resampling.NEAREST)
            if real_icon.mode != 'RGB': real_icon = real_icon.convert('RGB')
            icon_img = real_icon
        except: icon_img = None
    if icon_img is None:
        default_icon_path = Path(__file__).with_name("unknown_server.png")
        with Image.open(default_icon_path) as default_icon:
            icon_img = default_icon.convert('RGB').resize((ICON_SIZE, ICON_SIZE), Image.Resampling.NEAREST)

    # 3. 确定图像宽度
    # 若未指定固定宽度，则自动计算所需的最小宽度，并确保不小于 800px
    if fixed_width:
        TOTAL_WIDTH = fixed_width
    else:
        TOTAL_WIDTH = calculate_required_width(server_addr, status, font_path, alias)
        TOTAL_WIDTH = max(TOTAL_WIDTH, 800)

    # 4. 创建信息卡片画布
    info_img = Image.new('RGB', (TOTAL_WIDTH, FIXED_HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(info_img)
    
    try:
        font_title = ImageFont.truetype(font_path, 30) 
        font_desc = ImageFont.truetype(font_path, 26)  
        font_info = ImageFont.truetype(font_path, 26)  
    except:
        font_title = ImageFont.load_default()
        font_desc = ImageFont.load_default()
        font_info = ImageFont.load_default()

    LINE_HEIGHT = 36
    START_Y = (FIXED_HEIGHT - (LINE_HEIGHT * 3)) // 2
    Y1, Y2, Y3 = START_Y - 2, START_Y + LINE_HEIGHT, START_Y + LINE_HEIGHT * 2
    
    PADDING_LEFT = 20
    PADDING_RIGHT = 20
    
    # 5. 绘制右侧统计信息 (始终右对齐)
    ALIGN_X = TOTAL_WIDTH - PADDING_RIGHT
    r = data["right"]
    
    w_p = measure_text_width(r["p_txt"], draw, font_info)
    draw_text_with_shadow(draw, (ALIGN_X - w_p, Y1), r["p_txt"], r["p_col"], font_info)
    
    w_v = measure_text_width(r["v_txt"], draw, font_info)
    draw_text_with_shadow(draw, (ALIGN_X - w_v, Y2), r["v_txt"], r["v_col"], font_info)
    
    w_ping = measure_text_width(r["ping_txt"], draw, font_info)
    draw_text_with_shadow(draw, (ALIGN_X - w_ping, Y3), r["ping_txt"], r["ping_col"], font_info)
    
    # 6. 绘制左侧文本信息 (标题和 MOTD)
    l = data["left"]
    TEXT_X = PADDING_LEFT
    
    draw_text_with_shadow(draw, (TEXT_X, Y1), l["title"], (255, 255, 255), font_title)
    
    curr_x = TEXT_X
    for t, c, bold in l["line1"]:
        curr_x += draw_text_with_shadow(draw, (curr_x, Y2), t, c, font_desc, bold)
        
    curr_x = TEXT_X
    for t, c, bold in l["line2"]:
        curr_x += draw_text_with_shadow(draw, (curr_x, Y3), t, c, font_desc, bold)

    return icon_img, info_img
