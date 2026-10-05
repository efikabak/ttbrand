#!/usr/bin/env python3
"""Builds TTR Studio into public/: the page, every downloadable file, and the zips.

Sources: assets/logo (SVG masters), assets/video, fonts/, src/ (templates, textures, web font), site/index.html.
Run:  python3 build.py            full build
      python3 build.py --html     only re-copy the page (fast, for copy and CSS edits)
"""
import json, os, shutil, struct, subprocess, sys, tempfile, time, zipfile
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "public"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SITE = os.environ.get("SITE_URL", "https://ttbrand.vercel.app").rstrip("/")

# CMYK is only published for the primaries (from the original guidelines); nothing else gets invented values
COLORS = {
    "Primary": [("Obsidian", "#131313", (0, 0, 0, 93)), ("Ash", "#EDE8E4", (0, 2, 4, 7)), ("Golden Yellow", "#FCCF00", (0, 18, 100, 1))],
    "Extended": [("Navy", "#001F47"), ("Bronze", "#642D00"), ("Forest", "#2A6400"),
                 ("Violet", "#8A55F8"), ("Blaze", "#FC5400"), ("Emerald", "#BCE0A2")],
    "Neutrals": [("Cloud", "#FFFCF9"), ("Pearl", "#FCF6EF"), ("Egg Shell", "#F0E9E3"),
                 ("Graphite", "#40424D"), ("Arsenic", "#1E1E24")],
}
GOLD_FOIL = [("#F0D39D", 0), ("#FDEED2", 30), ("#DBC29B", 65), ("#A88043", 100)]
WAY_NAME = {"light": "light", "dark": "dark", "yellow": "gold"}


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def slug(name):
    return name.lower().replace(" ", "-")


