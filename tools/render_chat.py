"""Render the scripted demo into Telegram-style screenshots and an animated GIF.

Runs the real handlers through the emulator (store_bot.demo.scripted), turns every step into an
HTML chat screen, screenshots it with headless Chrome and assembles docs/demo.gif with ffmpeg.

    python tools/render_chat.py            # needs Google Chrome/Chromium and ffmpeg
"""
from __future__ import annotations

import asyncio
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from store_bot.demo import scripted  # noqa: E402

DOCS = ROOT / "docs"
CHROME_CANDIDATES = [
    os.environ.get("CHROME", ""),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    shutil.which("google-chrome") or "", shutil.which("chromium") or "", shutil.which("chromium-browser") or "",
]
W, H = 400, 780

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{width:%dpx;height:%dpx;background:#0e1621;font:14px/1.38 -apple-system,'SF Pro Text','Segoe UI',Roboto,sans-serif;
color:#f5f5f5;display:flex;flex-direction:column;overflow:hidden}
.top{height:56px;background:#17212b;display:flex;align-items:center;gap:10px;padding:0 14px;flex:none;
box-shadow:0 1px 0 #0b1118}
.ava{width:38px;height:38px;border-radius:50%%;background:linear-gradient(135deg,#ff7a45,#c2462e);display:grid;
place-items:center;font-weight:700;font-size:15px}
.who b{display:block;font-size:15px}.who span{color:#7f91a4;font-size:12.5px}
.chat{flex:1;display:flex;flex-direction:column;justify-content:flex-end;gap:6px;padding:10px 10px 8px;
overflow:hidden;background:radial-gradient(circle at 20%% 10%%,#13202e 0,#0e1621 60%%)}
.row{display:flex;flex-direction:column;max-width:86%%}
.row.bot{align-self:flex-start}.row.user{align-self:flex-end;align-items:flex-end}
.bub{background:#182533;border-radius:14px 14px 14px 4px;padding:7px 10px 8px;white-space:pre-wrap;word-wrap:break-word}
.user .bub{background:#2b5278;border-radius:14px 14px 4px 14px}
.bub.ph{padding:0;overflow:hidden;width:262px}.bub.ph img{display:block;width:262px;height:262px;object-fit:cover}
.bub.ph .cap{padding:7px 10px 8px;white-space:pre-wrap}
.uimg{width:180px;height:180px;border-radius:14px;object-fit:cover;display:block}
.kb{display:flex;flex-direction:column;gap:3px;margin-top:3px;width:100%%;min-width:262px}
.kr{display:flex;gap:3px}.kr div{flex:1;background:rgba(43,82,120,.55);border-radius:8px;padding:7px 6px;
text-align:center;font-size:13px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.inv{width:262px}.inv .t{font-weight:600}.inv .d{color:#b9c6d3;font-size:13px;margin:3px 0 6px}
.inv .ln{display:flex;justify-content:space-between;font-size:13px;color:#cfd8e3}
.inv .pay{margin-top:8px;background:#5288c1;border-radius:8px;text-align:center;padding:8px;font-weight:600}
.doc{display:flex;gap:10px;align-items:center}.doc .ic{width:40px;height:40px;border-radius:50%%;background:#5288c1;
display:grid;place-items:center;font-size:18px}.doc small{color:#8da2b8}
.svc{align-self:center;background:rgba(0,0,0,.35);border-radius:12px;padding:4px 12px;font-size:12.5px;color:#dfe7ee}
.foot{flex:none;background:#17212b;padding:9px 14px 11px;border-top:1px solid #0b1118}
.foot .k{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#6ab3f3;font-weight:700}
.foot .c{font-size:14px;margin-top:2px}
b,strong{font-weight:650}i{color:#a9b8c7}code{font-family:ui-monospace,Menlo,monospace;font-size:12.5px}
a{color:#6ab3f3;text-decoration:none}
""" % (W, H)

ALLOWED = re.compile(r"&lt;(/?)(b|i|code|a)(?:\s+href=&quot;[^&]*&quot;)?&gt;")


def rich(text: str) -> str:
    """Bot texts are Telegram-HTML: keep b/i/code/a, escape everything else."""
    esc = html.escape(text or "", quote=True)
    esc = esc.replace("&amp;lt;", "&lt;").replace("&amp;gt;", "&gt;").replace("&amp;amp;", "&amp;")
    return ALLOWED.sub(lambda m: f"<{m.group(1)}{m.group(2)}>", esc)


def keyboard(buttons) -> str:
    if not buttons:
        return ""
    rows = "".join("<div class=kr>" + "".join(f"<div>{html.escape(b['text'])}</div>" for b in row) + "</div>"
                   for row in buttons)
    return f"<div class=kb>{rows}</div>"


def item_html(it: dict) -> str:
    who, kind = it["who"], it["kind"]
    if kind == "payment":
        return f"<div class=svc>💳 {html.escape(it['text'])}</div>"
    if who == "user":
        if kind == "photo":
            return f"<div class='row user'><img class=uimg src='{Path(it['photo']).as_uri()}'></div>"
        return f"<div class='row user'><div class=bub>{html.escape(it['text'])}</div></div>"
    if kind == "photo":
        img = f"<img src='{Path(it['photo']).as_uri()}'>" if it.get("photo") else ""
        body = f"<div class='bub ph'>{img}<div class=cap>{rich(it['text'])}</div></div>"
    elif kind == "invoice":
        title, _, desc = it["text"].partition("\n")
        ex = it.get("extra", {})
        lines = "".join(f"<div class=ln><span>{html.escape(lbl)}</span><span>€{amt / 100:.2f}</span></div>"
                        for lbl, amt in ex.get("prices", []))
        total = sum(a for _, a in ex.get("prices", [])) / 100
        body = (f"<div class='bub inv'><div class=t>{html.escape(title)}</div><div class=d>{html.escape(desc)}</div>"
                f"{lines}<div class=pay>Pay €{total:.2f} + shipping</div></div>")
    elif kind == "document":
        name = it.get("extra", {}).get("filename", "file")
        body = (f"<div class=bub><div class=doc><div class=ic>📄</div><div>{html.escape(name)}<br>"
                f"<small>{rich(it['text'])}</small></div></div></div>")
    else:
        body = f"<div class=bub>{rich(it['text'])}</div>"
    return f"<div class='row bot'>{body}{keyboard(it.get('buttons'))}</div>"


def page(frame: dict) -> str:
    chat = "".join(item_html(i) for i in frame["items"][-14:])
    return (f"<!doctype html><meta charset=utf-8><style>{CSS}</style><div class=top><div class=ava>K</div>"
            f"<div class=who><b>KIEZ Supply</b><span>bot</span></div></div><div class=chat>{chat}</div>"
            f"<div class=foot><div class=k>{html.escape(frame['title'])}</div>"
            f"<div class=c>{html.escape(frame['caption'])}</div></div>")


def chrome() -> str:
    for c in CHROME_CANDIDATES:
        if c and Path(c).exists():
            return c
    sys.exit("Chrome/Chromium not found; set CHROME=/path/to/chrome")


def shoot(browser: str, html_file: Path, png: Path, scale: int) -> None:
    subprocess.run([browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                    f"--window-size={W},{H}", f"--force-device-scale-factor={scale}",
                    "--allow-file-access-from-files", f"--screenshot={png}", html_file.as_uri()],
                   check=True, capture_output=True, timeout=60)


SCREENSHOTS = {  # caption -> file name (static images for the README)
    "Product card with photo": "01-product-card.png",
    "Checkout → Telegram invoice": "02-cart-invoice.png",
    "Owner gets the paid order instantly": "03-owner-alert.png",
    "Product is live": "04-admin-add-product.png",
    "Product card in German": "05-german-customer.png",
}


def main() -> None:
    h = asyncio.run(scripted(quiet=True))
    frames = [f for n, f in enumerate(h.frames)
              if f["caption"] != "Wizard step" or h.frames[n + 1]["caption"] != "Wizard step"]
    browser = chrome()
    (DOCS / "screenshots").mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmpd = Path(tmp)
        lst = []
        for n, frame in enumerate(frames):
            hf = tmpd / f"f{n:03d}.html"
            hf.write_text(page(frame), encoding="utf-8")
            png = tmpd / f"f{n:03d}.png"
            shoot(browser, hf, png, 1)
            hold = 2.4 if frame["caption"] in SCREENSHOTS or n == len(frames) - 1 else 1.1
            lst.append(f"file '{png}'\nduration {hold}")
            if frame["caption"] in SCREENSHOTS:
                shoot(browser, hf, DOCS / "screenshots" / SCREENSHOTS[frame["caption"]], 2)
        lst.append(f"file '{tmpd / f'f{len(frames) - 1:03d}.png'}'")
        (tmpd / "list.txt").write_text("\n".join(lst))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(tmpd / "list.txt"),
                        "-vf", "split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];"
                               "[b][p]paletteuse=dither=bayer:bayer_scale=4", str(DOCS / "demo.gif")], check=True)
    print(f"{len(frames)} frames -> {DOCS / 'demo.gif'} ({(DOCS / 'demo.gif').stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
