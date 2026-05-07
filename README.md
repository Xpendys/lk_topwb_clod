# Реферальная программа ТопВТоп · MVP

Личный кабинет партнёра + интеграция с amoCRM через Albato. Партнёр получает 10% с оплаченных выкупов приглашённого клиента (пожизненно).

## Что внутри

- `app/` — Python-приложение на FastAPI
- `app/templates/` — HTML-страницы личного кабинета (Jinja2)
- `app/static/style.css` — стили
- `tilda_snippet.html` — JS-код для вставки в Tilda
- `requirements.txt` — зависимости Python
- `.env.example` — пример конфига (скопировать в `.env`)

## Локальный запуск (для проверки на своём компьютере)

```bash
# 1) Создать виртуальное окружение
python -m venv .venv

# 2) Активировать
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Windows (cmd):
.venv\Scripts\activate.bat
# Linux/Mac:
source .venv/bin/activate

# 3) Установить зависимости
pip install -r requirements.txt

# 4) Создать .env из примера
cp .env.example .env
# Открой .env и поменяй SECRET_KEY и ALBATO_WEBHOOK_SECRET на длинные случайные строки.
# Сгенерировать можно так:
python -c "import secrets; print(secrets.token_hex(32))"

# 5) Запустить
uvicorn app.main:app --reload --port 8000
```

Открой http://localhost:8000 — увидишь главную страницу. Зарегистрируй тестового партнёра, зайди в `/lk`.

База данных создаётся автоматически в файле `referal.db`.

---

## Деплой на боевой сервер — пошагово

Дальше идёт инструкция «делай как написано», предназначенная для человека, который никогда не настраивал серверы. Каждый шаг — отдельная задача, не пропускай и не меняй порядок.

### Шаг 0. Что у тебя должно быть на руках

- [x] Аккаунт Selectel
- [x] Аккаунт Albato
- [x] Доступ админа в АМО
- [x] Поле `REFERER` (тип Текст) **в Контактах** в АМО (уже создано)
- [ ] Купленный поддомен `referal.toptopwb.ru` (или который выберешь) — покупаем на следующих шагах
- [ ] Доступ к управлению DNS того, у кого зарегистрирован `toptopwb.ru` (reg.ru / beget / nic.ru)

### Шаг 1. Создать VPS на Selectel

1. Войди на https://my.selectel.ru
2. Слева в меню → **«Облачные серверы»** (или «Облачная платформа» → «Серверы»).
3. **«Создать сервер»**.
4. Параметры:
   - **Регион:** `Москва, ru-1` (любой ближайший)
   - **Тариф:** «Готовая конфигурация → Линейка SSD → 1 vCPU / 1 ГБ RAM / 10 ГБ диск» — этого хватит с большим запасом.
   - **Источник:** Образ → **Ubuntu 24.04 LTS**
   - **SSH-ключ:** если есть — добавь. Если нет — выбери «Пароль» и придумай надёжный пароль для root, **запиши его**.
   - **Сеть:** оставь как по умолчанию (публичный IP включён).
5. **Создать.** Через минуту сервер готов. Запиши его **публичный IP** — он понадобится дальше.

### Шаг 2. Зайти на сервер

Тебе нужен SSH-клиент. На Windows проще всего:

- **PowerShell** (встроенный): открой PowerShell, выполни:
  ```
  ssh root@ТВОЙ_IP
  ```
- Введи пароль (тот что задал в Шаге 1).
- Если SSH говорит «host key verification» — нажми `yes`.

