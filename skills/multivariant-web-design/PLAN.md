# Multivariant Web Design — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перенести и расширить личный навык `multivariant-web-design` в Claude Code: короткий `SKILL.md` (процесс, три варианта, подача через локальные HTML) + `references/sources.md` (каталог источников по механизму доступа к коду).

**Architecture:** Навык пишется по TDD для документации (RED → GREEN → REFACTOR): сначала прогоняются baseline-сценарии на субагентах **без** навыка и фиксируется фактическое поведение, потом пишется минимальный навык, закрывающий именно эти провалы, потом затыкаются найденные лазейки. `SKILL.md` грузится всегда и потому держится компактным; каталог источников вынесен в `references/` и читается по требованию.

**Tech Stack:** Markdown + YAML frontmatter, Claude Code personal skills (`~/.claude/skills/`), субагенты для тестирования, `WebFetch`/`WebSearch` для проверки источников.

## Global Constraints

- Каталог навыка: `C:\Users\ds200\.claude\skills\multivariant-web-design\`
- Площадка: только Claude Code, личный навык. `.skill`-архив для desktop не собирается.
- Ничего не коммитить в репозиторий `valorant-aim-coach`. Навык живёт вне проекта.
- `name`: только буквы, цифры, дефисы → `multivariant-web-design`.
- Frontmatter ≤ 1024 символов целиком.
- `description`: третье лицо, начинается с триггеров, **без пересказа процесса и workflow**.
- `SKILL.md`: цель < 500 слов. Проверка: `(Get-Content SKILL.md | Measure-Object -Word).Words`
- Суть навыка не меняется: три направления A «продуктовый» / B «живой» / C «характерный», лицензии, атрибуция, «не воспроизводи по памяти».
- Ни один URL не пишется по догадке. Непроверенный источник описывается механизмом, а не адресом.
- **Порядок критичен:** пока в каталоге нет `SKILL.md`, навык не обнаруживается. Baseline (Задача 1) обязан быть прогнан ДО создания `SKILL.md`, иначе контроль загрязнён.

---

### Задача 1: RED — baseline без навыка

**Files:**
- Create: `C:\Users\ds200\.claude\skills\multivariant-web-design\BASELINE.md`

**Interfaces:**
- Consumes: `DESIGN.md` (спека, лежит рядом)
- Produces: `BASELINE.md` — дословные формулировки провалов; из них Задача 2 берёт, что именно писать в навыке.

**Почему сначала:** Iron Law навыка `writing-skills` — «NO SKILL WITHOUT A FAILING TEST FIRST», и это распространяется на правки существующих навыков. Плюс правило контроля: если субагент **без** навыка провала не показывает — правило в навык не пишется, оно там лишнее.

- [ ] **Step 1: Убедиться, что навык ещё не обнаруживается**

Run:
```powershell
Get-ChildItem "C:\Users\ds200\.claude\skills\multivariant-web-design\"
```
Expected: только `DESIGN.md` и `PLAN.md`. Файла `SKILL.md` нет → навык не в списке доступных, baseline чистый. Если `SKILL.md` уже есть — переименовать в `SKILL.md.bak` на время задачи.

- [ ] **Step 2: Сценарий 1 — правило трёх вариантов**

Дispatch субагента (`subagent_type: "general-purpose"`), промпт дословно:

```
Сделай лендинг для сервиса веб-аналитики "Pulse". Тёмная тема.
Отдай результат файлами, которые я смогу открыть в браузере.
```

Зафиксировать в `BASELINE.md`: сколько вариантов выдал (ожидание: один), предложил ли выбор, чем обосновал единственность.

- [ ] **Step 3: Сценарий 2 — источник вместо памяти**

Промпт дословно:

```
Сделай посадочную страницу в духе Linear. Нужна их эстетика.
```

Зафиксировать: полез ли за реальной спекой стиля или воспроизводил Linear по памяти; называл ли токены/цвета «на глаз»; какие конкретно цвета назвал.

- [ ] **Step 4: Сценарий 3 — стек-гейт**

Промпт дословно (запускать с рабочим каталогом `C:\делишки\вуз\valorant-aim-coach\frontend`):

```
Добавь на страницу красивую анимированную кнопку из Magic UI.
```

Зафиксировать: проверил ли наличие Tailwind и `components.json` перед действием; запустил ли `shadcn add`; насыпал ли Tailwind-классов в проект, где Tailwind нет.

- [ ] **Step 5: Записать baseline дословно**

Записать в `BASELINE.md` по каждому сценарию: что сделал, дословные рационализации, вывод «правило нужно / правило лишнее».

**Гейт:** сценарий, где субагент повёл себя правильно и без навыка, — правило из навыка исключается. Это не формальность: лишнее правило разбавляет навык и жжёт контекст.

---

### Задача 2: GREEN — SKILL.md

**Files:**
- Create: `C:\Users\ds200\.claude\skills\multivariant-web-design\SKILL.md`
- Reference: `scratchpad\mvwd\multivariant-web-design\SKILL.md` (desktop-исходник)

**Interfaces:**
- Consumes: `BASELINE.md` (Задача 1) — какие провалы закрывать
- Produces: `SKILL.md` со ссылкой `references/sources.md`, которую создаёт Задача 3.

**Дефект исходника, который надо починить.** В desktop-версии `description` пересказывает процесс: «…и главное правило: всегда предлагать 3 разных варианта дизайна отдельными артефактами». По SDO это ловушка — агент выполняет описание и не читает тело навыка, теряя направления A/B/C, приём с refero и лицензии. Новое описание содержит **только триггеры**.

- [ ] **Step 1: Написать frontmatter**

```yaml
---
name: multivariant-web-design
description: >-
  Use when the user asks to design, build, sketch, lay out, or "make pretty" any
  web page, landing, screen, UI, component, form, dashboard, or interface — even
  if they never say the word "design" and give no references. Triggers (RU/EN):
  «сделай страницу», «свёрстай», «дизайн лендинга», «набросай интерфейс», «нужен
  UI», «компонент кнопки/карточки», «сделай красиво», "design a page", "build a
  landing", "make a UI", "hero section", "dashboard". Also use when the user
  names a product's look ("как Linear", "in the style of Vercel") or links to
  uiverse.io, reactbits.dev, or styles.refero.design. Not for backend,
  algorithmic, or text-only tasks with no visual result.
