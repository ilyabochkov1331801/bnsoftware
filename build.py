#!/usr/bin/env python3
"""Собирает статический сайт из папки apps/ в папку dist/.

Запуск:  python3 build.py
Зависимостей нет — нужен только Python 3.8+.
"""
import html
import json
import re
import shutil
import sys
from datetime import date
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent
APPS_DIR = ROOT / "apps"
OUT = ROOT / "dist"

# Какие документы искать в папке приложения: имя файла (без .md/.html) -> заголовок.
DOCS = {"privacy": "Privacy Policy", "terms": "Terms of Use"}
ICONS = ("icon.png", "icon.jpg", "icon.jpeg", "icon.webp", "icon.svg")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def esc(value):
    return html.escape(str(value), quote=True)


# ---------------------------------------------------------------- markdown

def slugify(text):
    text = re.sub(r"<[^>]+>", "", text).lower()
    text = re.sub(r"[^\w\s-]", "", text).strip()
    return re.sub(r"[\s_-]+", "-", text) or "section"


def emphasis(text):
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__",
                  lambda m: f"<strong>{m.group(1) or m.group(2)}</strong>", text)
    return re.sub(r"(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?![\w*])|(?<![\w_])_(?=\S)(.+?)(?<=\S)_(?![\w_])",
                  lambda m: f"<em>{m.group(1) or m.group(2)}</em>", text)


