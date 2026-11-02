"""A lightweight Pillow renderer for Minecraft's multiplayer list."""

from __future__ import annotations

import base64
import binascii
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageDraw, ImageFont

from .mc_renderer import BG_COLOR, MC_COLORS, parse_inner_legacy, resolve_color
from .minecraft_font import FONT, MinecraftFont


ASSET_DIR = Path(__file__).with_name("assets") / "vanilla26"
DEFAULT_ICON_PATH = Path(__file__).with_name("unknown_server.png")
ROW_WIDTH = 323
ROW_HEIGHT = 32
DEFAULT_TEXT = (128, 128, 128)
VERSION_TEXT = (170, 170, 170)
TITLE_TEXT = "Minecraft Server Status"
TITLE_FONT_SIZE = 48
TITLE_HEADER_HEIGHT = 100
FOOTER_TEXT_TEMPLATE = "{time}  |  Made by leiuary"


def render_server_list_image(
    rows: list[dict[str, Any]],
    width: int = 1330,
    height: int = 750,
    gui_scale: int = 4,
    force_unicode_font: bool = False,
    font_path: Optional[str] = None,
) -> Image.Image:
    """Render a static multiplayer-list frame from already queried statuses."""
    width = max(320, int(width))
    height = max(240, int(height))
    scale = max(1, int(gui_scale))
    font = FONT if force_unicode_font else MinecraftFont(force_unicode_font=False)
    font_path = font_path or str(Path(__file__).with_name("minecraft.ttf"))

    row_width = ROW_WIDTH * scale
    row_height = ROW_HEIGHT * scale
    row_left = (width - row_width + 9 * scale) // 2
    first_row_y = TITLE_HEADER_HEIGHT
    row_layout = []
    row_y = first_row_y
    for row in rows:
        player_image = _render_player_list_v01(
            row.get("player_samples", []), row_width, font_path
        )
        row_layout.append((row, row_y, player_image))
        player_height = player_image.height if player_image is not None else 0
        row_y += row_height + player_height + 10

    content_bottom = (
        row_y - 10 if row_layout else first_row_y
    )
    height = max(240, content_bottom + 50) if row_layout else max(height, 240)

    image = Image.new("RGB", (width, height), BG_COLOR)
    _draw_title(image, font_path)
    for row, row_y, player_image in row_layout:
        _draw_server_row(image, row, row_left, row_y, row_width, row_height, scale, font)
        if player_image is not None:
            image.paste(player_image, (row_left, row_y + row_height))

    _draw_footer(image, font_path)
    return image


def _render_player_list_v01(
    players: Any, width: int, font_path: str
) -> Optional[Image.Image]:
    if not isinstance(players, list):
        return None
    names = [
        str(player.get("name") or "Unknown").replace("&", "§")
        for player in players
        if isinstance(player, dict)
    ]
    if not names:
        return None

    try:
        font = ImageFont.truetype(font_path, 20)
    except OSError:
        font = ImageFont.load_default()
    dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    is_message_list = any(
        "§" in name or " " in name or any(ord(character) > 127 for character in name)
        for name in names
    )
    lines: list[list[str]] = []
    if is_message_list:
        lines = [[name] for name in names]
    else:
        current_line: list[str] = []
        current_width = 0.0
        max_width = width - 40
        for name in names:
            clean_name = name
            for digit in "0123456789":
                clean_name = clean_name.replace(f"§{digit}", "")
            for code in "abcdefklmnor":
                clean_name = clean_name.replace(f"§{code}", "")
            name_width = dummy.textlength(clean_name + ", ", font=font)
            if current_width + name_width > max_width and current_line:
                lines.append(current_line)
                current_line = [name]
                current_width = name_width
            else:
                current_line.append(name)
                current_width += name_width
        if current_line:
            lines.append(current_line)

    image = Image.new("RGB", (width, len(lines) * 24 + 20), BG_COLOR)
    draw = ImageDraw.Draw(image)
    y = 10
    for line in lines:
        x = 20
        for index, name in enumerate(line):
            separator = ", " if not is_message_list and index < len(line) - 1 else ""
            for text, color, *_ in parse_inner_legacy(name + separator, (200, 200, 200)):
                draw.text((x, y), text, fill=color, font=font)
                x += dummy.textlength(text, font=font)
        y += 24
    return image


