"""Company and school logos for the CV. Images only: ATS parsers skip them, recruiters see them.
A real logo when one can be found, otherwise a monogram badge. Drop your own <id>.png in
candidates/<name>/logos/ to override either."""
import base64
import io
import logging
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"}
SIZE = 128
BADGE_COLOR = "#1e3a8a"  # one navy for every monogram, so they sit well next to real logos


def _image(data: bytes) -> Image.Image | None:
    try:
        img = Image.open(io.BytesIO(data))
        if getattr(img, "n_frames", 1) > 1 or img.format == "ICO":  # .ico: take the largest size
            sizes = sorted(img.info.get("sizes") or [img.size])
            img.size = sizes[-1] if img.format == "ICO" else img.size
        return img.convert("RGBA")
    except Exception:
        return None


def _fetch(url: str) -> Image.Image | None:
    try:
        r = requests.get(url, headers=UA, timeout=20)
        return _image(r.content) if r.ok else None
    except requests.RequestException:
        return None


def _candidates(domain: str) -> list[str]:
    """Icon URLs worth trying, best first."""
    urls = []
    try:
        page = requests.get(f"https://{domain}", headers=UA, timeout=20)
        soup = BeautifulSoup(page.text, "html.parser")
        links = []
        for tag in soup.find_all("link", rel=True):
            rel = " ".join(tag["rel"]).lower()
            if "icon" in rel and tag.get("href") and not tag["href"].endswith(".svg"):
                size = max((int(n) for n in re.findall(r"\d+", tag.get("sizes", ""))), default=0)
                links.append((("apple" in rel) * 1000 + size, urljoin(page.url, tag["href"])))
        urls += [u for _, u in sorted(links, reverse=True)]
    except requests.RequestException:
        pass
    urls += [f"https://www.google.com/s2/favicons?domain={domain}&sz=128",
             f"https://{domain}/apple-touch-icon.png", f"https://icons.duckduckgo.com/ip3/{domain}.ico"]
    return urls


def _flat(img: Image.Image) -> bool:
    """True for icons that are basically one color (a dot on a square): they read as a glitch on a CV."""
    pixels = list(img.convert("RGBA").resize((48, 48)).getdata())
    opaque = [px[:3] for px in pixels if px[3] > 128]
    if len(opaque) < 100:
        return True
    if len(opaque) / len(pixels) < 0.8:  # a one-color mark on a transparent background is a real logo
        return False
    buckets: dict = {}
    for r, g, b in opaque:
        key = (r // 32, g // 32, b // 32)
        buckets[key] = buckets.get(key, 0) + 1
    return max(buckets.values()) / len(opaque) > 0.9


def _square(img: Image.Image) -> Image.Image:
    bbox = img.getchannel("A").getbbox()
    if bbox:
        img = img.crop(bbox)
    side = max(img.size)
    canvas = Image.new("RGBA", (side, side), (255, 255, 255, 0))
    canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2), img)
    return canvas.resize((SIZE, SIZE), Image.LANCZOS)


