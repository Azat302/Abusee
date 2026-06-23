# Инструкция по развертыванию Abusee VPN Bot на VPS

## Предварительные требования
- VPS с Ubuntu/Debian
- Доступ к VPS по SSH
- Установленные: Python 3.10+, Git

---

## Шаг 1: Создание GitHub репозитория

1. Перейдите на https://github.com
2. Создайте **приватный** репозиторий (назовите его например `abusee-vpn-bot`)
3. Не инициализируйте README, .gitignore или LICENSE (мы добавим их сами)
4. Сохраните URL репозитория (например, `https://github.com/ваше_имя/abusee-vpn-bot.git`)

---

## Шаг 2: Загрузка кода на GitHub

На локальном компьютере (в папке проекта):
```bash
# Инициализируем git
git init

# Добавляем все файлы
git add .

# Создаем коммит
git commit -m "Initial production commit"

# Подключаем репозиторий
git remote add origin https://github.com/ваше_имя/abusee-vpn-bot.git

# Отправляем код на GitHub
git branch -M main
git push -u origin main
```

---

## Шаг 3: Клонирование на VPS

Подключитесь к VPS по SSH:
```bash
# Перейдите в папку для проектов (например, /opt)
cd /opt

# Клонируйте репозиторий
git clone https://github.com/ваше_имя/abusee-vpn-bot.git
cd abusee-vpn-bot
```

---

## Шаг 4: Создание виртуального окружения

```bash
# Создаем venv
python3 -m venv venv

# Активируем venv
source venv/bin/activate
```

---

## Шаг 5: Установка зависимостей

```bash
pip install -r requirements.txt
```

---

## Шаг 6: Заполнение .env

Скопируйте пример и отредактируйте:
```bash
# Скопируйте пример .env
cp .env.example .env

# Отредактируйте .env (вставьте ваши токены)
nano .env
```

В `.env` нужно заполнить:
- `XUI_URL` - URL вашего 3x-ui панели
- `XUI_USERNAME` - логин для 3x-ui
- `XUI_PASSWORD` - пароль для 3x-ui
- `TELEGRAM_BOT_TOKEN` - токен бота из @BotFather
- `TELEGRAM_ADMIN_ID` - ваш Telegram username или ID
- `INSTALLATION_GUIDE_URL` - ссылка на инструкцию по подключению
- `YOO_PAYMENT_TOKEN` - **боевой** токен ЮKassa из BotFather

---

## Шаг 7: Запуск бота вручную

Проверяем, что бот запускается:
```bash
python bot.py
```

Если всё хорошо, вы увидите:
```
✅ База данных инициализирована
🔧 Создаём приложение бота...
🚀 Запускаем бота...
```

Нажмите `Ctrl+C` чтобы остановить бота и перейдем к systemd.

---

## Шаг 8: Установка как systemd-сервиса

Скопируйте пример сервиса:
```bash
sudo cp systemd_service_example.txt /etc/systemd/system/abusee-bot.service
```

Отредактируйте файл сервиса, указав правильные пути:
```bash
sudo nano /etc/systemd/system/abusee-bot.service
```

Проверьте, что:
- `WorkingDirectory` указывает на папку с ботом (например, `/opt/abusee-vpn-bot`)
- `ExecStart` использует правильный путь к venv
- `User` - пользователь, под которым будет работать бот (например, `root` или создайте отдельного пользователя)

Активируем сервис:
```bash
# Перезагружаем systemd
sudo systemctl daemon-reload

# Включаем автозапуск при загрузке
sudo systemctl enable abusee-bot.service

# Запускаем сервис
sudo systemctl start abusee-bot.service

# Проверяем статус
sudo systemctl status abusee-bot.service
```

---

## Шаг 9: Обновление проекта через `git pull`

Когда нужно обновить бота:
```bash
# Перейдите в папку проекта
cd /opt/abusee-vpn-bot

# Активируйте venv
source venv/bin/activate

# Сохраните изменения в .env (если нужно)
git stash push -m "save local env"

# Скачайте обновления
git pull origin main

# Восстановите .env
git stash pop

# Установите новые зависимости (если есть)
pip install -r requirements.txt

# Перезапустите сервис
sudo systemctl restart abusee-bot.service

# Проверьте статус
sudo systemctl status abusee-bot.service
```

---

## Просмотр логов сервиса

```bash
# Последние 50 строк логов
sudo journalctl -u abusee-bot.service -n 50

# Логи в реальном времени
sudo journalctl -u abusee-bot.service -f
```
