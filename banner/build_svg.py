"""banner.html의 배치를 그대로 재서 움직이는 SVG 배너(라이트·다크)를 만든다.

정건희(github.com/donasman)의 배너 생성 스크립트를 바탕으로, 색·내용과 재는 방법(playwright 대신
설치된 Chrome의 headless --dump-dom)만 바꿨다.

실행: python banner/build_svg.py
- 글꼴은 처음 실행할 때 banner/.fonts/ 에 받아 두고, 쓰인 글자만 잘라 SVG 안에 넣는다.
- 움직임: 선이 한 번 그려진 뒤, 경험을 하나씩 돌아가며 그 경험에 쓴 기술과 선을 강조한다.
  동작 줄이기 설정을 켠 환경에서는 움직이지 않는다.
"""
import base64
import html
import io
import json
import os
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

HERE = Path(__file__).parent
OUT = HERE.parent / "assets"
FONTS = HERE / ".fonts"
FONT_SRC = {
    "sans": ("WantedSansVariable.ttf",
             "https://cdn.jsdelivr.net/gh/wanteddev/wanted-sans@v1.0.3/packages/wanted-sans/fonts/variable/WantedSansVariable.ttf"),
    "mono": ("jetbrains-mono-500.woff",
             "https://cdn.jsdelivr.net/npm/@fontsource/jetbrains-mono@5.0.20/files/jetbrains-mono-latin-500-normal.woff"),
}

THEMES = {
    "light": dict(ink="#1f2328", muted="#59636e", rule="#d1d9e0", accent="#1d5fae", accent_ink="#174e91", tint="#e4edf8"),
    "dark": dict(ink="#e6edf3", muted="#9198a1", rule="#3d444d", accent="#6ea8ee", accent_ink="#8fbdf3", tint="#15263a"),
}

# 시간(초)
DRAW_STAGGER = 0.06   # 기술 행마다 선이 그려지기 시작하는 간격
DRAW_DUR = 0.9
CYCLE_DELAY = 2.2     # 첫 강조가 시작되는 시점
NEUTRAL = 1.4         # 강조 사이클 앞의 전체 보기 구간
WINDOW = 2.3          # 경험 하나를 강조하는 시간
RAMP = 0.3


EXP_ORDER = ["hansotbap", "fantasteel", "opic", "stock", "bankmode"]


def ensure_fonts():
    FONTS.mkdir(exist_ok=True)
    paths = {}
    for key, (name, url) in FONT_SRC.items():
        p = FONTS / name
        if not p.exists():
            print("download", url)
            urllib.request.urlretrieve(url, p)
        paths[key] = p
    return paths


