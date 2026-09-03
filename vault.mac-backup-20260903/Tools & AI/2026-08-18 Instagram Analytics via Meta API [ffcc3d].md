---
source: https://www.instagram.com/reel/DcL_0CDs0hn/
date: 2026-08-18
type: reel-note
folder: Tools & AI
topics: [ai-tools, productivity, content-creation]
content_type: tutorial
kind: video
categories: [Tools & AI, Content & Creator]
status: inbox
review_question: Why must you store your Meta API key in a .env file instead of pasting it directly into the AI chat?
---

# Instagram Analytics via Meta API

**Useful for:** Creators who want Instagram stats (ads, reels, stories) pulled automatically instead of entering data into spreadsheets manually.

## Steps
1. Choose an AI assistant to write your scripts — Claude or Codex both work.
2. Create a Meta Business Portfolio and link the Instagram accounts you want to track.
3. On Meta for Developers, click «Создать приложение» (Create App) and tie it to that Business Portfolio.
4. Open the «Сценарии работы» (Use Cases) tab and grant the app the required permissions (list appears on screen).
5. Back in Business Portfolio, add the new app to System Users and grant it full object access.
6. Click «Сгенерировать маркер» (Generate Token), enable the needed permissions, and copy the API key — never share it.
7. On your computer, create a project folder and put a .env file inside it with your API key (e.g. API_KEY=***…) — this keeps the key off AI servers.
8. Start an AI session, point it at the project folder, and ask it to write scripts that pull any stat you want via the API key.

## Recommended
- [ ] ⚠️ [Meta for Developers](https://developers.facebook.com) — Meta (URL is well-known canonical Meta developer portal; could not confirm via search (search tool blocked this session).)
- [ ] ⚠️ [Instagram Graph API](https://developers.facebook.com/docs/instagram-api/) — Meta (Standard canonical docs path; could not confirm via live search.)
- [ ] ⚠️ [Claude](https://claude.ai) — Anthropic (Well-known canonical URL; search blocked this session.)
- [ ] ⚠️ [Codex](https://openai.com/codex) — OpenAI (Speaker mentions it as an alternative AI for writing scripts; product status in 2026 unclear, could not verify via live search.)

**Why save:** Concrete step-by-step walkthrough for building a fully automated Instagram analytics dashboard via the Meta Graph API — no spreadsheet entry ever again.

**Original:** https://www.instagram.com/reel/DcL_0CDs0hn/
#instagram-api #automation #analytics

## Transcript

Все топовые спецы уже давно сделали себе такие центры аналитики по инстаграм-аккаунтам, поэтому давай я и тебе быстренько покажу, как это все дело настраивается. Лично я один раз себе все это сделал и кайфую уже полгода, больше вообще не ввожу никакие данные вручную по таблицам, они все появляются автоматически, с нужными мне показателями, отображаются по рекламе, по релсам, по сторис. Короче, очень удобно смотреть, что тебе для этого нужно. Во-первых, нужна нейронка, чтобы написать скрипты. Подойдет и клод, и кодекс, это вообще абсолютно не важно, пользуйся тем, что тебе больше нравится. Следующим пунктом нам нужно создать бизнес-портфолио и связать его с теми инстаграм-аккаунтами, которые ты хочешь отслеживать. После того, как ты это все сделаешь, переходишь по ссылке и жмешь на кнопку «Создать приложение», после чего это самое приложение привяжешь к своему бизнес-портфолио, которое я только что создал. Следующим шагом попадаем на вкладку «Сценарии работы» и даем приложению нужное для этой работы разрешение. Список разрешений появился прямо сейчас на экране. Теперь обратно возвращаемся в бизнес-портфолио, добавляем созданное приложение уже в список системных пользователей и даем ему к объектам все нужные доступы. И последнее, жмем вот эту кнопку «Сгенерировать маркер», включаем нужное разрешение и получаем API-ключ, который как раз таки и является прямым доступом к твоим инстаграм-аккаунтам, поэтому никому его не отдавай. Дальше уже на своем компе создаем папку с проектом, абсолютно любую, в нее закидываем файл с расширением .env и строку внутрь этого файла, вот типа такой, только вместо звездочек добавь свой ключ API. Это нужно для безопасности, чтобы твой ключ не ушел на сервера нейронки. Ну и все, теперь можешь запускать сессию с нейронкой, давать ей доступ к этой папке, просить ее забрать любую статистику по ключу и начинать создавать скрипты с полноценной статистикой, аналитикой, как это выглядит у меня.


## Caption

Делаем всё по инструкции из ролика, забираем ключ и наслаждаемся жизнью без таблиц, но с полным контролем над статистикой и крутейшей аналитикой как у лучших специалистов сегодня.

Кому интересны такие автоматизации для развития личного бренда и инфобиза, подписывайтесь на тг-канал.

Ссылка в шапке профиля.
