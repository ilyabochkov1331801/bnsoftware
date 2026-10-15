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

def page(site, *, title, body, depth, description=""):
    up = "../" * depth
    home = up or "./"
    company = esc(site["company"])
    email = site.get("email", "").strip()
    contact = f'<a href="mailto:{esc(email)}">{esc(email)}</a>' if email else ""
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
<body>
<header class="site"><div class="wrap"><a class="brand" href="{home}">{company}</a></div></header>
<main><div class="wrap">
{body}
</div></main>
<footer class="site"><div class="wrap"><span>© {date.today().year} {company}</span>{contact}</div></footer>
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
    (OUT / ".nojekyll").touch()

    # Главная: список приложений
    if apps:
        cards = "".join(f"""
<article class="app">
  <a href="{a['slug']}/">{icon_html(a, a['slug'] + '/')}</a>
  <div class="app-body">
    <h2><a href="{a['slug']}/">{esc(a['name'])}</a></h2>
    {f"<p>{esc(a['description'])}</p>" if a['description'] else ""}
    <div class="links">{doc_links(a, a['slug'] + '/')}</div>
  </div>
</article>""" for a in apps)
        listing = f'<section class="apps">{cards}</section>'
    else:
        listing = '<p class="empty">Пока нет ни одного приложения — добавьте папку в apps/.</p>'
    write(OUT / "index.html", page(
        site, depth=0, title=f"Legal — {company}",
        description=f"Privacy policies and terms of use for apps by {company}.",
        body=f"""<p class="eyebrow">{esc(company)}</p>
<h1>Privacy policies &amp; terms</h1>
<p class="lead">Legal documents for the apps made by {esc(company)}.</p>
{listing}"""))

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
<div class="app-head">{icon_html(app, '')}<div>
<h1>{esc(name)}</h1>
{f'<p class="lead">{esc(app["description"])}</p>' if app['description'] else ''}
</div></div>
<div class="links big">{doc_links(app, '')}</div>"""))

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
