import math
from pathlib import Path
from PIL import Image, ImageDraw

def generate_icons():
    assets_dir = Path(__file__).resolve().parent.parent / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    png_path = assets_dir / "syntra_icon.png"
    ico_path = assets_dir / "syntra_icon.ico"

    # 繪製 256x256 高畫質星芒圓角圖示
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 繪製靛紫圓角矩形底圖
    draw.rounded_rectangle([8, 8, size - 8, size - 8], radius=54, fill=(99, 102, 241, 255))

    # 繪製中央白色四角星芒 (Gemini Sparkle)
    cx, cy = size // 2, size // 2
    r_outer = 84
    r_inner = 24
    points = []
    import math
    for i in range(8):
        angle = i * (math.pi / 4)
        r = r_outer if i % 2 == 0 else r_inner
        x = cx + r * math.cos(angle - math.pi / 2)
        y = cy + r * math.sin(angle - math.pi / 2)
        points.append((x, y))

    draw.polygon(points, fill=(255, 255, 255, 255))

    img.save(png_path, "PNG")
    # 儲存 ico 包含多尺寸 (16, 24, 32, 48, 64, 128, 256)
    img.save(
        ico_path,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print("Generated icons:", png_path, ico_path)

if __name__ == "__main__":
    generate_icons()
