"""Build an experimental 512x512 scene atlas from an OFL Noto Sans JP font.

Requires Pillow; pass the unmodified NotoSansJP[wght].ttf from google/fonts.
The SHA-256 guard prevents silently changing the glyph source on regeneration.
"""
import argparse
import ast
import hashlib
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SOURCE_SHA256 = "c2f3b4d463500a2ddcd3849cded1fceeb9fd6d1c32e6cbecd568453ba50fc68f"
GLYPH = re.compile(r'\{\s*((?:"(?:\\.|[^"\\])*"\s*)+),\s*(\d+),\s*(\d+)\s*\}')
STRING = re.compile(r'"(?:\\.|[^"\\])*"')


def glyphs(source):
    atlas = source.split("constexpr Glyph kAtlas[] = {", 1)[1].split("};", 1)[0]
    for match in GLYPH.finditer(atlas):
        chunks = []
        for literal in STRING.findall(match.group(1)):
            normalized = re.sub(r"\\x([0-9a-fA-F])(?![0-9a-fA-F])", r"\\x0\1", literal)
            chunks.append(ast.literal_eval(normalized).encode("latin-1"))
        label = b"".join(chunks).decode("cp932", errors="replace")
        yield label, int(match.group(2)), int(match.group(3))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if hashlib.sha256(arguments.font.read_bytes()).hexdigest() != SOURCE_SHA256:
        parser.error("font SHA-256 differs from the audited Noto Sans JP release")
    source = (Path(__file__).resolve().parents[1] / "src/render/scene_font.cpp").read_text(
        encoding="utf-8")
    atlas = Image.new("RGBA", (512, 512), (255, 255, 255, 0))
    mask = Image.new("L", (512, 512), 0)
    draw = ImageDraw.Draw(mask)
    font = ImageFont.truetype(str(arguments.font), 30)
    font.set_variation_by_axes([700])
    for label, left, top in glyphs(source):
        draw.text((left, top), label, font=font, fill=255, anchor="lt")
    atlas.putalpha(mask)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    atlas.save(arguments.output)


if __name__ == "__main__":
    main()
