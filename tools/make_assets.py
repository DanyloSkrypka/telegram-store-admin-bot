"""Draw the demo product photos (flat illustrations) into assets/products/. Requires Pillow."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "assets" / "products"
S = 800


def canvas(bg: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (S, S), bg)
    return img, ImageDraw.Draw(img)


def shadow(img: Image.Image, box: tuple[int, int, int, int]) -> None:
    sh = Image.new("L", (S, S), 0)
    ImageDraw.Draw(sh).ellipse(box, fill=90)
    sh = sh.filter(ImageFilter.GaussianBlur(18))
    img.paste((0, 0, 0), mask=sh.point(lambda v: v // 3))


def tee(color: str, bg: str, boxy: bool = False, logo: str = "#f4efe6") -> Image.Image:
    img, d = canvas(bg)
    shadow(img, (190, 650, 610, 710))
    w = 40 if boxy else 0
    body = [(270 - w, 210), (340, 180), (460, 180), (530 + w, 210), (650 + w, 300), (585 + w, 375),
            (540 + w, 345), (540 + w, 640), (260 - w, 640), (260 - w, 345), (215 - w, 375), (150 - w, 300)]
    d.polygon(body, fill=color)
    d.arc((345, 150, 455, 240), 20, 160, fill=bg, width=26)
    d.rounded_rectangle((345, 300, 455, 330), 6, fill=logo)
    d.rounded_rectangle((365, 345, 435, 360), 4, fill=logo)
    return img


def hoodie(color: str, bg: str, zip_: bool = False) -> Image.Image:
    img, d = canvas(bg)
    shadow(img, (180, 660, 620, 720))
    d.polygon([(250, 230), (550, 230), (660, 420), (640, 650), (575, 650), (565, 420), (555, 660),
               (245, 660), (235, 420), (225, 650), (160, 650), (140, 420)], fill=color)
    d.ellipse((300, 120, 500, 300), fill=color)
    d.ellipse((340, 170, 460, 290), fill="#1d1d1f")
    if zip_:
        d.line((400, 290, 400, 660), fill="#c9c9c9", width=8)
    else:
        d.rounded_rectangle((310, 480, 490, 580), 20, outline="#00000033", width=6)
    d.line((370, 290, 360, 380), fill="#f4efe6", width=6)
    d.line((430, 290, 440, 380), fill="#f4efe6", width=6)
    return img


def cap(color: str, bg: str) -> Image.Image:
    img, d = canvas(bg)
    shadow(img, (180, 560, 640, 620))
    d.pieslice((220, 250, 580, 610), 180, 360, fill=color)
    d.rounded_rectangle((200, 420, 600, 450), 14, fill=color)
    d.polygon([(480, 430), (690, 470), (670, 510), (470, 455)], fill=color)
    d.ellipse((385, 238, 415, 262), fill="#f4efe6")
    d.rounded_rectangle((350, 340, 450, 370), 6, fill="#f4efe6")
    return img


def tote(color: str, bg: str) -> Image.Image:
    img, d = canvas(bg)
    shadow(img, (200, 660, 600, 720))
    d.arc((300, 150, 400, 360), 180, 360, fill=color, width=18)
    d.arc((400, 150, 500, 360), 180, 360, fill=color, width=18)
    d.rounded_rectangle((230, 280, 570, 670), 12, fill=color)
    d.rounded_rectangle((320, 430, 480, 470), 8, fill="#1d1d1f")
    return img


def stickers(bg: str) -> Image.Image:
    img, d = canvas(bg)
    shadow(img, (200, 640, 600, 700))
    for (x, y, r, c) in [(300, 330, 110, "#ff5a36"), (500, 320, 95, "#2f6bff"), (330, 520, 90, "#ffd23f"),
                         (520, 520, 105, "#1d1d1f")]:
        d.ellipse((x - r - 8, y - r - 8, x + r + 8, y + r + 8), fill="white")
        d.ellipse((x - r, y - r, x + r, y + r), fill=c)
    d.rounded_rectangle((470, 500, 570, 540), 8, fill="#f4efe6")
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = {
        "tee_classic.png": tee("#1d1d1f", "#e9e4da"),
        "tee_box.png": tee("#f4efe6", "#c9d3c0", boxy=True, logo="#1d1d1f"),
        "hoodie.png": hoodie("#4a5a3c", "#e6dccb"),
        "zip_hoodie.png": hoodie("#2b2b2e", "#d8dde6", zip_=True),
        "cap.png": cap("#c2462e", "#efe7da"),
        "tote.png": tote("#efe3c8", "#3d4a5c"),
        "stickers.png": stickers("#e3ece9"),
        "new_beanie.png": cap("#2f6bff", "#f1e9dc"),  # used by the demo's "add product" step
    }
    for name, img in jobs.items():
        img.resize((600, 600), Image.LANCZOS).save(OUT / name, optimize=True)
        print("wrote", OUT / name)


if __name__ == "__main__":
    main()