def monogram(name: str, text: str = "") -> Image.Image:
    words = [w for w in re.split(r"[\s&-]+", name) if w and w[0].isalnum()]
    initials = (text or "".join(w[0] for w in words[:2]) or "?").upper()
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, SIZE - 1, SIZE - 1), radius=28, fill=BADGE_COLOR)
    font = None
    for f in ("seguisb.ttf", "segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            font = ImageFont.truetype(f, {1: 78, 2: 66, 3: 50, 4: 38}.get(len(initials), 30))
            break
        except OSError:
            continue
    draw.text((SIZE / 2, SIZE / 2), initials, fill="white", font=font or ImageFont.load_default(), anchor="mm")
    return img


def ensure(folder: Path, key: str, name: str, domain: str, badge: str = "", monogram_ok: bool = True) -> Path | None:
    """Return the logo file for an employer or school, fetching or drawing it once.
    monogram_ok=False: a real logo or None (used for the company being applied to)."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{key}.png"
    if path.exists():
        return path
    if not monogram_ok and (folder / f"{key}.none").exists():
        return None
    img = None
    if domain:
        for url in _candidates(domain):
            got = _fetch(url)
            if got and min(got.size) >= 48 and not _flat(got):
                img = _square(got)
                break
    if img is None:
        if not monogram_ok:
            (folder / f"{key}.none").touch()  # remembered: don't refetch on every pack
            return None
        log.info("no usable logo for %s, drawing a monogram", name)
        img = monogram(name, badge)
    img.save(path, "PNG", optimize=True)
    return path


def _svg_to_png(svg: bytes, bg: str = "") -> Image.Image:
    """Render an SVG logo (centred, padded) to a square PNG with Chromium. Optional brand background."""
    from playwright.sync_api import sync_playwright

    b64 = base64.b64encode(svg).decode()
    doc = (f'<div id="b" style="width:256px;height:256px;display:flex;align-items:center;justify-content:center;'
           f'background:{bg or "transparent"};border-radius:44px"><img src="data:image/svg+xml;base64,{b64}" '
           f'style="max-width:{78 if bg else 92}%;max-height:{78 if bg else 92}%"></div>')
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_content(doc, wait_until="load")
        png = page.locator("#b").screenshot(omit_background=True)
        browser.close()
    return Image.open(io.BytesIO(png)).convert("RGBA")


def from_url(url: str, bg: str = "") -> Image.Image | None:
    """A logo file named in the profile (PNG, JPG, ICO or SVG)."""
    try:
        # Wikimedia asks bots for an identifying user agent and rate-limits browser-looking ones.
        agent = "JobSearchLogos/1.0 (personal CV tool; python-requests)" if "wikimedia.org" in url else UA["User-Agent"]
        r = requests.get(url, headers={"User-Agent": agent}, timeout=25)
        r.raise_for_status()
    except requests.RequestException as e:
        log.warning("logo %s unreachable: %s", url, e)
        return None
    if url.lower().split("?")[0].endswith(".svg") or b"<svg" in r.content[:600]:
        return _svg_to_png(r.content, bg)
    img = _image(r.content)
    return _square(img) if img else None


def stack(top: Image.Image, bottom: Image.Image) -> Image.Image:
    """Two logos in one badge (an entry with two employers, like "Sitel & Webhelp")."""
    canvas = Image.new("RGBA", (SIZE, SIZE), (255, 255, 255, 0))
    for i, img in enumerate((top, bottom)):
        img = img.copy()
        bbox = img.getchannel("A").getbbox()
        img = img.crop(bbox) if bbox else img
        img.thumbnail((SIZE - 8, SIZE // 2 - 6), Image.LANCZOS)
        canvas.paste(img, ((SIZE - img.width) // 2, i * SIZE // 2 + (SIZE // 2 - img.height) // 2), img)
    return canvas


def refresh(cand, force: bool = False) -> list[str]:
    """Fetch every employer and school logo once: the profile's logo_url (one or two, joined by " + "), else the
    website's icon, else a monogram. Run after editing the profile; rendering only reads the cached files."""
    folder = cand.dir / "logos"
    folder.mkdir(exist_ok=True)
    entries = [(e["id"], e["company"], e) for e in cand.profile["experience"]]
    entries += [(f"edu-{i}", e["school"], e) for i, e in enumerate(cand.profile["education"])]
    done = []
    for key, name, e in entries:
        path = folder / f"{key}.png"
        if path.exists() and not force:
            continue
        img = None
        if e.get("logo_url"):
            parts = [from_url(u.strip(), e.get("logo_bg", "")) for u in e["logo_url"].split(" + ")]
            parts = [p for p in parts if p is not None]
            img = stack(*parts[:2]) if len(parts) == 2 else (parts[0] if parts else None)
        path.unlink(missing_ok=True)
        if img is None:
            path = ensure(folder, key, name, e.get("domain", ""), e.get("badge", ""))
        else:
            img.save(path, "PNG", optimize=True)
        done.append(f"{key}: {'logo file' if img is not None else 'site icon or monogram'}")
    return done


def brand_color(path: Path) -> str | None:
    """Dominant saturated color of a logo (#rrggbb), or None for black, white or grey logos."""
    import colorsys

    img = Image.open(path).convert("RGBA").resize((64, 64))
    opaque = [px for px in img.getdata() if px[3] > 128]
    bins: dict[int, list] = {}
    for r, g, b, _ in opaque:
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if s > 0.35 and 0.25 < v < 0.97:
            bins.setdefault(int(h * 24) % 24, []).append((r, g, b))
    if not opaque or not bins:
        return None
    best = max(bins.values(), key=len)
    if len(best) < 0.03 * len(opaque):
        return None
    r, g, b = (sum(c[i] for c in best) // len(best) for i in range(3))
    return f"#{r:02x}{g:02x}{b:02x}"


def data_uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()