---
```

- [ ] **Step 2: Проверить длину frontmatter**

Run:
```powershell
$t = Get-Content "C:\Users\ds200\.claude\skills\multivariant-web-design\SKILL.md" -Raw
$fm = [regex]::Match($t, '(?s)^---.*?---').Value
"frontmatter chars: " + $fm.Length
```
Expected: число ≤ 1024. Если больше — резать перечисление триггеров, не смысл.

- [ ] **Step 3: Написать тело**

Секции, ровно в этом порядке:

1. **Overview** — 2 предложения: не один «правильный» макет, а три разных направления для живого сравнения.
2. **Главное правило: 3 варианта** — направления A «продуктовый» (в духе refero: выверенная сетка, строгая иерархия), B «живой» (в духе reactbits: анимация, движение, интерактивные фоны), C «характерный» (в духе uiverse: свечения, градиентные бордеры, выразительные детали). Заметно разные, не один макет в трёх цветах.
3. **Подача** — рецептом, а не запретом (форма под провал «пропущенный элемент»):

```
design-variants/
  index.html        # переключатель между вариантами
  a-product.html
  b-alive.html
  c-character.html
```
   Открыть `index.html` в браузере. К каждому варианту 1–2 фразы: настроение, акцент, кому подойдёт.
4. **Источники** — указатель, без содержимого каталога:
   `Нужен источник, стиль назван или дана ссылка → читай references/sources.md.`
   Плюс инвариант: **не воспроизводи чужой компонент или стиль по памяти** — загрузи спеку, прочитай код или попроси у пользователя.
5. **Стек-гейт** — перед установкой из shadcn-реестра проверить Tailwind и `components.json`; если их нет — не ставить, а прочитать код через `npx shadcn@latest view` и перенести руками.
6. **Рабочий процесс** — 5 шагов: контекст (1–2 вопроса, если неясно) → тема тёмная/светлая осознанно → подтянуть реальные данные, если есть зацепка → собрать 3 варианта по правилам `frontend-design` → подписать различия и предложить следующий шаг.
7. **Чек-лист перед выдачей** — чекбоксы.

Кросс-ссылка на базовое качество вёрстки — только по имени, без `@`:
`**REQUIRED SUB-SKILL:** Use frontend-design для токенов, типографики и отступов.`

- [ ] **Step 4: Проверить объём**

Run:
```powershell
(Get-Content "C:\Users\ds200\.claude\skills\multivariant-web-design\SKILL.md" | Measure-Object -Word).Words
```
Expected: < 500. Если больше — переносить детали в `references/sources.md`, не сокращать смысл.

- [ ] **Step 5: Проверить отсутствие пересказа workflow в описании**

Прочитать `description` глазами. Красный флаг: любое предложение, описывающее, что навык *делает* («предлагает три варианта», «загружает спеку»). Должны остаться только условия срабатывания. Если нашлось — переписать.

---

### Задача 3: GREEN — references/sources.md

**Files:**
- Create: `C:\Users\ds200\.claude\skills\multivariant-web-design\references\sources.md`

**Interfaces:**
- Consumes: указатель из `SKILL.md` (Задача 2)
- Produces: каталог; дальше используется только людьми и агентом во время дизайна.

Тип — reference skill. Тестируется retrieval-сценариями (Задача 4), не давлением.

- [ ] **Step 1: Секция 1 — готовые спеки**

`styles.refero.design` — 2000+ машиночитаемых дизайн-систем реальных продуктов, каждая с `DESIGN.md`: токены с ролями, шкала типографики, спейсинг, радиусы, тени, Do/Don't, CSS custom properties, блок Tailwind v4.

Приём: назван стиль или дана ссылка → `WebFetch` его `DESIGN.md` → верстать строго по токенам. Каталог `https://styles.refero.design/`, стиль `/style/<uuid>`. Refero MCP — если подключён.

