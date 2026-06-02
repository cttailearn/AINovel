"""生成 Tauri 需要的所有图标尺寸"""
from PIL import Image
import os

SRC = r"d:\AI\new\src-tauri\icons\source.png"
ICONS_DIR = r"d:\AI\new\src-tauri\icons"

os.chdir(ICONS_DIR)

source = Image.open(SRC).convert("RGBA")
print(f"源图: {source.size}")

sizes = {
    "32x32.png": 32,
    "128x128.png": 128,
    "128x128@2x.png": 256,
    "icon.png": 512,
    "Square30x30Logo.png": 30,
    "Square44x44Logo.png": 44,
    "Square71x71Logo.png": 71,
    "Square89x89Logo.png": 89,
    "Square107x107Logo.png": 107,
    "Square142x142Logo.png": 142,
    "Square150x150Logo.png": 150,
    "Square284x284Logo.png": 284,
    "Square310x310Logo.png": 310,
    "StoreLogo.png": 50,
}

for name, size in sizes.items():
    resized = source.resize((size, size), Image.LANCZOS)
    resized.save(name, "PNG")
    print(f"  {name}: {size}x{size}")

ico_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
source.resize((256, 256), Image.LANCZOS).save(
    "icon.ico", format="ICO", sizes=ico_sizes
)
print(f"  icon.ico: 多尺寸")

print("\n全部完成")
print("\n生成的文件:")
for f in sorted(os.listdir(".")):
    if f.endswith((".png", ".ico")):
        size = os.path.getsize(f)
        print(f"  {f}: {size} bytes")
