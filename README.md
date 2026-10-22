# B&N Software

Простой статический сайт с Privacy Policy и Terms of Use для мини-приложений B&N Software.
Без фреймворков и зависимостей: документы пишутся в Markdown, скрипт `build.py` собирает из них HTML.

## Как устроено

```
site.json                 название компании, контактный e-mail, язык
apps/
  my-app/                 одна папка = одно приложение (имя папки = адрес на сайте)
    app.json              название, описание (description) и ссылка на App Store
                          (store_url; пока пусто — показывается «Coming soon to the App Store»)
    privacy.md            Privacy Policy   (или privacy.html)
    terms.md              Terms of Use     (или terms.html)
    icon.png              иконка (необязательно; .png/.jpg/.webp/.svg)
build.py                  сборка сайта в dist/
style.css                 оформление
```

После сборки у каждого приложения появляются адреса, которые можно указывать в App Store, Google Play, Telegram (BotFather) и т. д.:

```
https://bnsoftware.org/my-app/privacy/
https://bnsoftware.org/my-app/terms/
```

## Добавить новое приложение

1. Скопируйте папку `apps/daystamp` и переименуйте её, например в `apps/habit-tracker`
   (только латиница в нижнем регистре, цифры и дефисы).
2. В `app.json` впишите название и короткое описание.
3. Замените текст в `privacy.md` и `terms.md` своим. Первая строка `# ...` станет заголовком страницы.
   Если политика уже есть в виде HTML (например, из генератора), положите её как `privacy.html` —
   она вставится как есть.
4. Соберите сайт и проверьте (см. ниже), затем опубликуйте.

Папки, имя которых начинается с `_`, пропускаются — удобно для черновиков.

В `site.json` укажите `email` и `legal` (юрлицо, адрес, IČO) — они появятся в подвале каждой страницы.

## Сборка и просмотр на своём компьютере

```bash
python3 build.py
```

```bash
python3 -m http.server 8000 -d dist
```

Затем откройте http://localhost:8000.

## Публикация

Сайт размещается на Cloudflare Pages по адресу https://bnsoftware.org и пересобирается сам при каждом push в `main`.

Первичная настройка (один раз):

1. Cloudflare → **Workers & Pages → Create → Pages → Connect to Git**, выбрать репозиторий `bnsoftware`.
2. Build command: `python3 build.py`, Build output directory: `dist`.
3. В проекте: **Custom domains → Set up a domain** → `bnsoftware.org` (и при желании `www.bnsoftware.org`).

Новый документ можно добавить прямо в веб-интерфейсе GitHub: **Add file → Upload files** в папку `apps/<имя>/` — сайт обновится сам через минуту.

## Поддерживаемый Markdown

Заголовки `#`–`######`, абзацы, списки `-` / `1.` (с одним уровнем вложенности), `**жирный**`, `*курсив*`,
ссылки `[текст](https://...)`, `> цитаты`, разделитель `---`. Ссылки и e-mail в тексте становятся кликабельными сами.
Строки, начинающиеся с HTML-тега (`<table>`, `<div>` …), вставляются без изменений.

> Тексты в `daystamp` написаны под это приложение и не являются юридической консультацией. Для нового приложения проверьте их под его функции
> и требования площадок (App Store, Google Play, Telegram).