Если по какой-то причине SSH не работает в PowerShell — установи **PuTTY** (https://www.putty.org/) и зайди через него.

### Шаг 3. Подготовить сервер (один раз)

После того как зашёл по SSH, выполни команды по очереди (можно копировать и вставлять):

```bash
# Обновить систему
apt update && apt upgrade -y

# Установить Python, nginx, git, certbot для SSL
apt install -y python3 python3-venv python3-pip nginx git certbot python3-certbot-nginx

# Создать пользователя для приложения (не работаем под root)
adduser --disabled-password --gecos "" referal
```

### Шаг 4. Загрузить код приложения на сервер

Самый простой способ — через git. Создай приватный репозиторий на GitHub/GitLab и залей туда содержимое этой папки. Потом на сервере:

```bash
# Войти под пользователем referal
su - referal

# Склонировать репозиторий (замени URL на свой)
git clone https://github.com/ТВОЙ_ЛОГИН/referal-toptopwb.git app
cd app

# Создать виртуальное окружение и установить зависимости
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# Создать .env
cp .env.example .env
nano .env
```

В `.env` обязательно **поменяй**:
- `SECRET_KEY` → длинная случайная строка (сгенерируй: `python3 -c "import secrets; print(secrets.token_hex(32))"`)
- `ALBATO_WEBHOOK_SECRET` → ещё одна длинная случайная строка (запиши её — понадобится в Albato)
- `LK_BASE_URL=https://referal.toptopwb.ru` (или какой у тебя поддомен)
- `PUBLIC_SITE_URL=https://www.toptopwb.ru`

Сохрани в nano: `Ctrl+O`, `Enter`, `Ctrl+X`.

### Шаг 5. Сделать приложение «службой»

Чтобы оно само запускалось и перезапускалось при сбоях, заведём systemd-сервис.

Выйди обратно в root:
```bash
exit
```

Создай файл сервиса:
```bash
nano /etc/systemd/system/referal.service
```

Вставь:
```ini
[Unit]
Description=ToptopWB Referral
After=network.target

[Service]
Type=simple
User=referal
WorkingDirectory=/home/referal/app
ExecStart=/home/referal/app/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Сохрани (`Ctrl+O`, `Enter`, `Ctrl+X`). Запусти сервис:
```bash
systemctl daemon-reload
systemctl enable referal
systemctl start referal
systemctl status referal
```

Если видишь зелёное `active (running)` — отлично.

### Шаг 6. Настроить nginx как «парадную дверь»

```bash
nano /etc/nginx/sites-available/referal
```

Вставь (поменяй `referal.toptopwb.ru` на свой поддомен):
```nginx
server {
    listen 80;
    server_name referal.toptopwb.ru;

    client_max_body_size 1m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Включить:
```bash
ln -s /etc/nginx/sites-available/referal /etc/nginx/sites-enabled/referal
nginx -t              # должно сказать "syntax is ok"
systemctl reload nginx
```

### Шаг 7. Купить и направить поддомен

1. **Купить поддомен НЕ нужно** — поддомены создаются бесплатно у регистратора основного домена `toptopwb.ru`.
2. Зайди в панель регистратора домена `toptopwb.ru` (reg.ru / beget / nic.ru).
3. Найди раздел **«DNS» / «Управление DNS-записями»** для домена `toptopwb.ru`.
4. Добавь новую запись:
   - **Тип:** `A`
   - **Имя / Поддомен:** `referal`  *(только это слово, без точки и без основного домена)*
   - **Значение / IP:** публичный IP твоего сервера из Шага 1
   - **TTL:** оставь по умолчанию (или 600)
5. Сохрани.
6. Подожди 5–30 минут (DNS обновляется не мгновенно). Проверить:
   ```bash
   ping referal.toptopwb.ru
   ```
   Должен показать твой IP.

### Шаг 8. Подключить SSL (https)

Когда DNS обновился (Шаг 7):
```bash
certbot --nginx -d referal.toptopwb.ru
```

- Введи email для уведомлений Let's Encrypt.
- Согласись с условиями.
- Когда спросит про редирект HTTP→HTTPS — выбери `2` (включить редирект).

После этого открой `https://referal.toptopwb.ru` в браузере — должен открыться твой сайт с зелёным замочком.

### Шаг 9. Настроить Albato

Цель: чтобы при переходе сделки в АМО на этап «Оплачено» Albato автоматически дёрнул наш сервер.

1. Войди на https://albato.ru → **«Связки»** → **«Создать связку»**.
2. **Источник:** AmoCRM
   - Подключи свой аккаунт АМО (через OAuth, никаких заявлений — Albato это публичный виджет в маркетплейсе АМО).
   - **Триггер:** «Сделка изменена» (Deal updated).
   - **Воронка:** твоя основная воронка продаж.
   - **Условие:** этап = `Оплачено`. Если в Albato нельзя задать условие на этапе — добавь шаг «Фильтр» после источника: `current_status_name == "Оплачено"`.
3. **Шаг "Поиск":** «Найти контакт по ID» — указать Main Contact ID из триггера. Это даст нам пользовательские поля контакта, включая `REFERER`.
4. **Назначение:** «Webhook» / «HTTP запрос».
   - **URL:** `https://referal-top-wb.ru/api/amo-webhook?secret=ТВОЙ_ALBATO_WEBHOOK_SECRET_ИЗ_.env`
   - **Метод:** `POST`
   - **Тип тела:** JSON
   - **Тело:**
     ```json
     {
       "amo_lead_id": {{ trigger.id }},
       "buyout_budget": {{ trigger.custom_fields.Бюджет_выкупы }},
       "amo_contact_id": {{ contact.id }},
       "referer_code": "{{ contact.custom_fields.REFERER }}"
     }
     ```
     (точные имена переменных зависят от Albato — выбирай в их визуальном маппере поля «ID сделки», «Бюджет выкупы», «ID контакта», «REFERER (контакт)»)
5. **Сохрани и включи связку.**

**Тест:**
- В АМО возьми тестовую сделку, в её Контакте заполни поле REFERER значением реф-кода тестового партнёра (например `RUDY47`).
- Переведи сделку в этап «Оплачено».
- Через 10–30 секунд зайди в ЛК партнёра — должно появиться начисление.
- Если не появилось — смотри логи в Albato (раздел «История запусков») и логи на сервере: `journalctl -u referal -n 100`.

### Шаг 10. Настроить Tilda

1. Открой `tilda_snippet.html` в этой папке. Внутри лежит готовый блок `<script>...</script>`.
2. Зайди в **Tilda → Сайт → Настройки сайта → Ещё → HTML-код для вставки внутрь HEAD**.
3. Вставь содержимое файла. Сохрани. **Опубликуй сайт** (важно — без публикации не применится!).
4. Теперь надо в Tilda сказать: «поле формы `REFERER` слать в АМО как поле Контакта `REFERER`».
   - Tilda → **Сайт → Настройки сайта → Формы → AmoCRM**.
   - В настройках интеграции есть таблица соответствия полей. Добавь правило:
     - **Поле формы:** `REFERER`
     - **Тип сущности:** Контакт
     - **Поле в АМО:** `REFERER` (то которое мы создали в Контакте)
   - Сохрани.

**Тест:**
1. Открой `https://www.toptopwb.ru/?ref=RUDY47` (где `RUDY47` — реф-код твоего тестового партнёра).
2. Открой DevTools (F12) → Application → Cookies — должна появиться cookie `ttwb_ref=RUDY47`.
3. Открой DevTools → Elements, найди `<form>`, разверни — внутри должен быть `<input type="hidden" name="REFERER" value="RUDY47">`.
4. Заполни и отправь форму. В АМО должна создаться сделка, у её контакта в карточке поле REFERER должно быть заполнено `RUDY47`.

### Шаг 11. Готово, как использовать дальше

- Раз в месяц заходи на сервер → выгружай список выплат (пока вручную через SQLite):
  ```bash
  ssh root@ТВОЙ_IP
  su - referal
  cd app
  .venv/bin/python -c "
  from app.db import db_cursor
  with db_cursor() as cur:
      cur.execute('''
          SELECT u.id, u.first_name, u.last_name, u.email,
                 COALESCE(SUM(c.commission_amount), 0) -
                 COALESCE((SELECT SUM(amount) FROM payouts WHERE user_id = u.id), 0) AS balance
          FROM users u
          LEFT JOIN commissions c ON c.user_id = u.id
          GROUP BY u.id
          HAVING balance > 0
      ''')
      for row in cur.fetchall():
          print(row['id'], row['first_name'], row['last_name'], row['email'], row['balance'], 'руб')
  "
  ```
- После того как переведёшь деньги вручную — отметь выплату:
  ```bash
  .venv/bin/python -c "
  from app.db import db_cursor
  user_id = 1            # id партнёра
  amount = 5000          # сколько выплачено в рублях
  note = 'Перевод 2026-04-30, чек ###'
  with db_cursor() as cur:
      cur.execute(
          'INSERT INTO payouts (user_id, amount, note) VALUES (?, ?, ?)',
          (user_id, amount, note)
      )
  "
  ```

В будущем сделаем нормальную админку, чтобы не лазить в SQL.

### Обновление кода после правок

Когда что-то поправил локально и залил в git:
```bash
ssh root@ТВОЙ_IP
su - referal
cd app
git pull
.venv/bin/pip install -r requirements.txt   # если поменялись зависимости
exit
systemctl restart referal
```

### Бэкап базы

База — это файл `/home/referal/app/referal.db`. Раз в неделю копируй его себе:
```bash
scp root@ТВОЙ_IP:/home/referal/app/referal.db ~/backup-referal-$(date +%Y%m%d).db
```

---

## Отладка

### Не открывается сайт
- `systemctl status referal` — приложение запущено?
- `journalctl -u referal -n 100` — что в логах?
- `systemctl status nginx` — nginx работает?
- `nginx -t` — конфиг ок?

### Webhook от Albato не приходит
- В Albato → История запусков — что показывает?
- На сервере: `journalctl -u referal -f` (живой лог) → переведи тестовую сделку в «Оплачено», следи за логом.
- Проверь что в URL webhook после `?secret=` стоит тот же `ALBATO_WEBHOOK_SECRET`, что в `.env` на сервере.

### Реф-код не подставляется в форму Tilda
- Зайди на сайт через `?ref=ТЕСТКОД` → DevTools (F12) → Console — нет ли ошибок JS?
- DevTools → Application → Cookies → есть ли `ttwb_ref`?
- DevTools → Elements → `<form>` → есть ли `<input name="REFERER">`?
- Если нет — возможно, твоя версия Tilda монтирует формы по-другому. Скажи мне — поправим селектор в `tilda_snippet.html`.

---

## Что дальше (улучшения после MVP)

- Админ-кабинет (выплаты в браузере, без SQL)
- Восстановление пароля по email
- Email-уведомления партнёру о новой сделке/начислении
- Экспорт начислений в Excel
- Двухфакторная авторизация
- Подтверждение email при регистрации
