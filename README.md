# VPN Service Backend

Production-ready backend for VPN service built with FastAPI.

## Стек технологий

- Python 3.12
- FastAPI
- SQLAlchemy 2.0
- SQLite
- Pydantic 2.0
- Requests

## Структура проекта

```
Abusee/
├── app/
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py          # API endpoints
│   ├── models/
│   │   ├── __init__.py
│   │   ├── user.py            # SQLAlchemy User model
│   │   └── schemas.py         # Pydantic schemas
│   ├── services/
│   │   ├── __init__.py
│   │   ├── xui_client.py      # XUI panel client
│   │   └── vpn_service.py     # VPN business logic
│   └── database/
│       ├── __init__.py
│       └── database.py        # SQLAlchemy setup
├── main.py                    # FastAPI application entry point
├── requirements.txt           # Python dependencies
├── .env                       # Environment variables
└── .env.example               # Example environment variables
```

## Установка и запуск на macOS

### 1. Клонирование проекта (если необходимо)

```bash
cd /path/to/Abusee
```

### 2. Создание виртуального окружения

```bash
python3.12 -m venv venv
source venv/bin/activate
```

### 3. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 4. Настройка переменных окружения

Скопируйте пример файла окружения и отредактируйте при необходимости:

```bash
cp .env.example .env
```

Отредактируйте `.env` файл, если нужно изменить параметры подключения к XUI панели.

### 5. Запуск сервера

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Сервер будет доступен по адресу: http://localhost:8000

### 6. Документация API

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## API Endpoints

### GET /
Возвращает статус сервера.

### POST /users
Создаёт нового пользователя (упрощённая версия).

Параметры запроса:
```json
{
  "username": "string",
  "months": 1,
  "traffic_limit_gb": 100
}
```

### GET /users
Возвращает список всех пользователей.

### POST /vpn/create
Создаёт VPN-пользователя с полной подготовкой для 3x-ui (рекомендованный endpoint).

Параметры запроса:
```json
{
  "username": "string",
  "months": 1,
  "traffic_limit_gb": 100,
  "device_limit": 3
}
```

Ответ:
```json
{
  "user_id": 1,
  "uuid": "550e8400-e29b-41d4-a716-446655440000",
  "expire_at": "2026-07-08T23:13:20.625476",
  "subscription_url": null
}
```

## Модель User

Поля модели пользователя:
- `id` - уникальный идентификатор
- `telegram_id` - ID пользователя в Telegram (опционально)
- `username` - имя пользователя
- `vpn_email` - email для VPN (опционально)
- `uuid` - уникальный идентификатор для 3x-ui
- `expire_at` - дата истечения подписки
- `traffic_limit_gb` - лимит трафика в GB
- `xui_client_id` - ID клиента в 3x-ui (опционально)
- `subscription_url` - URL подписки (опционально)
- `is_active` - статус активности
- `protocol` - протокол VPN (по умолчанию vless)
- `device_limit` - лимит устройств
- `created_at` - дата создания

## XUI Client (3x-ui интеграция)

Модуль `app/services/xui_client.py` содержит класс `XUIClient` с методами:
- `login()` - авторизация в панели
- `get_inbounds()` - получение списка inbound'ов
- `create_client()` - создание клиента
- `get_client()` - получение информации о клиенте
- `update_client()` - обновление клиента
- `delete_client()` - удаление клиента

В текущей версии методы являются заглушками с TODO для реальной интеграции.

## Архитектура для будующего расширения

Проект подготовлен для добавления:
- Telegram бота (интеграция через `telegram_id`)
- Системы оплаты (интеграция через создание заказов перед созданием пользователя)
- Реферальной системы (дополнительные поля в модели User)