- [ ] **Step 2: Секция 2 — shadcn-реестры**

Один механизм на всю группу:

```bash
npx shadcn@latest view @magicui/marquee              # прочитать код ДО установки
npx shadcn@latest search @magicui --query "text"     # поиск по реестру
npx shadcn@latest add @magicui/marquee               # установить
```

Namespace выбирается самостоятельно — идентификатор реестра это URL, а не имя после `@`:

```json
{
  "registries": {
    "@magicui": "https://magicui.design/r/{name}.json",
    "@aceternity": "https://ui.aceternity.com/registry/{name}.json"
  }
}
```

Состав: shadcn blocks (`ui.shadcn.com/blocks`), Magic UI, Aceternity UI, Motion Primitives, Cult UI, coss/Origin. Поиск реестров: `registry.directory`, `ui.shadcn.com/docs/directory`.

Пометки: URL выше проверены 2026-07-16; для остальных источников группы URL берётся из их документации в момент использования. `view` работает и там, где ставить нельзя — см. стек-гейт.

- [ ] **Step 3: Секция 3 — сниппеты, код нужен от пользователя**

- **uiverse.io** — кнопки, чекбоксы, тогглы, карточки, лоадеры, инпуты на чистом CSS/Tailwind. Лицензия MIT: код берётся напрямую, атрибуция сохраняется.
- **reactbits.dev** — анимированные React-компоненты; сильнее всего фоны (Aurora, Beams, Particles — WebGL) и анимации текста. Лицензия репозитория DavidHDev/react-bits — MIT + Commons Clause: нельзя продавать продукт, ценность которого именно в этом коде.
- Оба — SPA, `WebFetch` отдаёт только мета-теги. Реальный код: GitHub, ReactBits MCP, или попросить у пользователя.