def subset_font(path, text, flavor="woff"):
    opts = subset.Options()
    opts.flavor = flavor
    opts.layout_features = ["*"]
    opts.name_IDs = ["*"]
    opts.notdef_outline = True
    font = TTFont(path)
    sub = subset.Subsetter(opts)
    sub.populate(text=text)
    sub.subset(font)
    buf = io.BytesIO()
    font.flavor = flavor
    font.save(buf)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def find_chrome():
    for p in (os.environ.get("CHROME"),
              r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
              shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chrome")):
        if p and Path(p).exists():
            return p
    raise SystemExit("Chrome을 찾지 못했습니다. CHROME 환경 변수로 경로를 알려 주세요.")


def measure():
    url = (HERE / "banner.html").resolve().as_uri() + "#measure"
    out = subprocess.run(
        [find_chrome(), "--headless=new", "--disable-gpu", "--window-size=900,600",
         "--virtual-time-budget=15000", "--dump-dom", url],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    ).stdout
    m = re.search(r'<pre id="measure">(.*?)</pre>', out, re.S)
    if not m:
        raise SystemExit("배너를 재지 못했습니다(글꼴을 받지 못했을 수 있습니다).")
    data = json.loads(html.unescape(m.group(1)))
    if not data.pop("fontsOk", False):
        raise SystemExit("웹 글꼴이 아직 안 받아진 상태로 재었습니다. 다시 실행해 주세요.")
    return data


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def keyframes(name, members, prop_values):
    """members: 강조되는 경험 인덱스 집합. prop_values: {prop: (N, A, D)}"""
    cycle = NEUTRAL + WINDOW * len(EXP_ORDER) + RAMP
    points = [(0.0, "N"), (NEUTRAL - RAMP, "N")]
    for k in range(len(EXP_ORDER)):
        s = NEUTRAL - RAMP + WINDOW * k
        state = "A" if k in members else "D"
        points.append((s + RAMP, state))
        points.append((s + WINDOW, state))
    points.append((cycle, "N"))
    idx = {"N": 0, "A": 1, "D": 2}
    lines = [f"@keyframes {name} {{"]
    for t, st in points:
        decl = "; ".join(f"{prop}: {vals[idx[st]]}" for prop, vals in prop_values.items())
        lines.append(f"  {t / cycle * 100:.3f}% {{ {decl} }}")
    lines.append("}")
    return "\n".join(lines), cycle


def build(data, fonts_b64, theme):
    c = THEMES[theme]
    W, H = round(data["width"]), round(data["height"])
    skills_ent, exps_ent = data["entities"]
    exp_rows = {r["id"]: r for r in exps_ent["rows"]}
    exp_index = {e: i for i, e in enumerate(EXP_ORDER)}

    css, kf_done = [], {}

    def kf(kind, members, props):
        key = (kind, tuple(sorted(members)))
        if key not in kf_done:
            name = f"{kind}{len(kf_done)}"
            block, cycle = keyframes(name, set(members), props)
            css.append(block)
            kf_done[key] = (name, cycle)
        return kf_done[key]

    def cyc(kind, members, props, extra=""):
        name, cycle = kf(kind, members, props)
        anim = f"{name} {cycle:.2f}s linear {CYCLE_DELAY}s infinite"
        return f'style="animation: {extra}{anim}"'

    body = []
    # 선과 끝점
    line_props = {"opacity": (0.42, 1, 0.12), "stroke-width": ("1.15px", "1.9px", "1.15px")}
    for i, row in enumerate(skills_ent["rows"]):
        x1 = skills_ent["box"]["x"] + skills_ent["box"]["w"]
        y1 = row["y"] + row["h"] / 2
        for eid in row["rel"].split():
            er = exp_rows[eid]
            x2, y2 = er["x"], er["y"] + er["h"] / 2
            dx = (x2 - x1) * 0.5
            d = f"M{x1:.1f},{y1:.1f} C{x1 + dx:.1f},{y1:.1f} {x2 - dx:.1f},{y2:.1f} {x2:.1f},{y2:.1f}"
            draw = f"draw {DRAW_DUR}s cubic-bezier(.3,.7,.3,1) {i * DRAW_STAGGER:.2f}s both, "
            body.append(f'<path class="ln" pathLength="1" d="{d}" {cyc("ln", [exp_index[eid]], line_props, draw)}/>')
    for row in skills_ent["rows"]:
        members = [exp_index[e] for e in row["rel"].split()]
        cx = skills_ent["box"]["x"] + skills_ent["box"]["w"]
        body.append(f'<circle class="dot" cx="{cx:.1f}" cy="{row["y"] + row["h"] / 2:.1f}" r="2" {cyc("dot", members, {"opacity": (1, 1, 0.3)})}/>')
    for eid in EXP_ORDER:
        er = exp_rows[eid]
        body.append(f'<circle class="dot" cx="{er["x"]:.1f}" cy="{er["y"] + er["h"] / 2:.1f}" r="2.6" {cyc("dot", [exp_index[eid]], {"opacity": (1, 1, 0.3)})}/>')

    # 개체 상자, 강조 배경, 구분선
    for n, ent in enumerate((skills_ent, exps_ent)):
        b = ent["box"]
        clip = f"clip{n}"
        body.append(f'<clipPath id="{clip}"><rect x="{b["x"]:.1f}" y="{b["y"]:.1f}" width="{b["w"]:.1f}" height="{b["h"]:.1f}" rx="7"/></clipPath>')
        body.append(f'<g clip-path="url(#{clip})">')
        for row in ent["rows"]:
            members = [exp_index[e] for e in row["rel"].split()] if row["rel"] else [exp_index[row["id"]]]
            body.append(f'<rect class="hl" x="{row["x"]:.1f}" y="{row["y"]:.1f}" width="{row["w"]:.1f}" height="{row["h"]:.1f}" '
                        f'{cyc("hl", members, {"opacity": (0, 1, 0)})}/>')
        body.append("</g>")
        body.append(f'<line class="rule" x1="{b["x"]:.1f}" x2="{b["x"] + b["w"]:.1f}" y1="{ent["headBottom"] - 0.5:.1f}" y2="{ent["headBottom"] - 0.5:.1f}"/>')
        for row in ent["rows"][1:]:
            body.append(f'<line class="rule" x1="{b["x"]:.1f}" x2="{b["x"] + b["w"]:.1f}" y1="{row["y"] + 0.5:.1f}" y2="{row["y"] + 0.5:.1f}"/>')
        body.append(f'<rect class="box" x="{b["x"] + 0.5:.1f}" y="{b["y"] + 0.5:.1f}" width="{b["w"] - 1:.1f}" height="{b["h"] - 1:.1f}" rx="6.5"/>')

    # 글자
    for t in data["texts"]:
        fam = "m" if t["mono"] else "s"
        attrs = f'x="{t["x"]:.2f}" y="{t["y"]:.2f}" class="{fam} {t["color"]}" font-size="{t["size"]}" font-weight="{t["weight"]}"'
        if t["ls"]:
            attrs += f' letter-spacing="{t["ls"]:.3f}"'
        if t["kind"] == "skill":
            members = [exp_index[e] for e in t["rel"].split()]
            attrs += " " + cyc("tx", members, {"fill": (c["ink"], c["accent_ink"], c["muted"])})
        elif t["kind"] == "xtitle":
            attrs += " " + cyc("tx", [exp_index[t["id"]]], {"fill": (c["ink"], c["accent_ink"], c["muted"])})
        body.append(f"<text {attrs}>{esc(t['text'])}</text>")

    style = f"""
@font-face {{ font-family: "B Sans"; src: url(data:font/woff;base64,{fonts_b64['sans']}) format("woff"); font-weight: 400 1000; }}
@font-face {{ font-family: "B Mono"; src: url(data:font/woff;base64,{fonts_b64['mono']}) format("woff"); font-weight: 500; }}
.s {{ font-family: "B Sans", "Apple SD Gothic Neo", "Malgun Gothic", sans-serif; }}
.m {{ font-family: "B Mono", ui-monospace, monospace; }}
.ink {{ fill: {c['ink']}; }} .muted {{ fill: {c['muted']}; }} .accent {{ fill: {c['accent']}; }}
.box {{ fill: none; stroke: {c['rule']}; stroke-width: 1; }}
.rule {{ stroke: {c['rule']}; stroke-width: 1; }}
.hl {{ fill: {c['tint']}; opacity: 0; }}
.ln {{ fill: none; stroke: {c['accent']}; stroke-width: 1.15px; opacity: .42; stroke-dasharray: 1; stroke-dashoffset: 0; }}
.dot {{ fill: {c['accent']}; }}
@keyframes draw {{ from {{ stroke-dashoffset: 1; }} to {{ stroke-dashoffset: 0; }} }}
{chr(10).join(css)}
@media (prefers-reduced-motion: reduce) {{ * {{ animation: none !important; }} }}
"""
    label = "김동건, AI가 틀리는 날에도 현장은 멈추지 않게 만드는 AI 서비스 개발자. 기술 15개를 프로젝트 5건에 연결한 관계도"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="{label}">\n'
            f"<title>{label}</title>\n<style>{style}</style>\n" + "\n".join(body) + "\n</svg>\n")


def main():
    fonts = ensure_fonts()
    data = measure()
    sans_text = "".join(t["text"] for t in data["texts"] if not t["mono"])
    mono_text = "".join(t["text"] for t in data["texts"] if t["mono"])
    fonts_b64 = {"sans": subset_font(fonts["sans"], sans_text), "mono": subset_font(fonts["mono"], mono_text)}
    for theme in THEMES:
        svg = build(data, fonts_b64, theme)
        out = OUT / f"banner-{theme}.svg"
        out.write_text(svg, encoding="utf-8")
        print("saved", out, f"{len(svg.encode('utf-8')) / 1024:.0f} KB")


if __name__ == "__main__":
    main()
