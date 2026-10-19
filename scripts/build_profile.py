#!/usr/bin/env python3
"""Builds assets/terminal.svg (animated ASCII avatar + neofetch-style card)
and the projects table in README.md, using live data from the GitHub API.

Runs in GitHub Actions (see .github/workflows/profile-card.yml).
Local test: python scripts/build_profile.py --avatar some.png --repos repos.json --user user.json
"""
import argparse
import io
import json
import os
import re
from datetime import datetime, timezone
from html import escape

import requests
from PIL import Image, ImageDraw

LOGIN = os.environ.get("GH_LOGIN", "shanshantanusingh113-max")
DISPLAY_NAME = "Shantanu"
FOCUS = [
    ("Building", "Kepler Orrery · 3D Solar System Lab"),
    ("Learning", "C++ in depth"),
    ("Exploring", "AI · Google Cloud"),
    ("Ask me", "Collaboration · Tech support"),
]
STACK = "C · C++ · Python · GCP · Git · Linux"
MAX_CARD_PROJECTS = 8

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SVG_OUT = os.path.join(ROOT, "assets", "terminal.svg")
README = os.path.join(ROOT, "README.md")

LANG_COLORS = {
    "Python": "#3572A5", "C++": "#f34b7d", "C": "#8b8b8b", "JavaScript": "#f1e05a",
    "TypeScript": "#3178c6", "HTML": "#e34c26", "CSS": "#663399", "Java": "#b07219",
    "Jupyter Notebook": "#DA5B0B", "Shell": "#89e051", "Go": "#00ADD8", "Rust": "#dea584",
    "Kotlin": "#A97BFF", "Dart": "#00B4AB", "PHP": "#4F5D95", "C#": "#178600",
}

# palette
BG, BAR, FG, DIM = "#0d1117", "#161b22", "#c9d1d9", "#6e7681"
CYAN, PURPLE, PINK, GREEN, YELLOW = "#22d3ee", "#a78bfa", "#f472b6", "#3fb950", "#e3b341"

FONT = "ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,'Liberation Mono',monospace"
RAMP = " .,:;-=+*#%@"