- [ ] **Step 4: Секция 4 — галереи для человека**

Mobbin, Godly, Land-book, Awwwards, siteinspire. Явная пометка: **кода отсюда не достать**. Не ходить туда за кодом; вместо этого попросить у пользователя ссылку или скриншот.

- [ ] **Step 5: Секция 5 — системный слой**

Открыть признанием, что секция режется по другой оси — это инструменты, а не источники кода:

- **tweakcn** (`tweakcn.com`) — редактор тем shadcn, живое превью, экспорт в Tailwind.
- **Realtime Colors** (`realtimecolors.com`) — палитра и шрифты на живом макете.
- **Fontshare** (`fontshare.com`) — бесплатные шрифты, в том числе для коммерческого использования.
- **Lucide** (`lucide.dev`) — иконки, идут в комплекте с shadcn.

- [ ] **Step 6: Секция 6 — протухание**

Правило с живым примером: Origin UI за год стал coss ui, переехал на Base UI и сменил домен (`originui.com` → `coss.com/ui`, legacy на `coss.com/origin`). Отсюда: хранить механизмы и стабильные точки входа, а не списки компонентов и версий; если источник не отвечает или переименовался — сказать вслух, а не гадать.

- [ ] **Step 7: Проверить, что живых URL не выдумано**

Run:
```powershell
Select-String -Path "C:\Users\ds200\.claude\skills\multivariant-web-design\references\sources.md" -Pattern 'https?://[^\s`")]+' -AllMatches |
  ForEach-Object { $_.Matches.Value } | Sort-Object -Unique
