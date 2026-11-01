"""Bitmap fonts used by Minecraft 26.1's default GUI font."""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw

from .mc_renderer import _vanilla_glyphs_for_text


ASSET_DIR = Path(__file__).with_name("assets") / "vanilla26"
_BITMAP_GLYPHS: Optional[dict[str, dict]] = None
_BITMAP_IMAGES: dict[str, Image.Image] = {}


def _load_bitmap_glyphs() -> dict[str, dict]:
    global _BITMAP_GLYPHS
    if _BITMAP_GLYPHS is not None:
        return _BITMAP_GLYPHS

    providers = json.loads(
        (ASSET_DIR / "font" / "include_default.json").read_text(encoding="utf-8")
    )["providers"]
    glyphs: dict[str, dict] = {}
    for provider in providers:
        texture_name = Path(provider["file"].split(":", 1)[1]).name
        if texture_name not in _BITMAP_IMAGES:
            with Image.open(ASSET_DIR / "font" / texture_name) as texture_file:
                _BITMAP_IMAGES[texture_name] = texture_file.convert("RGBA")
        texture = _BITMAP_IMAGES[texture_name]
        rows = provider["chars"]
        cell_width = texture.width // 16
        cell_height = texture.height // len(rows)
        for row_index, row in enumerate(rows):
            for column_index, character in enumerate(row):
                if character == "\0" or character in glyphs:
                    continue
                box = (
                    column_index * cell_width,
                    row_index * cell_height,
                    (column_index + 1) * cell_width,
                    (row_index + 1) * cell_height,
                )
                mask = texture.crop(box).getchannel("A")
                bounds = mask.getbbox()
                advance = 4 if character == " " else (bounds[2] + 1 if bounds else 0)
                glyphs[character] = {
                    "mask": mask,
                    "advance": advance,
                    "pixel_scale": 8 / cell_height,
                    "bold_offset": 1,
                    "shadow_offset": 1,
                    "y_offset": 0,
                }

    glyphs["\u200c"] = {
        "mask": Image.new("L", (1, 1), 0),
        "advance": 0,
        "pixel_scale": 1,
        "bold_offset": 1,
        "shadow_offset": 1,
        "y_offset": 0,
    }
    _BITMAP_GLYPHS = glyphs
    return glyphs


@lru_cache(maxsize=1)
def _get_unifont_glyphs(text: str) -> dict[int, Optional[dict]]:
    return _vanilla_glyphs_for_text(text)


class MinecraftFont:
    """Draw the game's bitmap ASCII glyphs and Unihex fallback glyphs."""

    def __init__(self, force_unicode_font: bool = False) -> None:
        self.force_unicode_font = force_unicode_font

    def prepare(self, text: str) -> None:
        if self.force_unicode_font:
            _vanilla_glyphs_for_text(text)
        else:
            bitmap_glyphs = _load_bitmap_glyphs()
            fallback_text = "".join(
                character for character in text
                if character not in bitmap_glyphs and character not in (" ", "\u200c")
            )
            if fallback_text:
                _vanilla_glyphs_for_text(fallback_text)

    def glyph(self, character: str) -> Optional[dict]:
        if character == "\u200c":
            return {
                "mask": None,
                "advance": 0,
                "pixel_scale": 1,
                "bold_offset": 1,
                "shadow_offset": 1,
                "y_offset": 0,
            }
        if character == " ":
            return {
                "mask": None,
                "advance": 4,
                "pixel_scale": 1,
                "bold_offset": 1,
                "shadow_offset": 1,
                "y_offset": 0,
            }
        if self.force_unicode_font:
            return _get_unifont_glyphs(character).get(ord(character))
        bitmap = _load_bitmap_glyphs().get(character)
        return bitmap if bitmap is not None else _get_unifont_glyphs(character).get(ord(character))

    def measure(self, text: str, bold: bool = False) -> float:
        self.prepare(text)
        width = 0.0
        for character in text:
            glyph = self.glyph(character)
            if glyph is not None:
                width += glyph["advance"] + (glyph["bold_offset"] if bold else 0)
        return width

    def draw(
        self,
        draw: ImageDraw.ImageDraw,
        position: tuple[int, int],
        text: str,
        color: tuple[int, int, int],
        scale: int,
        *,
        bold: bool = False,
        italic: bool = False,
        underline: bool = False,
        strikethrough: bool = False,
        shadow: bool = True,
    ) -> int:
        self.prepare(text)
        x, y = position
        start_x = x
        for character in text:
            glyph = self.glyph(character)
            if glyph is None:
                continue
            advance = glyph["advance"]
            bold_offset = glyph["bold_offset"] if bold else 0
            mask = glyph["mask"]
            pixel_scale = glyph["pixel_scale"] * scale
            if mask is not None:
                width = max(1, math.ceil(mask.width * pixel_scale))
                height = max(1, math.ceil(mask.height * pixel_scale))
                scaled_mask = mask.resize((width, height), Image.Resampling.NEAREST)
                glyph_y = y + int(glyph.get("y_offset", 0) * scale)
                shadow_color = tuple(channel // 4 for channel in color)

                def draw_instance(origin_x: int, origin_y: int, ink: tuple[int, int, int]) -> None:
                    if italic:
                        for line_y in range(height):
                            line = scaled_mask.crop((0, line_y, width, line_y + 1))
                            slant = math.floor((height - line_y - 1) / 4)
                            draw.bitmap(
                                (origin_x + slant, origin_y + line_y),
                                line,
                                fill=(*ink, 255) if draw.mode == "RGBA" else ink,
                            )
                    else:
                        draw.bitmap(
                            (origin_x, origin_y),
                            scaled_mask,
                            fill=(*ink, 255) if draw.mode == "RGBA" else ink,
                        )

                if shadow:
                    shadow_offset = int(glyph["shadow_offset"] * scale)
                    draw_instance(x + shadow_offset, glyph_y + shadow_offset, shadow_color)
                    if bold:
                        draw_instance(x + int(bold_offset * scale) + shadow_offset,
                                      glyph_y + shadow_offset, shadow_color)
                draw_instance(x, glyph_y, color)
                if bold:
                    draw_instance(x + int(bold_offset * scale), glyph_y, color)

            x += int(round((advance + bold_offset) * scale))

        if text and underline:
            decoration_y = y + 7 * scale
            fill = (*color, 255) if draw.mode == "RGBA" else color
            draw.line((start_x, decoration_y, x - 1, decoration_y), fill=fill, width=scale)
        if text and strikethrough:
            decoration_y = y + 3 * scale
            fill = (*color, 255) if draw.mode == "RGBA" else color
            draw.line((start_x, decoration_y, x - 1, decoration_y), fill=fill, width=scale)
        return x - start_x


FONT = MinecraftFont(force_unicode_font=False)