# ---------------------------------------------------------------- data
def gh(path, token):
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.get(f"https://api.github.com{path}", headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch(args):
    token = os.environ.get("GITHUB_TOKEN")
    user = json.load(open(args.user)) if args.user else gh(f"/users/{LOGIN}", token)
    if args.repos:
        repos = json.load(open(args.repos))
    else:
        repos, page = [], 1
        while True:
            batch = gh(f"/users/{LOGIN}/repos?per_page=100&page={page}&sort=pushed", token)
            repos += batch
            if len(batch) < 100:
                break
            page += 1
    if args.avatar:
        avatar = Image.open(args.avatar)
    else:
        url = user.get("avatar_url") or f"https://github.com/{LOGIN}.png"
        avatar = Image.open(io.BytesIO(requests.get(url + "&s=200" if "?" in url else url + "?s=200", timeout=30).content))
    projects = [r for r in repos if not r.get("fork") and not r.get("archived")
                and r["name"].lower() != LOGIN.lower()]
    projects.sort(key=lambda r: r.get("pushed_at") or "", reverse=True)
    return user, projects, avatar


# ---------------------------------------------------------------- ascii avatar
def ascii_avatar(img, cols=52, rows=26):
    img = img.convert("RGBA")
    side = min(img.size)
    img = img.crop(((img.width - side) // 2, (img.height - side) // 2,
                    (img.width + side) // 2, (img.height + side) // 2))
    # flatten transparency onto the image's own corner colour
    bg = Image.new("RGBA", img.size, img.getpixel((2, 2))[:3] + (255,))
    img = Image.alpha_composite(bg, img).convert("RGB")
    corner = img.getpixel((2, 2))
    small = img.resize((cols, rows), Image.LANCZOS)

    # circular mask (chars are ~2x taller than wide, so the grid is 2:1)
    mask = Image.new("L", (cols * 4, rows * 8), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, cols * 4 - 1, rows * 8 - 1), fill=255)
    mask = mask.resize((cols, rows))

    def dist(a, b):
        return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5

    lines = []
    for y in range(rows):
        row = []
        for x in range(cols):
            if mask.getpixel((x, y)) < 128:
                row.append((" ", None)); continue
            r, g, b = small.getpixel((x, y))
            if dist((r, g, b), corner) < 28:          # background → faint dots
                row.append(("·" if (x + y) % 3 == 0 else " ", DIM)); continue
            lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
            ch = RAMP[max(1, min(len(RAMP) - 1, int(lum * (len(RAMP) - 1) + 0.5)))]
            # lift dark colours so they read on a dark terminal
            lift = lambda c: int(min(255, 70 + c * 0.8))
            q = lambda c: min(255, (c // 24) * 24)
            row.append((ch, "#%02x%02x%02x" % (q(lift(r)), q(lift(g)), q(lift(b)))))
        lines.append(row)
    return lines


# ---------------------------------------------------------------- svg helpers
def t(text, x, y, fill=FG, size=13, weight=400, extra=""):
    return (f'<text x="{x}" y="{y}" fill="{fill}" font-size="{size}" font-weight="{weight}" '
            f'xml:space="preserve" {extra}>{escape(text)}</text>')


def typed(idx, x, y, w, begin, dur, inner):
    """Reveal `inner` left→right like it's being typed (clip-path width animation)."""
    steps = max(4, int(w / 9))
    keys = ";".join(f"{i/steps:.3f}" for i in range(steps + 1))
    vals = ";".join(f"{w*i/steps:.1f}" for i in range(steps + 1))
    return (f'<clipPath id="c{idx}"><rect x="{x-2}" y="{y-16}" width="0" height="22">'
            f'<animate attributeName="width" begin="{begin:.2f}s" dur="{dur:.2f}s" fill="freeze" '
            f'calcMode="discrete" keyTimes="{keys}" values="{vals}"/></rect></clipPath>'
            f'<g clip-path="url(#c{idx})">{inner}</g>')


def fade(begin, inner, dur=0.25):
    return (f'<g opacity="0"><animate attributeName="opacity" from="0" to="1" '
            f'begin="{begin:.2f}s" dur="{dur}s" fill="freeze"/>{inner}</g>')


def ago(iso):
    if not iso:
        return ""
    d = (datetime.now(timezone.utc) - datetime.fromisoformat(iso.replace("Z", "+00:00"))).days
    if d < 1: return "today"
    if d < 30: return f"{d}d ago"
    if d < 365: return f"{d // 30}mo ago"
    return f"{d // 365}y ago"


def clip(s, n):
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


# ---------------------------------------------------------------- build svg
def build_svg(user, projects, avatar):
    W = 980
    CW = 7.8          # approx char width at 13px monospace
    clips = 0
    parts = []

    # header bar
    parts.append(f'<rect width="{W}" height="36" rx="12" fill="{BAR}"/><rect y="24" width="{W}" height="12" fill="{BAR}"/>')
    for i, c in enumerate(["#ff5f57", "#febc2e", "#28c840"]):
        parts.append(f'<circle cx="{22 + i*20}" cy="18" r="6" fill="{c}"/>')
    parts.append(t(f"{LOGIN} — zsh", W / 2, 23, DIM, 12, extra='text-anchor="middle"'))

    # command 1
    y = 66
    cmd = "neofetch --user " + DISPLAY_NAME.lower()
    prompt = f'<tspan fill="{GREEN}">➜</tspan> <tspan fill="{CYAN}">~</tspan> '
    parts.append(f'<text x="24" y="{y}" font-size="13" fill="{FG}" xml:space="preserve">{prompt}</text>')
    clips += 1
    parts.append(typed(clips, 60, y, len(cmd) * CW + 4, 0.3, 1.1, t(cmd, 60, y)))

    # ascii avatar, line by line
    art = ascii_avatar(avatar)
    ay, lh, fs = y + 26, 10.2, 9
    t0 = 1.6
    for i, row in enumerate(art):
        spans, cur, buf = [], None, ""
        for ch, col in row:
            if col != cur and buf:
                spans.append((buf, cur)); buf = ""
            cur = col; buf += ch
        spans.append((buf, cur))
        inner = "".join(f'<tspan fill="{c or BG}">{escape(s)}</tspan>' for s, c in spans)
        line = (f'<text x="24" y="{ay + i*lh:.1f}" font-size="{fs}" xml:space="preserve" '
                f'letter-spacing="0.4">{inner}</text>')
        parts.append(fade(t0 + i * 0.045, line, 0.15))

    # info panel
    ix, iy = 360, ay + 2
    stars = sum(p.get("stargazers_count", 0) for p in projects)
    langs = {}
    for p in projects:
        if p.get("language"):
            langs[p["language"]] = langs.get(p["language"], 0) + 1
    top_langs = " · ".join(k for k, _ in sorted(langs.items(), key=lambda kv: -kv[1])[:4]) or "Python · C++"
    joined = (user.get("created_at") or "")[:4]

    info = [
        ("title", f"{DISPLAY_NAME}@github"),
        ("rule", ""),
        ("OS", "GitHub · since " + joined if joined else "GitHub"),
        ("Host", user.get("location") or "India"),
        ("Repos", f"{user.get('public_repos', len(projects))} public · ★ {stars} stars"),
        ("Followers", str(user.get("followers", 0))),
        ("Langs", top_langs),
        ("Stack", STACK),
        ("rule", ""),
    ] + [(k, v) for k, v in FOCUS]

    t1 = t0 + 0.4
    for j, (k, v) in enumerate(info):
        yy = iy + j * 21
        b = t1 + j * 0.28
        if k == "title":
            n = len(DISPLAY_NAME)
            inner = (f'<text x="{ix}" y="{yy}" font-size="15" font-weight="700" xml:space="preserve">'
                     f'<tspan fill="{CYAN}">{escape(DISPLAY_NAME)}</tspan><tspan fill="{FG}">@</tspan>'
                     f'<tspan fill="{PURPLE}">github</tspan></text>')
            clips += 1
            parts.append(typed(clips, ix, yy, (n + 7) * 9.2, b, 0.5, inner))
        elif k == "rule":
            parts.append(fade(b, f'<rect x="{ix}" y="{yy-8}" width="380" height="1" fill="{DIM}"/>'))
        else:
            label = f"{k}:".ljust(11)
            inner = (f'<text x="{ix}" y="{yy}" font-size="13" xml:space="preserve">'
                     f'<tspan fill="{PINK}" font-weight="700">{escape(label)}</tspan>'
                     f'<tspan fill="{FG}">{escape(clip(v, 46))}</tspan></text>')
            clips += 1
            parts.append(typed(clips, ix, yy, (11 + len(clip(v, 46))) * CW + 6, b, 0.45, inner))

    # colour blocks
    cy = iy + len(info) * 21 + 4
    cb = t1 + len(info) * 0.28
    blocks = "".join(f'<rect x="{ix + k*30}" y="{cy}" width="26" height="14" rx="3" fill="{c}"/>'
                     for k, c in enumerate([BG, "#f85149", GREEN, YELLOW, "#58a6ff", PURPLE, CYAN, FG]))
    parts.append(fade(cb, blocks, 0.4))

    # command 2: projects
    y2 = max(ay + len(art) * lh, cy + 14) + 34
    t2 = cb + 0.6
    cmd2 = "ls -lt ~/projects"
    parts.append(fade(t2 - 0.1, f'<text x="24" y="{y2}" font-size="13" fill="{FG}" xml:space="preserve">{prompt}</text>', 0.1))
    clips += 1
    parts.append(typed(clips, 60, y2, len(cmd2) * CW + 4, t2, 0.8, t(cmd2, 60, y2)))

    shown = projects[:MAX_CARD_PROJECTS]
    py = y2 + 28
    t3 = t2 + 1.0
    if not shown:
        parts.append(fade(t3, t("(no public projects yet — stay tuned)", 24, py, DIM)))
        py += 22
    for k, p in enumerate(shown):
        yy = py + k * 24
        lang = p.get("language") or "—"
        lc = LANG_COLORS.get(lang, PURPLE)
        name = clip(p["name"], 26)
        desc = clip(p.get("description") or "No description yet", 52)
        row = (f'<text x="24" y="{yy}" font-size="13" xml:space="preserve">'
               f'<tspan fill="{DIM}">drwxr-xr-x  </tspan>'
               f'<tspan fill="{CYAN}" font-weight="700">{escape(name.ljust(27))}</tspan>'
               f'<tspan fill="{lc}">● </tspan><tspan fill="{FG}">{escape(lang[:11].ljust(12))}</tspan>'
               f'<tspan fill="{YELLOW}">★{str(p.get("stargazers_count", 0)).rjust(3)}  </tspan>'
               f'<tspan fill="{DIM}">{escape(desc)}</tspan></text>')
        parts.append(fade(t3 + k * 0.18, row, 0.2))
    py += max(1, len(shown)) * 24
    if len(projects) > len(shown):
        parts.append(fade(t3 + len(shown) * 0.18, t(f"… and {len(projects) - len(shown)} more — see the table below", 24, py, DIM, 12)))
        py += 22

    # final prompt + blinking cursor
    tf = t3 + len(shown) * 0.18 + 0.4
    py += 12
    parts.append(fade(tf, f'<text x="24" y="{py}" font-size="13" xml:space="preserve">{prompt}</text>'
                          f'<rect x="60" y="{py-12}" width="8" height="15" fill="{CYAN}">'
                          f'<animate attributeName="opacity" values="1;1;0;0" keyTimes="0;0.5;0.5;1" dur="1s" '
                          f'begin="{tf:.2f}s" repeatCount="indefinite"/></rect>', 0.1))

    H = int(py + 26)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
            f'font-family="{FONT}" role="img" aria-label="{escape(DISPLAY_NAME)} — terminal profile card">'
            f'<defs><linearGradient id="edge" x1="0" y1="0" x2="1" y2="1">'
            f'<stop offset="0" stop-color="{CYAN}"/><stop offset=".5" stop-color="{PURPLE}"/>'
            f'<stop offset="1" stop-color="{PINK}"/></linearGradient></defs>'
            f'<rect x="1" y="1" width="{W-2}" height="{H-2}" rx="12" fill="{BG}" stroke="url(#edge)" stroke-width="1.5"/>'
            + "".join(parts) + "</svg>")


# ---------------------------------------------------------------- readme table
def build_table(projects):
    if not projects:
        return "_No public projects yet — new ones show up here automatically._"
    out = ["| Project | Description | Language | ⭐ | Updated |", "|---|---|---|:-:|---|"]
    for p in projects:
        name = f"[**{p['name']}**]({p['html_url']})"
        if p.get("homepage"):
            name += f" · [demo]({p['homepage']})"
        desc = (p.get("description") or "—").replace("|", "\\|")
        topics = p.get("topics") or []
        if topics:
            desc += "<br>" + " ".join(f"`{x}`" for x in topics[:5])
        out.append(f"| {name} | {desc} | {p.get('language') or '—'} | {p.get('stargazers_count', 0)} | {ago(p.get('pushed_at'))} |")
    return "\n".join(out)


def update_readme(table):
    text = open(README, encoding="utf-8").read()
    new = re.sub(r"(<!-- PROJECTS:START -->).*?(<!-- PROJECTS:END -->)",
                 lambda m: f"{m.group(1)}\n{table}\n{m.group(2)}", text, flags=re.S)
    if new != text:
        open(README, "w", encoding="utf-8").write(new)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--avatar"); ap.add_argument("--repos"); ap.add_argument("--user")
    args = ap.parse_args()
    user, projects, avatar = fetch(args)
    os.makedirs(os.path.dirname(SVG_OUT), exist_ok=True)
    open(SVG_OUT, "w", encoding="utf-8").write(build_svg(user, projects, avatar))
    update_readme(build_table(projects))
    print(f"built card with {len(projects)} projects")


if __name__ == "__main__":
    main()
