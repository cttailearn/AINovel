"""生成 Tauri 源图标：深色主题 + AI 小说视觉元素"""
from PIL import Image, ImageDraw, ImageFont
import os

OUT = r"d:\AI\new\src-tauri\icons\source.png"
os.makedirs(os.path.dirname(OUT), exist_ok=True)

SIZE = 1024
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

for y in range(SIZE):
    ratio = y / SIZE
    r = int(15 + (88 - 15) * ratio)
    g = int(23 + (28 - 23) * ratio)
    b = int(42 + (135 - 42) * ratio)
    draw.line([(0, y), (SIZE, y)], fill=(r, g, b, 255))

margin = 80
draw.rounded_rectangle(
    [margin, margin, SIZE - margin, SIZE - margin],
    radius=120,
    fill=(255, 255, 255, 18),
    outline=(255, 255, 255, 50),
    width=4,
)

try:
    font_path = "C:\\Windows\\Fonts\\msyh.ttc"
    if not os.path.exists(font_path):
        font_path = "C:\\Windows\\Fonts\\msyh.ttf"
    if not os.path.exists(font_path):
        font_path = "C:\\Windows\\Fonts\\simhei.ttf"
    if not os.path.exists(font_path):
        font_path = "C:\\Windows\\Fonts\\arial.ttf"
    title_font = ImageFont.truetype(font_path, 360)
    sub_font = ImageFont.truetype(font_path, 120)
except Exception:
    title_font = ImageFont.load_default()
    sub_font = ImageFont.load_default()

title = "AI"
bbox = draw.textbbox((0, 0), title, font=title_font)
tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
draw.text(((SIZE - tw) / 2 - bbox[0], 280 - bbox[1]), title, font=title_font, fill=(255, 255, 255, 255))

sub = "NOVEL"
bbox2 = draw.textbbox((0, 0), sub, font=sub_font)
sw, sh = bbox2[2] - bbox2[0], bbox2[3] - bbox2[1]
draw.text(((SIZE - sw) / 2 - bbox2[0], 680 - bbox2[1]), sub, font=sub_font, fill=(140, 180, 255, 255))

img.save(OUT, "PNG")
print(f"源图标已生成: {OUT} ({os.path.getsize(OUT)} bytes)")