def _draw_title(image: Image.Image, font_path: str) -> None:
    draw = ImageDraw.Draw(image)
    try:
        title_font = ImageFont.truetype(font_path, TITLE_FONT_SIZE)
    except OSError:
        title_font = ImageFont.load_default()
    title_width = draw.textlength(TITLE_TEXT, font=title_font)
    x = int((image.width - title_width) // 2)
    y = (TITLE_HEADER_HEIGHT - TITLE_FONT_SIZE) // 2
    draw.text((x, y), TITLE_TEXT, fill=(255, 255, 255), font=title_font)


def _draw_footer(image: Image.Image, font_path: str) -> None:
    footer = FOOTER_TEXT_TEMPLATE.format(time=time.strftime("%Y-%m-%d %H:%M:%S"))
    draw = ImageDraw.Draw(image)
    try:
        footer_font = ImageFont.truetype(font_path, 24)
    except OSError:
        footer_font = ImageFont.load_default()
    footer_width = draw.textlength(footer, font=footer_font)
    x = int(image.width - footer_width - 20)
    y = image.height - 30
    draw.text((x, y), footer, fill=(150, 150, 150), font=footer_font)


def _draw_server_row(
    image: Image.Image,
    row: dict[str, Any],
    left: int,
    top: int,
    width: int,
    height: int,
    scale: int,
    font: MinecraftFont,
) -> None:
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    status = row["status_obj"]
    raw = getattr(status, "raw", {}) or {}
    address = str(row.get("address") or "").strip()
    label = str(row.get("alias") or row.get("name") or "").strip()
    if address and label and label.casefold() != address.casefold():
        name = f"{label} ({address})"
    else:
        name = label or address

    icon = _server_icon(raw.get("favicon"))
    icon = icon.resize((32 * scale, 32 * scale), Image.Resampling.NEAREST)
    layer.alpha_composite(icon, (0, 0))

    text_x = 35 * scale
    status_text, status_color, ping_sprite = _status_display(status, raw)
    status_icon_x = width - 19 * scale
    status_icon_y = 0
    status_text_right = status_icon_x - 5 * scale
    detail_text_right = status_icon_x + 10 * scale
    version_text = _server_version(raw)
    latency_text, latency_color = _latency_display(status)
    detail_width = max(font.measure(version_text), font.measure(latency_text)) * scale
    motd_width = min(
        ROW_WIDTH - 34,
        max(0, (detail_text_right - detail_width - text_x - 2 * scale) // scale),
    )
    font.draw(draw, (text_x, scale), name, (255, 255, 255), scale, shadow=True)

    motd = _component_segments(raw.get("description", ""), DEFAULT_TEXT)
    lines = _wrap_segments(motd, motd_width, font)
    for line_index, segments in enumerate(lines[:2]):
        y = (12 + line_index * 9) * scale
        x = text_x
        for segment in segments:
            x += font.draw(
                draw,
                (x, y),
                segment["text"],
                segment["color"],
                scale,
                bold=segment["bold"],
                italic=segment["italic"],
                underline=segment["underline"],
                strikethrough=segment["strikethrough"],
                shadow=True,
            )

    for text, text_y, color, text_right in (
        (status_text, scale, status_color, status_text_right),
        (version_text, 10 * scale, VERSION_TEXT, detail_text_right),
        (latency_text, 19 * scale, latency_color, detail_text_right),
    ):
        text_width = font.measure(text) * scale
        text_x = text_right - int(round(text_width))
        font.draw(draw, (text_x, text_y), text, color, scale, shadow=True)

    sprite_path = ASSET_DIR / "server_list" / f"{ping_sprite}.png"
    with Image.open(sprite_path) as sprite:
        icon_sprite = sprite.convert("RGBA").resize(
            (10 * scale, 8 * scale), Image.Resampling.NEAREST
        )
    layer.alpha_composite(icon_sprite, (status_icon_x, status_icon_y))
    image.paste(layer, (left, top), layer.getchannel("A"))


def _status_display(status: Any, raw: dict[str, Any]) -> tuple[str, tuple[int, int, int], str]:
    players = raw.get("players") or {}
    status_text = f"{players.get('online', 0)}/{players.get('max', 0)}"
    latency = float(getattr(status, "latency", -1))
    if latency < 0:
        sprite = "unreachable"
        color = DEFAULT_TEXT
    elif latency < 150:
        sprite = "ping_5"
        color = (85, 255, 85) if players.get("online", 0) > 0 else DEFAULT_TEXT
    elif latency < 300:
        sprite = "ping_4"
        color = (85, 255, 85) if players.get("online", 0) > 0 else DEFAULT_TEXT
    elif latency < 600:
        sprite = "ping_3"
        color = (85, 255, 85) if players.get("online", 0) > 0 else DEFAULT_TEXT
    elif latency < 1000:
        sprite = "ping_2"
        color = (85, 255, 85) if players.get("online", 0) > 0 else DEFAULT_TEXT
    else:
        sprite = "ping_1"
        color = (85, 255, 85) if players.get("online", 0) > 0 else DEFAULT_TEXT
    return status_text, color, sprite


def _server_version(raw: dict[str, Any]) -> str:
    version = raw.get("version") or {}
    if isinstance(version, dict):
        return str(version.get("name") or "Unknown")
    return str(version or "Unknown")


def _latency_display(status: Any) -> tuple[str, tuple[int, int, int]]:
    latency = float(getattr(status, "latency", -1))
    if latency < 0:
        return "-1ms", DEFAULT_TEXT
    if latency < 150:
        color = (85, 255, 85)
    elif latency < 300:
        color = (255, 255, 85)
    elif latency < 600:
        color = (255, 170, 0)
    else:
        color = (255, 85, 85)
    return f"{int(round(latency))}ms", color


def _server_icon(favicon: Optional[str]) -> Image.Image:
    if favicon:
        encoded = favicon.split(",", 1)[-1]
        try:
            with Image.open(BytesIO(base64.b64decode(encoded, validate=True))) as icon:
                if icon.size == (64, 64):
                    return icon.convert("RGBA")
        except (ValueError, binascii.Error, OSError):
            pass
    with Image.open(DEFAULT_ICON_PATH) as icon:
        return icon.convert("RGBA").resize((64, 64), Image.Resampling.NEAREST)


def _component_segments(
    component: Any,
    default_color: tuple[int, int, int],
) -> list[dict[str, Any]]:
    base_style = {
        "color": default_color,
        "bold": False,
        "italic": False,
        "underline": False,
        "strikethrough": False,
    }
    output: list[dict[str, Any]] = []

    def visit(node: Any, inherited: dict[str, Any]) -> None:
        if isinstance(node, list):
            for child in node:
                visit(child, inherited)
            return
        if isinstance(node, str):
            _append_legacy_text(output, node, inherited)
            return
        if not isinstance(node, dict):
            return

        style = dict(inherited)
        if "color" in node:
            style["color"] = resolve_color(node["color"])
        for key in ("bold", "italic", "underlined", "strikethrough"):
            if key in node:
                style["underline" if key == "underlined" else key] = bool(node[key])

        text = node.get("text")
        if text is None and "translate" in node:
            text = _translate(str(node["translate"]))
        if text is not None:
            _append_legacy_text(output, str(text), style)
        for child in node.get("extra", []):
            visit(child, style)

    visit(component, base_style)
    return output


def _append_legacy_text(
    output: list[dict[str, Any]], text: str, inherited: dict[str, Any]
) -> None:
    style = dict(inherited)
    buffer: list[str] = []

    def flush() -> None:
        if not buffer:
            return
        segment = {"text": "".join(buffer), **style}
        if output and all(output[-1][key] == segment[key] for key in style):
            output[-1]["text"] += segment["text"]
        else:
            output.append(segment)
        buffer.clear()

    index = 0
    while index < len(text):
        if text[index] != "§" or index + 1 >= len(text):
            buffer.append(text[index])
            index += 1
            continue

        code = text[index + 1].lower()
        if code == "x" and index + 13 < len(text):
            hex_parts = text[index + 2:index + 14]
            hex_digits = "".join(
                hex_parts[position + 1]
                for position in range(0, 12, 2)
                if hex_parts[position] == "§"
            )
            if len(hex_digits) == 6 and all(character in "0123456789abcdefABCDEF" for character in hex_digits):
                flush()
                style = {
                    **inherited,
                    "color": tuple(int(hex_digits[i:i + 2], 16) for i in (0, 2, 4)),
                    "bold": False,
                    "italic": False,
                    "underline": False,
                    "strikethrough": False,
                }
                index += 14
                continue
        if code in MC_COLORS:
            flush()
            style = {**inherited, "color": MC_COLORS[code], "bold": False,
                     "italic": False, "underline": False, "strikethrough": False}
        elif code == "r":
            flush()
            style = {
                "color": DEFAULT_TEXT,
                "bold": False,
                "italic": False,
                "underline": False,
                "strikethrough": False,
            }
        elif code == "l":
            flush()
            style["bold"] = True
        elif code == "o":
            flush()
            style["italic"] = True
        elif code == "n":
            flush()
            style["underline"] = True
        elif code == "m":
            flush()
            style["strikethrough"] = True
        elif code == "k":
            # Vanilla obfuscation is time-dependent; keep its text legible in a still image.
            pass
        else:
            buffer.extend(text[index:index + 2])
        index += 2
    flush()


def _translate(key: str) -> str:
    translations = {
        "multiplayer.status.cannot_connect": "无法连接到服务器",
        "multiplayer.status.pinging": "正在查询服务器……",
        "multiplayer.status.no_connection": "无法连接到服务器",
    }
    return translations.get(key, key)


def _wrap_segments(
    segments: list[dict[str, Any]], max_width: int, font: MinecraftFont
) -> list[list[dict[str, Any]]]:
    font.prepare("".join(segment["text"] for segment in segments))
    lines: list[list[tuple[str, dict[str, Any]]]] = [[]]
    line_width = 0.0
    for segment in segments:
        for character in segment["text"]:
            if character == "\n":
                lines.append([])
                line_width = 0.0
                continue
            advance = font.measure(character, segment["bold"])
            if lines[-1] and line_width + advance > max_width:
                line = lines[-1]
                break_at = next(
                    (i for i in range(len(line) - 1, -1, -1) if line[i][0].isspace()),
                    -1,
                )
                if break_at >= 0:
                    remainder = line[break_at + 1:]
                    lines[-1] = line[:break_at]
                    lines.append(remainder)
                    line_width = sum(
                        font.measure(char, style["bold"]) for char, style in remainder
                    )
                else:
                    lines.append([])
                    line_width = 0.0
                if character.isspace() and not lines[-1]:
                    continue
            style = {key: value for key, value in segment.items() if key != "text"}
            lines[-1].append((character, style))
            line_width += advance

    packed: list[list[dict[str, Any]]] = []
    for line in lines:
        packed_line: list[dict[str, Any]] = []
        for character, style in line:
            if packed_line and all(packed_line[-1][key] == style[key] for key in style):
                packed_line[-1]["text"] += character
            else:
                packed_line.append({"text": character, **style})
        packed.append(packed_line)
    return packed