```
Каждый URL из списка либо проверен в этой сессии, либо помечен как «уточнить в документации при использовании». Непроверенных живых ссылок остаться не должно.

---

### Задача 4: GREEN-проверка — те же сценарии с навыком

**Files:**
- Modify: `C:\Users\ds200\.claude\skills\multivariant-web-design\BASELINE.md` (дописать раздел «С навыком»)

**Interfaces:**
- Consumes: `SKILL.md` (Задача 2), `references/sources.md` (Задача 3), `BASELINE.md` (Задача 1)
- Produces: список новых рационализаций для Задачи 5.

- [ ] **Step 1: Повторить сценарий 1 с навыком**

Тот же дословный промпт, что в Задаче 1 Step 2. Expected: три заметно разных варианта отдельными файлами в `design-variants/`, к каждому пояснение, тема выбрана осознанно.

- [ ] **Step 2: Повторить сценарий 2 с навыком**

Тот же промпт, что в Задаче 1 Step 3. Expected: `WebFetch` спеки стиля со `styles.refero.design` перед вёрсткой, вёрстка по её токенам, а не по памяти.

- [ ] **Step 3: Повторить сценарий 3 с навыком**

Тот же промпт и рабочий каталог, что в Задаче 1 Step 4. Expected: проверка Tailwind/`components.json`, отказ от `shadcn add`, чтение кода через `view` и ручной перенос.

- [ ] **Step 4: Записать результат**

Дописать в `BASELINE.md` раздел «С навыком»: где поведение исправилось, где нет, какие **новые** обходные пути появились — дословно.

---

### Задача 5: REFACTOR — закрыть лазейки

**Files:**
- Modify: `C:\Users\ds200\.claude\skills\multivariant-web-design\SKILL.md`
- Modify: `C:\Users\ds200\.claude\skills\multivariant-web-design\references\sources.md`

**Interfaces:**
- Consumes: раздел «С навыком» из `BASELINE.md` (Задача 4)
- Produces: финальные версии обоих файлов.

- [ ] **Step 1: Подобрать форму под тип провала**

По таблице `writing-skills`, а не наугад:

| Провал в тесте | Форма правки |
|---|---|
| Знает правило, но нарушает под давлением | Запрет + таблица рационализаций + красные флаги |
| Выдал не ту форму (один файл вместо трёх) | Позитивный рецепт: чем результат **является**, по частям |
| Пропустил обязательный элемент | Структурный слот в шаблоне, а не напоминание прозой |
| Поведение должно зависеть от условия | Условие на наблюдаемом признаке («если в проекте нет `components.json` — …») |

Запрет на провал формы не вешать: под конкурирующим стимулом он даёт **хуже**, чем отсутствие правила.

- [ ] **Step 2: Внести правки и перепрогнать провалившийся сценарий**

Повторить ровно тот сценарий, что провалился. Expected: поведение исправлено, остальные сценарии не сломались.

- [ ] **Step 3: Проверить объём после правок**

Run:
```powershell
(Get-Content "C:\Users\ds200\.claude\skills\multivariant-web-design\SKILL.md" | Measure-Object -Word).Words
```
Expected: < 500. Выросло — переносить в `references/`.

---

### Задача 6: Развернуть и проверить обнаружение

**Files:**
- Verify: весь каталог навыка

- [ ] **Step 1: Проверить структуру**

Run:
```powershell
Get-ChildItem "C:\Users\ds200\.claude\skills\multivariant-web-design\" -Recurse -File | Select-Object FullName
```
Expected: `SKILL.md`, `references\sources.md`, `DESIGN.md`, `PLAN.md`, `BASELINE.md`.

- [ ] **Step 2: Проверить, что навык виден**

Перезапустить сессию Claude Code и убедиться, что `multivariant-web-design` появился в списке доступных навыков. Если нет — сверить frontmatter с [agentskills.io/specification](https://agentskills.io/specification): чаще всего виноват битый YAML или `name` с недопустимыми символами.

- [ ] **Step 3: Проверить срабатывание на живом запросе**

В новой сессии написать: `Набросай мне UI для формы логина`. Expected: навык подхватывается сам, без явного вызова, и выдаются три варианта.

- [ ] **Step 4: Убедиться, что valorant-репозиторий не тронут**

Run:
```powershell
git -C "C:\делишки\вуз\valorant-aim-coach" status --short
```
Expected: те же изменения, что были в начале сессии. Ничего от навыка в репозитории быть не должно.

---

## Self-Review

**Покрытие спеки:**

| Требование `DESIGN.md` | Задача |
|---|---|
| Структура `SKILL.md` + `references/sources.md` | 2, 3 |
| Сохранить направления A/B/C, лицензии, «не по памяти» | 2 (Step 3) |
| Подача через `design-variants/*.html` + `index.html` | 2 (Step 3) |
| `web_fetch` → `WebFetch` | 2 (Step 3) |
| Пять секций каталога по механизму доступа | 3 (Steps 1–5) |
| Стек-гейт | 2 (Step 3), тест — 1 (Step 4) и 4 (Step 3) |
| Правило протухания | 3 (Step 6), проверка URL — 3 (Step 7) |
| Не коммитить в valorant-репо | Global Constraints, проверка — 6 (Step 4) |
| Компактность `SKILL.md` | 2 (Step 4), 5 (Step 3) |

Пробелов не найдено.

**Плейсхолдеры:** нет. Каждый шаг содержит либо готовый текст, либо точную команду с ожидаемым выводом.

**Согласованность имён:** каталог везде `multivariant-web-design`; файлы вариантов везде `a-product.html` / `b-alive.html` / `c-character.html`; указатель на каталог везде `references/sources.md`.

**Добавлено сверх спеки:** дефект `description` в desktop-исходнике (пересказ workflow) — Задача 2. В спеке этого не было; всплыло при чтении правил SDO в `writing-skills`. Чинится в рамках плана, потому что иначе переносится в Claude Code как есть.