def inline(text):
    kept = []

    def keep(fragment):
        kept.append(fragment)
        return f"\x00{len(kept) - 1}\x00"

    def link(href, label):
        return keep(f'<a href="{href.replace(chr(34), "%22")}">{label}</a>')

    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", lambda m: keep(f"<code>{m.group(1)}</code>"), text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", lambda m: link(m.group(2), emphasis(m.group(1))), text)
    text = re.sub(r"&lt;(https?://\S+?)&gt;", lambda m: link(m.group(1), m.group(1)), text)
    text = re.sub(r"https?://[^\s<\x00]*[^\s<\x00.,;:!?)]", lambda m: link(m.group(0), m.group(0)), text)
    text = re.sub(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", lambda m: link("mailto:" + m.group(0), m.group(0)), text)
    text = emphasis(text).replace("\x01", "<br>")
    while "\x00" in text:
        text = re.sub(r"\x00(\d+)\x00", lambda m: kept[int(m.group(1))], text)
    return text


BLOCK_HTML = re.compile(
    r"^</?(div|p|h[1-6]|ul|ol|li|table|thead|tbody|tr|td|th|section|article|br|hr"
    r"|details|summary|blockquote|pre|dl|dt|dd)\b", re.I)
HR_RE = re.compile(r"([-*_])( *\1){2,}")


def markdown(src):
    """Небольшой конвертер Markdown: заголовки, абзацы, списки (+1 уровень вложенности),
    цитаты, разделители, **жирный**, *курсив*, `код`, ссылки, автоссылки и e-mail.
    Строки, начинающиеся с блочного HTML-тега, вставляются как есть."""
    out, para, quote, items = [], [], [], []
    seen_ids = {}
    state = {"list": None, "blank": True}

    def close_para():
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
            para.clear()

    def close_list():
        tag = state["list"]
        if not tag:
            return
        lis = []
        for item in items:
            body = inline(" ".join(item["text"]))
            if item["sub"]:
                sub_tag = item["sub"][0][0]
                subs = "".join(f"<li>{inline(t)}</li>" for _, t in item["sub"])
                body += f"<{sub_tag}>{subs}</{sub_tag}>"
            lis.append(f"<li>{body}</li>")
        out.append(f"<{tag}>{''.join(lis)}</{tag}>")
        items.clear()
        state["list"] = None

    def close_quote():
        if quote:
            out.append(f"<blockquote>{markdown(chr(10).join(quote))}</blockquote>")
            quote.clear()

    def close_all():
        close_para()
        close_list()
        close_quote()

    for raw in src.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        s = line.strip()
        indent = len(line) - len(line.lstrip())
        was_blank, state["blank"] = state["blank"], not s
        text = s + ("\x01" if raw.endswith("  ") else "")

        if not s:
            close_para()
            close_quote()
            continue
        if s.startswith(">"):
            close_para()
            close_list()
            quote.append(re.sub(r"^> ?", "", s))
            continue
        close_quote()

        if HR_RE.fullmatch(s):
            close_all()
            out.append("<hr>")
            continue

        m = re.match(r"(?:([-*+])|\d+[.)])\s+(.*)", s)
        if m:
            tag = "ul" if m.group(1) else "ol"
            if state["list"] and indent >= 2 and items:
                items[-1]["sub"].append((tag, m.group(2)))
                continue
            close_para()
            if state["list"] != tag:
                close_list()
            state["list"] = tag
            items.append({"text": [m.group(2)], "sub": []})
            continue

        m = re.match(r"(#{1,6})\s+(.*?)\s*#*$", s)
        if m:
            close_all()
            level, content = len(m.group(1)), inline(m.group(2))
            anchor = slugify(content)
            seen_ids[anchor] = seen_ids.get(anchor, 0) + 1
            if seen_ids[anchor] > 1:
                anchor += f"-{seen_ids[anchor]}"
            out.append(f'<h{level} id="{anchor}">{content}</h{level}>')
            continue

        if BLOCK_HTML.match(s):
            close_all()
            out.append(line)
            continue

        if state["list"] and items and (indent >= 2 or not was_blank):
            items[-1]["text"].append(text)
            continue

        close_list()
        para.append(text)

    close_all()
    return "\n".join(out)


# ---------------------------------------------------------------- pages

def page(site, *, title, body, depth, description="", up=None, wide=False):
    up = "../" * depth if up is None else up
    home = up or "./"
    company = esc(site["company"])
    email = site.get("email", "").strip()
    contact = f'<a href="mailto:{esc(email)}">{esc(email)}</a>' if email else ""
    owner = ", ".join([site.get("legal_name") or site["company"], *site.get("address", [])])
    if site.get("ids"):
        owner += f' · {site["ids"][0][0]} {site["ids"][0][1]}'
    meta = f'<meta name="description" content="{esc(description)}">' if description else ""
    return f"""<!doctype html>
<html lang="{esc(site.get('lang', 'en'))}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
{meta}
<link rel="stylesheet" href="{up}style.css">
</head>
<body{' class="wide"' if wide else ""}>
<header class="site"><div class="wrap"><a class="brand" href="{home}">{company}</a><nav class="nav"><a href="{home}#apps">Apps</a><a href="{home}#about">About</a><a href="{home}#work">Work with us</a><a href="{home}#contact">Contact</a></nav></div></header>
<main><div class="wrap">
{body}
</div></main>
<footer class="site"><div class="wrap"><span>© {date.today().year} {esc(owner)}</span>{contact}</div></footer>
</body>
</html>
"""


def icon_html(app, prefix):
    if app["icon"]:
        return f'<img class="icon" src="{prefix}{esc(app["icon"])}" alt="">'
    return f'<span class="icon" aria-hidden="true">{esc(app["name"][:1].upper())}</span>'


def doc_links(app, prefix):
    return "".join(
        f'<a class="pill" href="{prefix}{key}/">{esc(DOCS[key])}</a>' for key in app["docs"])


def store_html(app):
    """Ссылка на App Store или пометка «скоро», если store_url не задан."""
    if app["store_url"]:
        return f'<a class="pill store" href="{esc(app["store_url"])}">App Store</a>'
    return '<span class="soon">Coming soon to the App Store</span>'


def descriptions(app, cls=""):
    return f'<p class="{cls}">{esc(app["description"])}</p>' if app["description"] else ""


def features(app, limit=None):
    items = app["features"][:limit] if limit else app["features"]
    lis = "".join(f"<li>{esc(f)}</li>" for f in items)
    return f'<ul class="features">{lis}</ul>' if lis else ""


def tint(color):
    """Атрибуты карточки, окрашенной в цвет приложения или услуги."""
    return f' style="--tint: {esc(color)}"' if color else ""


def mailto(email, subject=""):
    href = f"mailto:{email}" + (f"?subject={quote(subject)}" if subject else "")
    return esc(href)


def company_html(site):
    """Разделы главной под списком приложений: About (команда), Work with us, Contact (с реквизитами)."""
    email = site.get("email", "").strip()
    paras = "".join(f"<p>{esc(t)}</p>" for t in site.get("about", []))
    people = "".join(f"""
<article class="person tinted"{tint(m.get("color"))}>
  {f'<img class="photo" src="{esc(m["photo"])}" alt="{esc(m["name"])}" width="112" height="112">' if m.get("photo") else ""}
  <div>
  <h3>{esc(m["name"])}</h3>
  <p class="role">{esc(m["role"])}</p>
  <p>{esc(m["bio"])}</p>
  <ul class="features">{"".join(f"<li>{esc(h)}</li>" for h in m.get("highlights", []))}</ul>
  {f'<a class="pill cta" href="{esc(m["cv"])}" download>Download CV (PDF)</a>' if m.get("cv") else ""}
  </div>
</article>""" for m in site.get("team", []))

    services = "".join(f"""
<article class="service tinted"{tint(sv.get("color"))}>
  <h3>{esc(sv["title"])}</h3>
  <p>{esc(sv["text"])}</p>
  <ul class="features">{"".join(f"<li>{esc(i)}</li>" for i in sv.get("items", []))}</ul>
  <a class="pill cta" href="{mailto(email, sv.get("subject", ""))}">{esc(sv["button"])}</a>
</article>""" for sv in site.get("services", []))
    work = f"""<section id="work" class="block">
<h2 class="section-title">Work with us</h2>
{f'<p>{esc(site["services_intro"])}</p>' if site.get("services_intro") else ""}
<div class="services">{services}</div>
</section>""" if services else ""

    legal = ", ".join([site.get("legal_name") or site["company"], *site.get("address", [])])
    ids = " · ".join(f"{label} {value}" for label, value in site.get("ids", []))
    contact = (f'<p>For support or feedback about our apps, a project or lessons, email us at '
               f'<a href="{mailto(email)}">{esc(email)}</a>. We read every message.</p>') if email else ""
    return f"""<section id="about" class="block">
<h2 class="section-title">About us</h2>
{paras}
{f'<div class="team">{people}</div>' if people else ""}
</section>
{work}
<section id="contact" class="block">
<h2 class="section-title">Contact</h2>
{contact}
<p class="legal">{esc(legal)}<br>{esc(ids)}</p>
</section>"""


def read_doc(path):
    """Возвращает (заголовок или None, HTML) для .md или .html файла."""
    src = path.read_text(encoding="utf-8")
    if path.suffix == ".md":
        m = re.match(r"\s*#\s+(.+?)\s*#*\s*(?:\n|$)", src)
        if m:
            return m.group(1), markdown(src[m.end():])
        return None, markdown(src)
    body = re.search(r"<body[^>]*>(.*)</body>", src, re.S | re.I)
    src = body.group(1) if body else src
    m = re.match(r"\s*<h1[^>]*>(.*?)</h1>", src, re.S | re.I)
    if m:
        return re.sub(r"<[^>]+>", "", m.group(1)).strip(), src[m.end():]
    return None, src


def load_apps():
    apps = []
    if not APPS_DIR.is_dir():
        return apps
    for folder in sorted(APPS_DIR.iterdir()):
        if not folder.is_dir() or folder.name.startswith(("_", ".")):
            continue
        if not SLUG_RE.match(folder.name):
            print(f"  ! пропускаю apps/{folder.name}: имя папки должно быть латиницей "
                  f"в нижнем регистре, цифрами и дефисами (например my-app)", file=sys.stderr)
            continue
        meta_file = folder / "app.json"
        meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
        docs = {}
        for key in DOCS:
            for ext in (".md", ".html"):
                if (folder / f"{key}{ext}").exists():
                    docs[key] = folder / f"{key}{ext}"
                    break
        if not docs:
            print(f"  ! пропускаю apps/{folder.name}: нет privacy.md / terms.md", file=sys.stderr)
            continue
        apps.append({
            "slug": folder.name,
            "dir": folder,
            "name": meta.get("name") or folder.name.replace("-", " ").title(),
            "description": meta.get("description", ""),
            "tagline": meta.get("tagline", ""),
            "color": meta.get("color", ""),
            "about": meta.get("about", ""),
            "features": meta.get("features", []),
            "price": meta.get("price", ""),
            "store_url": meta.get("store_url", ""),
            "icon": next((i for i in ICONS if (folder / i).exists()), None),
            "docs": docs,
        })
    return sorted(apps, key=lambda a: a["name"].lower())


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build():
    site = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
    apps = load_apps()
    company = site["company"]

    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir()
    shutil.copy(ROOT / "style.css", OUT / "style.css")
    if (ROOT / "assets").is_dir():  # фото и прочие файлы для главной
        shutil.copytree(ROOT / "assets", OUT / "assets")
    (OUT / ".nojekyll").touch()
    if (ROOT / "_redirects").exists():  # Cloudflare Pages redirects
        shutil.copy(ROOT / "_redirects", OUT / "_redirects")

    # Главная: список приложений
    if apps:
        cards = "".join(f"""
<article class="app tinted"{tint(a["color"])}>
  <a href="{a['slug']}/">{icon_html(a, a['slug'] + '/')}</a>
  <div class="app-body">
    <h2><a href="{a['slug']}/">{esc(a['name'])}</a></h2>
    {descriptions(a)}
    {features(a, 3)}
    <div class="links">{doc_links(a, a['slug'] + '/')}{store_html(a)}</div>
  </div>
</article>""" for a in apps)
        listing = f'''<section class="hero">
<h1>{esc(site.get("headline") or company)}</h1>
{f'<p class="lead">{esc(site["intro"])}</p>' if site.get("intro") else ""}
</section>
<section id="apps">
<h2 class="section-title">Our apps</h2>
<div class="apps">{cards}</div>
</section>'''
    else:
        listing = '<p class="empty">No apps yet.</p>'
    write(OUT / "index.html", page(
        site, depth=0, title=company, wide=True,
        description=site.get("intro") or f"Apps by {company}.",
        body=listing + company_html(site)))

    email = site.get("email", "").strip()
    # 404 открывается по любому адресу, поэтому ссылки в нём от корня сайта
    write(OUT / "404.html", page(
        site, depth=0, up="/", title=f"Page not found — {company}",
        body='<h1>Page not found</h1><p class="lead">This page does not exist. '
             '<a href="/">Go to the home page</a> to see our apps.</p>'))

    for app in apps:
        slug, name = app["slug"], app["name"]
        out_dir = OUT / slug
        if app["icon"]:
            out_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy(app["dir"] / app["icon"], out_dir / app["icon"])

        # Страница приложения
        write(out_dir / "index.html", page(
            site, depth=1, title=f"{name} — {company}", description=app["description"],
            body=f"""<nav class="crumbs"><a href="../">{esc(company)}</a></nav>
<div class="app-hero tinted"{tint(app["color"])}>
<div class="app-head">{icon_html(app, '')}<div>
<h1>{esc(name)}</h1>
{f'<p class="eyebrow">{esc(app["tagline"])}</p>' if app["tagline"] else ""}
{descriptions(app, "lead")}
</div></div>
<div class="links big">{doc_links(app, '')}{store_html(app)}</div>
</div>
{f'<p class="app-about">{esc(app["about"])}</p>' if app["about"] else ""}
{f'<h2 class="section-title">Features</h2><div class="tint-scope"{tint(app["color"])}>{features(app)}</div>' if app["features"] else ""}
{f'<h2 class="section-title">Price</h2><p>{esc(app["price"])}</p>' if app["price"] else ""}
<h2 class="section-title">Support</h2>
<p>Questions or feedback about {esc(name)}? Email us at <a href="mailto:{esc(email)}">{esc(email)}</a>.
{esc(name)} is developed and published by {esc(site.get("legal_name") or company)}, {esc(", ".join(site.get("address", [])))}.</p>"""))

        # Документы
        for key, path in app["docs"].items():
            heading, content = read_doc(path)
            heading = heading or DOCS[key]
            others = "".join(
                f'<a href="../{k}/">{esc(DOCS[k])}</a>' for k in app["docs"] if k != key)
            write(out_dir / key / "index.html", page(
                site, depth=2, title=f"{heading} — {name}",
                description=f"{DOCS[key]} for {name} by {company}.",
                body=f"""<nav class="crumbs"><a href="../../">{esc(company)}</a><span>/</span><a href="../">{esc(name)}</a></nav>
<h1>{esc(heading)}</h1>
<article class="doc">
{content}
</article>
{f'<nav class="doc-nav">See also: {others}</nav>' if others else ''}"""))

    print(f"Готово: {len(apps)} прилож. → dist/")
    for app in apps:
        for key in app["docs"]:
            print(f"  /{app['slug']}/{key}/")


if __name__ == "__main__":
    build()