def shoot(html, w, h, out):
    """Render an HTML string to a PNG with headless Chrome."""
    out = Path(out)
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "p.html"
        page.write_text(html)
        prof = Path(tmp) / "prof"
        if out.exists():
            out.unlink()
        # this Chrome writes the file but doesn't exit on its own, so wait for the file and close it
        proc = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                                 f"--window-size={w},{h}", "--virtual-time-budget=3000",
                                 f"--user-data-dir={prof}", f"--screenshot={out}", page.as_uri()],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(200):
            if out.exists() and out.stat().st_size > 0:
                time.sleep(0.4)
                break
            time.sleep(0.2)
        proc.kill()
        subprocess.run(["pkill", "-f", str(prof)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not out.exists():
            raise RuntimeError(f"render failed: {out}")


def ase(groups):
    """Adobe Swatch Exchange (.ase): one group per palette, global swatches."""
    def name_block(n):
        s = (n + "\0").encode("utf-16-be")
        return struct.pack(">H", len(s) // 2) + s
    blocks = []
    for group, items in groups.items():
        body = name_block(group)
        blocks.append(struct.pack(">HI", 0xC001, len(body)) + body)
        for item in items:
            n, hx = item[0], item[1]
            r, g, b = (v / 255 for v in rgb(hx))
            body = name_block(n) + b"RGB " + struct.pack(">fff", r, g, b) + struct.pack(">H", 0)
            blocks.append(struct.pack(">HI", 0x0001, len(body)) + body)
        blocks.append(struct.pack(">HI", 0xC002, 0))
    return b"ASEF" + struct.pack(">HHI", 1, 0, len(blocks)) + b"".join(blocks)


def zipdir(zpath, files):
    """Deterministic zip: fixed dates, already-compressed media stored as-is."""
    with zipfile.ZipFile(zpath, "w") as z:
        for arc, src in files:
            zi = zipfile.ZipInfo(arc, date_time=(2026, 1, 1, 0, 0, 0))
            zi.external_attr = 0o644 << 16
            zi.compress_type = zipfile.ZIP_STORED if src.suffix.lower() in {".png", ".jpg", ".mp4", ".woff2"} else zipfile.ZIP_DEFLATED
            z.writestr(zi, src.read_bytes())


def page_html():
    return ((ROOT / "site/index.html").read_text()
            .replace("{{SITE}}", SITE)
            .replace("{{UPDATED}}", time.strftime("%B %Y")))


def write_sizes():
    sizes = {str(p.relative_to(OUT)): p.stat().st_size for p in OUT.rglob("*") if p.is_file() and p.name != "sizes.json"}
    (OUT / "sizes.json").write_text(json.dumps(sizes, indent=1))
    return sizes


def main():
    if "--html" in sys.argv:
        (OUT / "index.html").write_text(page_html())
        write_sizes()
        return
    if OUT.exists():
        shutil.rmtree(OUT)
    a = OUT / "assets"
    for d in ["logo", "fonts", "video", "color", "avatars", "templates", "textures", "thumbs"]:
        (a / d).mkdir(parents=True, exist_ok=True)
    (OUT / "downloads").mkdir()
    tmp = Path(tempfile.mkdtemp())

    # logos: SVG masters as delivered; every PNG re-rendered from its SVG at 4000px so all nine match
    for src, dst in [("primary", "primary"), ("secondary", "stacked"), ("symbol", "symbol")]:
        (a / "logo" / dst).mkdir(parents=True, exist_ok=True)
        for svg in sorted((ROOT / "assets/logo" / src).glob("*.svg")):
            shutil.copy(svg, a / "logo" / dst / svg.name)
    for svg in sorted((a / "logo").rglob("*.svg")):
        subprocess.run(["sips", "-s", "format", "png", "-Z", "4000", str(svg), "--out", str(svg.with_suffix(".png"))],
                       stdout=subprocess.DEVNULL, check=True)

    # fonts + video (the reveal is silent, so drop the empty audio track)
    for f in ["Trove-SuperCondensed.otf", "Druk-CondSuper.otf"]:
        shutil.copy(ROOT / "fonts" / f, a / "fonts" / f)
    shutil.copy(ROOT / "src/Trove-SuperCondensed.woff2", a / "fonts")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(ROOT / "assets/video/intro.mp4"), "-c", "copy", "-an",
                    "-movflags", "+faststart", str(a / "video/ttr-logo-reveal.mp4")], check=True)

    # templates: the Figma examples, plus blank bases with the example copy cloned out
    from PIL import Image
    t = a / "templates"
    for n in ("cover", "inner"):
        shutil.copy(ROOT / f"src/templates/ttr-post-{n}-template.png", t / f"ttr-post-{n}-example.png")

    def blank(src, out, moves):
        im = Image.open(src).convert("RGB")
        for (y0, y1), dy in moves:  # paste empty background from elsewhere over the copy
            im.paste(im.crop((0, y0 + dy, 1080, y1 + dy)), (0, y0))
        im.save(out, optimize=True)
    blank(t / "ttr-post-cover-example.png", t / "ttr-post-cover-blank.png", [((40, 440), 560), ((1340, 1440), -400)])
    blank(t / "ttr-post-inner-example.png", t / "ttr-post-inner-blank.png", [((72, 265), 790), ((1258, 1352), -790)])
    for f in sorted((ROOT / "src/textures").iterdir()):
        if not f.name.startswith("."):
            shutil.copy(f, a / "textures" / f.name)

    # web-only previews (the full files are big)
    def thumb(src, dst, size):
        subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "82", "-Z", str(size), str(src), "--out", str(dst)],
                       stdout=subprocess.DEVNULL, check=True)
    thumb(t / "ttr-post-cover-example.png", a / "thumbs/cover.jpg", 900)
    thumb(t / "ttr-post-inner-example.png", a / "thumbs/inner.jpg", 900)
    thumb(t / "ttr-post-cover-blank.png", a / "thumbs/cover-blank.jpg", 900)
    thumb(t / "ttr-post-inner-blank.png", a / "thumbs/inner-blank.jpg", 900)
    thumb(a / "textures/ttr-paper-grain.png", a / "thumbs/paper.jpg", 900)
    thumb(a / "textures/ttr-film-scratches.png", a / "thumbs/film.jpg", 900)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "4.9", "-i", str(a / "video/ttr-logo-reveal.mp4"), "-frames:v", "1",
                    "-vf", "scale=1280:-1", str(a / "thumbs/reveal-poster.jpg")], check=True)
    # light 720p version for the hero; the 1080p master stays for the player and downloads
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(a / "video/ttr-logo-reveal.mp4"), "-an", "-vf", "scale=-2:720",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "28", "-preset", "slow", "-movflags", "+faststart",
                    str(a / "thumbs/hero.mp4")], check=True)

    # color files
    flat = [(g, it[0], it[1], it[2] if len(it) > 2 else None) for g, items in COLORS.items() for it in items]
    data = {"palette": [{"group": g, "name": n, "hex": h, "rgb": rgb(h), **({"cmyk": c} if c else {})} for g, n, h, c in flat],
            "goldFoil": {"type": "linear-gradient", "angle": 135, "stops": [{"hex": h, "at": p} for h, p in GOLD_FOIL]}}
    (a / "color/ttr-colors.json").write_text(json.dumps(data, indent=2))
    css = [":root {"] + [f"  --ttr-{slug(n)}: {h};" for _, n, h, _ in flat]
    css.append("  --ttr-gold-foil: linear-gradient(135deg, " + ", ".join(f"{h} {p}%" for h, p in GOLD_FOIL) + ");")
    css.append("}")
    (a / "color/ttr-colors.css").write_text("\n".join(css) + "\n")
    (a / "color/ttr-colors.ase").write_bytes(ase(COLORS))
    stops = ", ".join(f"{h} {p}%" for h, p in GOLD_FOIL)
    shoot(f'<body style="margin:0;width:2000px;height:2000px;background:linear-gradient(135deg,{stops})"></body>',
          2000, 2000, a / "color/ttr-gold-foil.png")

    # social avatars: symbol centred on brand colours, 1080 square
    sym = {k: (ROOT / f"assets/logo/symbol/TT_symbol_{k}.svg").read_text() for k in ["light", "dark", "yellow"]}
    for name, bg, mark in [("obsidian", "#131313", "light"), ("golden", "#FCCF00", "dark"), ("ash", "#EDE8E4", "dark"), ("obsidian-gold", "#131313", "yellow")]:
        svg = sym[mark].replace("<svg ", '<svg style="height:560px;width:auto" ', 1)
        shoot(f'<body style="margin:0;width:1080px;height:1080px;background:{bg};display:grid;place-items:center">{svg}</body>',
              1080, 1080, a / f"avatars/ttr-avatar-{name}.png")

    # read-mes that travel with the files
    readmes = {
        "fonts": "TTR fonts\n\n"
                 "Trove Super Condensed: headlines and display. Uppercase only.\n"
                 "Druk Condensed Super: licensed. Use only under Treasure Trove's license.\n"
                 "Web/: Trove as WOFF2 for websites.\n"
                 "Archivo (free): body copy, UI, captions. https://fonts.google.com/specimen/Archivo\n"
                 "Anton (free): fallback for Trove in Google Slides and shared docs. https://fonts.google.com/specimen/Anton\n",
        "logos": "TTR logos\n\n"
                 "Light: Ash logo for Obsidian and dark grounds.\n"
                 "Dark: Obsidian logo for Ash and light grounds.\n"
                 "Gold: Golden Yellow. Reserved, dark grounds only.\n\n"
                 "SVG for anything that scales. PNG (4000px) for slides and docs.\n"
                 "Keep half the symbol's width clear on every side. Symbol: 24px minimum.\n"
                 f"Full guide: {SITE}\n",
        "kit": "Treasure Trove brand kit\n\n"
               "Logos/      every lockup in light, dark and gold, plus social avatars\n"
               "Fonts/      Trove Super Condensed, Druk Condensed Super\n"
               "Colors/     Adobe swatches (.ase), CSS, JSON, Gold Foil gradient\n"
               "Templates/  Instagram cover and inside slide, blank and example\n"
               "Textures/   film scratches, paper grain\n"
               "Motion/     the logo reveal\n\n"
               f"Full guide: {SITE}\n",
    }
    rd = {k: tmp / f"{k}.txt" for k in readmes}
    for k, v in readmes.items():
        rd[k].write_text(v)

    # zips with names that match the site
    def files(folder, prefix):
        return [(f"{prefix}/{p.relative_to(folder)}", p) for p in sorted(folder.rglob("*"))
                if p.is_file() and not any(s.startswith(".") for s in p.relative_to(folder).parts)]

    def logo_arc(p):
        way = next(w for w in WAY_NAME if f"_{w}" in p.stem)
        lockup = p.parent.name
        return f"TTR-Logos/{lockup.title()}/TTR-{lockup}-{WAY_NAME[way]}{p.suffix}"
    logos = [(logo_arc(p), p) for p in sorted((a / "logo").rglob("*")) if p.is_file()]
    logos += files(a / "avatars", "TTR-Logos/Social avatars") + [("TTR-Logos/README.txt", rd["logos"])]
    fonts = [("TTR-Fonts/Trove-SuperCondensed.otf", a / "fonts/Trove-SuperCondensed.otf"),
             ("TTR-Fonts/Druk-CondSuper.otf", a / "fonts/Druk-CondSuper.otf"),
             ("TTR-Fonts/Web/Trove-SuperCondensed.woff2", a / "fonts/Trove-SuperCondensed.woff2"),
             ("TTR-Fonts/README.txt", rd["fonts"])]
    colors = files(a / "color", "TTR-Colors")
    templates = files(a / "templates", "TTR-Templates")
    textures = files(a / "textures", "TTR-Textures")
    zipdir(OUT / "downloads/TTR-Logos.zip", logos)
    zipdir(OUT / "downloads/TTR-Fonts.zip", fonts)
    zipdir(OUT / "downloads/TTR-Colors.zip", colors)
    zipdir(OUT / "downloads/TTR-Templates.zip", templates)
    zipdir(OUT / "downloads/TTR-Textures.zip", textures)
    kit = [("TTR-Brand-Kit/" + arc.split("/", 1)[0].replace("TTR-", "") + "/" + arc.split("/", 1)[1], src)
           for arc, src in logos + fonts + colors + templates + textures]
    kit += [("TTR-Brand-Kit/Motion/ttr-logo-reveal.mp4", a / "video/ttr-logo-reveal.mp4"), ("TTR-Brand-Kit/README.txt", rd["kit"])]
    zipdir(OUT / "downloads/TTR-Brand-Kit.zip", kit)

    # the page, icons, share image
    (OUT / "index.html").write_text(page_html())
    light = sym["light"]
    (OUT / "favicon.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#000"/>'
        '<svg x="17" y="8" width="30" height="48" viewBox="0 0 187 292">' + light.split(">", 1)[1].replace("</svg>", "") + "</svg></svg>")
    shoot(f'<body style="margin:0;width:180px;height:180px;background:#000;display:grid;place-items:center">'
          + light.replace("<svg ", '<svg style="height:118px;width:auto" ', 1) + "</body>", 180, 180, OUT / "apple-touch-icon.png")
    font = (a / "fonts/Trove-SuperCondensed.woff2").as_uri()
    film = (a / "thumbs/film.jpg").as_uri()
    og = f"""<html><head><style>@font-face{{font-family:T;src:url({font})}}
body{{margin:0;width:1200px;height:630px;background:#131313 url({film}) center/cover;background-blend-mode:screen;display:flex;align-items:flex-end;padding:64px;box-sizing:border-box;position:relative;overflow:hidden}}
h1{{font:400 150px/.86 T;text-transform:uppercase;margin:0}} h1 span{{display:block;width:fit-content;background:#EDE8E4;color:#131313;padding:.09em .14em .02em}} h1 span.g{{background:#FCCF00}}
.s{{position:absolute;right:80px;top:70px;height:220px;opacity:.9}}</style></head><body>
{light.replace("<svg ", '<svg class="s" ', 1)}<h1><span>Treasure Trove</span><span class="g">Studio</span></h1></body></html>"""
    shoot(og, 1200, 630, tmp / "og.png")
    subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "84", str(tmp / "og.png"), "--out", str(OUT / "og.jpg")],
                   stdout=subprocess.DEVNULL, check=True)
    shutil.rmtree(tmp, ignore_errors=True)

    sizes = write_sizes()
    for k in sorted(sizes):
        if k.startswith("downloads/"):
            print(f"{sizes[k] / 1e6:7.1f} MB  {k}")


if __name__ == "__main__":
    main()
