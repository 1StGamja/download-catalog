"""앱 아이콘(app.ico) 생성: 파란 원 + 아래 화살표(트레이 아이콘과 같은 모양)."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 256
k = SIZE / 64  # main.make_icon()의 64px 좌표를 확대


def draw():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2 * k, 2 * k, 62 * k, 62 * k), fill=(37, 99, 235, 255))
    d.polygon([(x * k, y * k) for x, y in
               [(32, 46), (18, 30), (26, 30), (26, 14), (38, 14), (38, 30), (46, 30)]],
              fill=(255, 255, 255, 255))
    d.rectangle((18 * k, 49 * k, 46 * k, 53 * k), fill=(255, 255, 255, 255))
    return img


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("app.ico")
    draw().save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("icon:", out)
