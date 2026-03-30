# ЛогоперРадар — Fleet Tracking System

Веб-приложение для мониторинга местоположения контейнерного флота по IMO-кодам.  
Автоматически определяет бассейн судна и обновляет данные каждые 3 дня.

---

## Структура проекта

```
logoper_radar/
├── backend/
│   ├── main.py          # FastAPI приложение (роуты, авторизация, API)
│   ├── database.py      # Инициализация SQLite
│   ├── scraper.py       # Парсер данных (goradar.ru + fallbacks)
│   ├── basin.py         # Логика определения бассейна
│   ├── requirements.txt # Зависимости Python
│   └── data/            # База данных SQLite (создаётся автоматически)
├── frontend/
│   ├── templates/
│   │   ├── public.html  # Публичная страница
│   │   └── admin.html   # Панель управления (после авторизации)
│   └── static/          # Статические файлы (CSS/JS если нужны)
├── run.sh               # Скрипт запуска
└── README.md
```

---

## Быстрый старт

### 1. Создать виртуальное окружение

```bash
cd logoper_radar
python3 -m venv venv
source venv/bin/activate        # Linux/Mac
# или: venv\Scripts\activate    # Windows
```

### 2. Установить зависимости

```bash
pip install -r backend/requirements.txt
```

### 3. Настроить переменные окружения (опционально)

```bash
export ADMIN_PASSWORD="ваш_пароль"    # По умолчанию: logoper2024
export SESSION_SECRET="random_string"  # Генерируется автоматически
```

Или создайте файл `.env` и загружайте через `python-dotenv`.

### 4. Запустить

```bash
./run.sh            # Production
./run.sh --dev      # Разработка (с hot-reload)
```

Или напрямую:

```bash
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000
```

Приложение будет доступно по адресу: **http://localhost:8000**

---

## Деплой на сервере (systemd)

Создайте файл `/etc/systemd/system/logoper-radar.service`:

```ini
[Unit]
Description=ЛогоперРадар Fleet Tracking
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/logoper_radar/backend
Environment="ADMIN_PASSWORD=ваш_пароль"
Environment="SESSION_SECRET=случайная_строка_32_символа"
ExecStart=/opt/logoper_radar/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable logoper-radar
sudo systemctl start logoper-radar
```

---

## Nginx (обратный прокси)

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        client_max_body_size 10M;
    }
}
```

---

## Использование

### Публичная страница
- Отображает статистику по бассейнам
- Кнопка «Войти» для входа в панель управления

### Панель управления (после входа)
- **Добавить судно**: введите 7-значный IMO-код в поле внизу таблицы
- **Импорт TXT**: прикрепите файл со списком IMO (по одному на строку)
- **Обновить**: запустить принудительное обновление всех судов
- **Экспорт XLS**: скачать данные в Excel
- **Удалить**: кнопка × у строки или «Массовое удаление»
- **Фильтр**: клик на карточку бассейна фильтрует таблицу

### Автоматическое обновление
Каждые **3 дня** система автоматически обходит все IMO-коды и обновляет:
- Название судна
- Морская линия (оператор)
- Текущий порт / назначение
- **Бассейн** (определяется по портам захода)

### Логика бассейнов
| Бассейн | Условие |
|---------|---------|
| ДВ | Заходит в Владивосток / Находку / Восточный + иностранные порты |
| ДВ каботаж | Только порты ДВ России (без иностранных) |
| ДВ без РФ | Маршрут ДВ, но без российских портов |
| Балтийский | Заходит в СПб / Калининград + иностранные |
| Балтика каботаж | Только СПб ↔ Калининград (кольцо) |
| Новороссийск | Новороссийск, Туапсе, Тамань, Темрюк, Керчь, Азов |
| Транзит | Иностранный маршрут, нет портов РФ |
| Неизвестно | Нет данных |

### Формат TXT-файла для импорта
```
9473626
9512834
1234567
```
Одна строка = один IMO-код (7 цифр). Парсер найдёт IMO даже в тексте.

---

## Смена пароля

Установите переменную окружения `ADMIN_PASSWORD` и перезапустите приложение:

```bash
export ADMIN_PASSWORD="новый_пароль"
systemctl restart logoper-radar
```

---

## Источники данных (без API-ключей)

Система последовательно пробует:
1. **goradar.ru** — основной источник
2. **myshiptracking.com** — резервный
3. **vesseltracker.com** — резервный
4. **marinetraffic.com** — резервный (ограниченные данные)

Если ни один источник недоступен, данные о судне остаются в базе без обновления.
