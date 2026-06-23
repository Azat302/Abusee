#!/usr/bin/env python3
"""
Telegram Bot для VPN-сервиса с оплатой через ЮKassa (Async)
"""
import os
import logging
import json
import fcntl
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Conflict
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    CallbackQueryHandler,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import select, func, or_

from app.models.user import (
    User, Payment, Referral, PromoCode, PromoCodeType, PromoActivation,
    Server, Broadcast, BroadcastCategory, Notification, NotificationType,
    SupportTicket, SupportTicketCategory, SupportTicketStatus
)
from app.services.vpn_service import AsyncVPNService
from app.services.yookassa_service import AsyncYooKassaService
from app.services.xui_client import AsyncXUIClient

# Загружаем переменные окружения (override existing)
BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env", override=True)

# Настраиваем логирование
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Конфигурация бота
TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
TELEGRAM_ADMIN_ID = (os.getenv("TELEGRAM_ADMIN_ID") or "").strip()
INSTALLATION_GUIDE_URL = (os.getenv("INSTALLATION_GUIDE_URL") or "").strip()

# Логируем загруженные данные (без полного токена)
logger.info(f"Loaded TELEGRAM_BOT_TOKEN: {TELEGRAM_BOT_TOKEN[:10]}...")
logger.info(f"Loaded TELEGRAM_ADMIN_ID: {TELEGRAM_ADMIN_ID}")

# Цены (в РУБЛЯХ!)
PRICE_1_MONTH = 199.0
PRICE_3_MONTHS = 550.0

# Состояния разговора
SELECTING_PLAN = 1
CONFIRM_NEW_SUBSCRIPTION = 2
SELECTING_EXTEND_PLAN = 3
WAITING_FOR_PAYMENT = 4
ENTERING_PROMO_CODE = 5
SUPPORT_CATEGORY = 6
SUPPORT_MESSAGE = 7
ADMIN_MENU = 8
ADMIN_BROADCAST_CATEGORY = 9
ADMIN_BROADCAST_TEXT = 10
ADMIN_CREATE_PROMO = 11
ADMIN_PROMO_CODE = 12
ADMIN_PROMO_TYPE = 13
ADMIN_PROMO_VALUE = 14
ADMIN_PROMO_MAX_USES = 15
ADMIN_PROMO_EXPIRE = 16

# Database async setup
if __name__ != "__main__":
    BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "vpn_service.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{DB_PATH}")
async_engine = create_async_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)
AsyncSessionLocal = async_sessionmaker(
    async_engine,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Debug logging setup (optional)
_DBG_CACHE = {"url": None, "session": None, "loaded": False}

def _dbg_load_config():
    if _DBG_CACHE["loaded"]:
        return
    _DBG_CACHE["loaded"] = True
    url = os.getenv("DEBUG_SERVER_URL")
    session = os.getenv("DEBUG_SESSION_ID")
    if url and session:
        _DBG_CACHE["url"] = url
        _DBG_CACHE["session"] = session

_dbg_load_config()

def format_bytes(bytes_val: int) -> str:
    """Форматирует байты в читаемый вид"""
    for unit in ["Б", "КБ", "МБ", "ГБ", "ТБ"]:
        if bytes_val < 1024.0:
            return f"{bytes_val:.2f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.2f} ПБ"

def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Создаёт основную клавиатуру с кнопками"""
    keyboard = [
        [KeyboardButton("🚀 Получить VPN")],
        [KeyboardButton("📄 Мой кабинет")],
        [KeyboardButton("🤝 Партнёрская программа")],
        [KeyboardButton("🆘 Поддержка")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton("📊 Статистика")],
        [KeyboardButton("👥 Пользователи")],
        [KeyboardButton("📢 Рассылка")],
        [KeyboardButton("🎁 Промокоды")],
        [KeyboardButton("🏠 Главное меню")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_plan_selection_keyboard() -> ReplyKeyboardMarkup:
    """Создаёт клавиатуру выбора тарифа"""
    keyboard = [
        [KeyboardButton("1 месяц - 199 ₽")],
        [KeyboardButton("3 месяца - 550 ₽")],
        [KeyboardButton("🎟️ Ввести промокод")],
        [KeyboardButton("🔙 Назад")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_confirmation_keyboard() -> ReplyKeyboardMarkup:
    """Создаёт клавиатуру подтверждения новой подписки"""
    keyboard = [
        [KeyboardButton("✅ Да, хочу купить ещё одно")],
        [KeyboardButton("📄 Посмотреть мои подписки")],
        [KeyboardButton("🔙 Назад")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_subscription_keyboard() -> ReplyKeyboardMarkup:
    """Создаёт клавиатуру для страницы подписки"""
    keyboard = [
        [KeyboardButton("🔄 Продлить подписку")],
        [KeyboardButton("🏠 Главное меню")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_extend_plan_keyboard() -> ReplyKeyboardMarkup:
    """Создаёт клавиатуру выбора плана для продления"""
    keyboard = [
        [KeyboardButton("1 месяц - 199 ₽")],
        [KeyboardButton("3 месяца - 550 ₽")],
        [KeyboardButton("🎟️ Ввести промокод")],
        [KeyboardButton("🔙 Назад")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_payment_waiting_keyboard() -> ReplyKeyboardMarkup:
    """Создаёт клавиатуру с кнопкой отмены оплаты"""
    keyboard = [
        [KeyboardButton("❌ Отменить оплату")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_support_category_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton("❌ VPN не работает")],
        [KeyboardButton("📺 YouTube не работает")],
        [KeyboardButton("🐌 Низкая скорость")],
        [KeyboardButton("💳 Ошибка оплаты")],
        [KeyboardButton("📝 Другое")],
        [KeyboardButton("🔙 Назад")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает команду /start"""
    user = update.effective_user
    if not user or not update.message:
        return

    referrer_id = None
    if context.args:
        try:
            referrer_id = int(context.args[0])
            if referrer_id == user.id:
                referrer_id = None
        except (ValueError, IndexError):
            referrer_id = None
    context.user_data['referrer_id'] = referrer_id

    async with AsyncSessionLocal() as db:
        stmt = select(User).where(User.telegram_id == user.id)
        result = await db.execute(stmt)
        existing_user = result.scalars().first()

        if not existing_user or not existing_user.trial_used:
            if not existing_user:
                vpn_service = AsyncVPNService(db)
                try:
                    db_user, _, subscription_url = await vpn_service.create_trial_user(
                        user.id, user.username or f"user_{user.id}", referrer_id
                    )
                    expire_str = db_user.expire_at.strftime("%d.%m.%Y %H:%M")
                    welcome_text = f"""👋 Привет, {user.first_name}!

🎁 Мы даём вам бесплатный тест VPN на 3 дня!

📅 Действует до: {expire_str}
📖 Инструкция к установке: {INSTALLATION_GUIDE_URL}

🔗 Ссылка для подключения:
{subscription_url}

Используйте кнопки ниже, чтобы управлять подпиской!"""
                    await update.message.reply_text(welcome_text, reply_markup=get_main_keyboard())
                    return
                except Exception as e:
                    logger.exception(f"Error creating trial user: {e}")
                    await update.message.reply_text("❌ Произошла ошибка, попробуйте позже.", reply_markup=get_main_keyboard())
                    return

    welcome_text = f"""👋 Привет, {user.first_name}!

🚀 Добро пожаловать в наш VPN-сервис!

Используйте кнопки ниже, чтобы начать пользоваться VPN!"""
    await update.message.reply_text(welcome_text, reply_markup=get_main_keyboard())

async def handle_get_vpn_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начинает процесс создания подписки - проверяет активные подписки"""
    telegram_user = update.effective_user
    if not telegram_user or not update.message:
        return ConversationHandler.END

    user_id = telegram_user.id
    logger.info(f"Пользователь {user_id} открыл выбор тарифа")

    async with AsyncSessionLocal() as db:
        vpn_service = AsyncVPNService(db)
        has_active = await vpn_service.has_active_subscriptions(user_id)

        if has_active:
            message = """👋 У вас уже есть активное подключение!

Ваша подписка доступна в разделе "📄 Мой кабинет".

Хотите купить ещё одно подключение?"""
            await update.message.reply_text(
                message,
                reply_markup=get_confirmation_keyboard(),
            )
            return CONFIRM_NEW_SUBSCRIPTION
        else:
            context.user_data['selected_duration'] = None
            context.user_data['promo_code'] = None
            plan_text = """📋 Выбери тариф подписки:

1 месяц - 199 ₽
3 месяца - 550 ₽

💡 При оплате за 3 месяца - скидка!"""
            await update.message.reply_text(plan_text, reply_markup=get_plan_selection_keyboard())
            return SELECTING_PLAN

async def handle_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает подтверждение новой подписки при наличии активной"""
    if not update.message:
        return ConversationHandler.END

    text = update.message.text.strip()

    if text == "✅ Да, хочу купить ещё одно":
        context.user_data['selected_duration'] = None
        context.user_data['promo_code'] = None
        plan_text = """📋 Выбери тариф подписки:

1 месяц - 199 ₽
3 месяца - 550 ₽

💡 При оплате за 3 месяца - скидка!"""
        await update.message.reply_text(plan_text, reply_markup=get_plan_selection_keyboard())
        return SELECTING_PLAN
    elif text == "📄 Посмотреть мои подписки":
        await handle_my_cabinet(update, context)
        return ConversationHandler.END
    elif text == "🔙 Назад":
        await start(update, context)
        return ConversationHandler.END
    else:
        await update.message.reply_text("Пожалуйста, выбери вариант с кнопок ниже.")
        return CONFIRM_NEW_SUBSCRIPTION

async def apply_promo_code(code: str, db: AsyncSession) -> tuple[PromoCode | None, float, int, str]:
    stmt = select(PromoCode).where(
        PromoCode.code == code.upper(),
        PromoCode.is_active == True
    )
    result = await db.execute(stmt)
    promo = result.scalars().first()

    if not promo:
        return None, 0.0, 0, "Промокод не найден"

    if promo.max_uses and promo.current_uses >= promo.max_uses:
        return None, 0.0, 0, "Промокод исчерпан"

    if promo.expire_at and promo.expire_at < datetime.now():
        return None, 0.0, 0, "Промокод истёк"

    discount = 0.0
    bonus_days = 0

    if promo.type == PromoCodeType.PERCENT:
        discount = promo.value / 100.0
    elif promo.type == PromoCodeType.FIXED:
        discount = promo.value
    elif promo.type == PromoCodeType.BONUS_DAYS:
        bonus_days = promo.value

    return promo, discount, bonus_days, ""

async def handle_plan_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает выбор тарифа и создаёт платёж в ЮKassa"""
    telegram_user = update.effective_user
    if not telegram_user or not update.message:
        return ConversationHandler.END

    text = update.message.text.strip()
    user_id = telegram_user.id
    username = telegram_user.username or f"user_{user.id}"

    if text == "🎟️ Ввести промокод":
        await update.message.reply_text("Введите промокод:", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 Назад")]], resize_keyboard=True))
        return ENTERING_PROMO_CODE

    duration_months = 0
    base_price = 0.0
    if "1 месяц" in text or "199 ₽" in text:
        duration_months = 1
        base_price = PRICE_1_MONTH
        logger.info(f"Пользователь {user_id} выбрал тариф на 1 месяц")
    elif "3 месяца" in text or "550 ₽" in text:
        duration_months = 3
        base_price = PRICE_3_MONTHS
        logger.info(f"Пользователь {user_id} выбрал тариф на 3 месяца")
    elif text == "🔙 Назад":
        await start(update, context)
        return ConversationHandler.END
    else:
        await update.message.reply_text("Пожалуйста, выбери тариф с кнопок ниже.")
        return SELECTING_PLAN

    context.user_data['selected_duration'] = duration_months
    final_price = base_price
    bonus_days = 0
    promo = None

    if 'promo_code' in context.user_data and context.user_data['promo_code']:
        async with AsyncSessionLocal() as db:
            promo, discount, bd, msg = await apply_promo_code(context.user_data['promo_code'], db)
            if promo:
                bonus_days = bd
                if discount > 0:
                    if promo.type == PromoCodeType.PERCENT:
                        final_price = base_price * (1 - discount)
                    elif promo.type == PromoCodeType.FIXED:
                        final_price = max(0, base_price - discount)

    try:
        yk_service = AsyncYooKassaService()
        payment = await yk_service.create_payment(
            amount=final_price,
            description=f"VPN подписка на {duration_months} мес" + (f" +{bonus_days} дней" if bonus_days else ""),
            return_url="https://t.me/abusee_vpnbot",
            metadata={
                "telegram_id": str(user_id),
                "username": username,
                "duration_months": str(duration_months),
                "bonus_days": str(bonus_days),
                "is_extend": "false",
                "promo_code_id": str(promo.id) if promo else ""
            }
        )

        async with AsyncSessionLocal() as db:
            db_payment = Payment(
                payment_id=payment["id"],
                status=payment["status"],
                amount=final_price,
                currency="RUB",
                description=f"VPN подписка на {duration_months} мес",
                telegram_id=user_id,
                promo_code_id=promo.id if promo else None
            )
            db.add(db_payment)
            await db.commit()
            await db.refresh(db_payment)
            logger.info(f"Платёж {payment['id']} сохранён в БД")

        confirmation_url = payment["confirmation"]["confirmation_url"]
        message = f"""⏳ Ожидание оплаты!

Сумма к оплате: {final_price:.2f} ₽
{f"Бонусные дни: {bonus_days}" if bonus_days else ""}

Для оплаты перейдите по ссылке:
{confirmation_url}

После оплаты бот автоматически отправит вам доступ к VPN!

Если хотите отменить оплату - нажмите кнопку ниже."""
        await update.message.reply_text(message, reply_markup=get_payment_waiting_keyboard())

        return WAITING_FOR_PAYMENT
    except Exception as e:
        logger.exception(f"Ошибка при создании платежа для пользователя {user_id}: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при создании платежа. Попробуйте позже или напишите в поддержку."
        )
        return ConversationHandler.END

async def handle_entering_promo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message:
        return ConversationHandler.END

    text = update.message.text.strip()
    if text == "🔙 Назад":
        await update.message.reply_text("Выберите тариф:", reply_markup=get_plan_selection_keyboard())
        return SELECTING_PLAN

    async with AsyncSessionLocal() as db:
        promo, discount, bonus_days, msg = await apply_promo_code(text, db)
        if promo:
            context.user_data['promo_code'] = text
            msg_text = f"✅ Промокод применён!"
            if promo.type == PromoCodeType.PERCENT:
                msg_text += f"\nСкидка: {promo.value}%"
            elif promo.type == PromoCodeType.FIXED:
                msg_text += f"\nСкидка: {promo.value} ₽"
            elif promo.type == PromoCodeType.BONUS_DAYS:
                msg_text += f"\nБонус: {promo.value} дней"
            await update.message.reply_text(msg_text + "\n\nТеперь выберите тариф:", reply_markup=get_plan_selection_keyboard())
            return SELECTING_PLAN
        else:
            await update.message.reply_text(f"❌ {msg}\nВведите промокод снова или вернитесь:", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🎟️ Попробовать ещё раз"), KeyboardButton("🔙 Назад")]], resize_keyboard=True))
            return ENTERING_PROMO_CODE

async def handle_extend_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начинает процесс продления подписки"""
    context.user_data['selected_duration'] = None
    context.user_data['promo_code'] = None
    await update.message.reply_text(
        "📋 Выбери на сколько хочешь продлить подписку:",
        reply_markup=get_extend_plan_keyboard()
    )
    return SELECTING_EXTEND_PLAN

async def handle_extend_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает выбор тарифа для продления"""
    telegram_user = update.effective_user
    if not telegram_user or not update.message:
        return ConversationHandler.END

    text = update.message.text.strip()
    user_id = telegram_user.id
    username = telegram_user.username or f"user_{user_id}"

    if text == "🎟️ Ввести промокод":
        await update.message.reply_text("Введите промокод:", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 Назад")]], resize_keyboard=True))
        return ENTERING_PROMO_CODE

    duration_months = 0
    base_price = 0.0
    if "1 месяц" in text or "199 ₽" in text:
        duration_months = 1
        base_price = PRICE_1_MONTH
        logger.info(f"Пользователь {user_id} выбрал продление на 1 месяц")
    elif "3 месяца" in text or "550 ₽" in text:
        duration_months = 3
        base_price = PRICE_3_MONTHS
        logger.info(f"Пользователь {user_id} выбрал продление на 3 месяца")
    elif text == "🔙 Назад":
        await handle_my_cabinet(update, context)
        return ConversationHandler.END
    else:
        await update.message.reply_text("Пожалуйста, выбери вариант из кнопок ниже.")
        return SELECTING_EXTEND_PLAN

    context.user_data['selected_duration'] = duration_months
    final_price = base_price
    bonus_days = 0
    promo = None

    if 'promo_code' in context.user_data and context.user_data['promo_code']:
        async with AsyncSessionLocal() as db:
            promo, discount, bd, msg = await apply_promo_code(context.user_data['promo_code'], db)
            if promo:
                bonus_days = bd
                if discount > 0:
                    if promo.type == PromoCodeType.PERCENT:
                        final_price = base_price * (1 - discount)
                    elif promo.type == PromoCodeType.FIXED:
                        final_price = max(0, base_price - discount)

    try:
        yk_service = AsyncYooKassaService()
        payment = await yk_service.create_payment(
            amount=final_price,
            description=f"Продление подписки на {duration_months} мес" + (f" +{bonus_days} дней" if bonus_days else ""),
            return_url="https://t.me/abusee_vpnbot",
            metadata={
                "telegram_id": str(user_id),
                "username": username,
                "duration_months": str(duration_months),
                "bonus_days": str(bonus_days),
                "is_extend": "true",
                "promo_code_id": str(promo.id) if promo else ""
            }
        )

        async with AsyncSessionLocal() as db:
            db_payment = Payment(
                payment_id=payment["id"],
                status=payment["status"],
                amount=final_price,
                currency="RUB",
                description=f"Продление подписки на {duration_months} мес",
                telegram_id=user_id,
                promo_code_id=promo.id if promo else None
            )
            db.add(db_payment)
            await db.commit()
            await db.refresh(db_payment)
            logger.info(f"Платёж {payment['id']} сохранён в БД")

        confirmation_url = payment["confirmation"]["confirmation_url"]
        message = f"""⏳ Ожидание оплаты!

Сумма к оплате: {final_price:.2f} ₽
{f"Бонусные дни: {bonus_days}" if bonus_days else ""}

Для оплаты перейдите по ссылке:
{confirmation_url}

После оплаты бот автоматически продлит вашу подписку!

Если хотите отменить оплату - нажмите кнопку ниже."""
        await update.message.reply_text(message, reply_markup=get_payment_waiting_keyboard())

        return WAITING_FOR_PAYMENT
    except Exception as e:
        logger.exception(f"Ошибка при создании платежа для пользователя {user_id}: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при создании платежа. Попробуйте позже или напишите в поддержку."
        )
        return ConversationHandler.END

async def handle_waiting_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает отмену оплаты"""
    if not update.message:
        return ConversationHandler.END

    text = update.message.text.strip()

    if text == "❌ Отменить оплату":
        await update.message.reply_text(
            "✅ Оплата отменена!\nЕсли передумаете, всегда можете вернуться и оплатить.",
            reply_markup=get_main_keyboard()
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text("Пожалуйста, используйте кнопки ниже.")
        return WAITING_FOR_PAYMENT

async def process_payment(payment_id: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает успешный платёж"""
    logger.info(f"Обрабатываем платёж {payment_id}")
    try:
        yk_service = AsyncYooKassaService()
        yk_payment = await yk_service.get_payment(payment_id)
        
        if yk_payment["status"] != "succeeded":
            logger.warning(f"Платёж {payment_id} имеет статус {yk_payment['status']}, не succeeded")
            return

        async with AsyncSessionLocal() as db:
            stmt = select(Payment).where(Payment.payment_id == payment_id)
            result = await db.execute(stmt)
            db_payment = result.scalars().first()
            
            if not db_payment:
                logger.error(f"Платёж {payment_id} не найден в БД")
                return
            
            if db_payment.processed:
                logger.info(f"Платёж {payment_id} уже был обработан")
                return
            
            db_payment.status = yk_payment["status"]
            
            metadata = yk_payment.get("metadata", {})
            telegram_id = int(metadata.get("telegram_id", 0))
            username = metadata.get("username", "")
            duration_months = int(metadata.get("duration_months", 0))
            bonus_days = int(metadata.get("bonus_days", 0))
            is_extend = metadata.get("is_extend", "false").lower() == "true"
            promo_code_id = metadata.get("promo_code_id", "")
            
            if promo_code_id:
                stmt_promo = select(PromoCode).where(PromoCode.id == int(promo_code_id))
                result_promo = await db.execute(stmt_promo)
                promo = result_promo.scalars().first()
                if promo:
                    promo.current_uses += 1
                    activation = PromoActivation(promo_code_id=promo.id, user_id=db_payment.id)
                    db.add(activation)
                    await db.commit()
            
            vpn_service = AsyncVPNService(db)
            
            if is_extend:
                stmt_user = select(User).where(User.telegram_id == telegram_id).order_by(User.created_at.desc())
                result_user = await db.execute(stmt_user)
                user = result_user.scalars().first()
                
                if user:
                    updated_user = await vpn_service.extend_subscription(user, duration_months, bonus_days)
                    if user.referrer_id:
                        stmt_ref_user = select(User).where(User.id == user.referrer_id)
                        ref_result = await db.execute(stmt_ref_user)
                        ref_user = ref_result.scalars().first()
                        if ref_user:
                            await vpn_service.check_and_update_vip_status(ref_user)
                    
                    expire_str = updated_user.expire_at.strftime("%d.%m.%Y %H:%M")
                    duration_word = "месяц" if duration_months == 1 else "месяца"
                    message = f"""✅ Подписка успешно продлена!

📅 Добавлено: {duration_months} {duration_word}{f" + {bonus_days} дней" if bonus_days else ""}
📅 Новая дата окончания: {expire_str}

Ты можешь продолжать пользоваться VPN! 🚀"""
                    await context.bot.send_message(
                        chat_id=telegram_id,
                        text=message,
                        reply_markup=get_main_keyboard()
                    )
            else:
                db_user, _, subscription_url = await vpn_service.create_new_user_with_duration(
                    telegram_id, username, duration_months, bonus_days
                )
                db_payment.user_id = db_user.id
                await db.commit()
                
                if db_user.referrer_id:
                    stmt_ref = select(User).where(User.id == db_user.referrer_id)
                    ref_result = await db.execute(stmt_ref)
                    ref_user = ref_result.scalars().first()
                    if ref_user:
                        await vpn_service.check_and_update_vip_status(ref_user)
                
                if db_user and subscription_url:
                    expire_str = db_user.expire_at.strftime("%d.%m.%Y %H:%M")
                    duration_word = "месяц" if duration_months == 1 else "месяца"
                    message = f"""🎉 Оплата успешна! Твой VPN готов!

📅 Срок подписки: {duration_months} {duration_word}{f" + {bonus_days} дней" if bonus_days else ""}
📅 Действует до: {expire_str}
📖 Инструкция к установке: {INSTALLATION_GUIDE_URL}

🔗 Ссылка для подключения:
{subscription_url}

Удачного использования! 🚀"""
                    await context.bot.send_message(
                        chat_id=telegram_id,
                        text=message,
                        reply_markup=get_main_keyboard()
                    )
            
            db_payment.processed = True
            await db.commit()
            logger.info(f"Платёж {payment_id} успешно обработан")
    except Exception as e:
        logger.exception(f"Ошибка при обработке платежа {payment_id}: {e}")

async def check_payments(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Периодически проверяет статус платежей"""
    async with AsyncSessionLocal() as db:
        stmt = select(Payment).where(Payment.processed == False)
        result = await db.execute(stmt)
        payments = result.scalars().all()
        logger.info(f"Проверяю статусы {len(payments)} платежей")
        
        for payment in payments:
            try:
                await process_payment(payment.payment_id, context)
            except Exception as e:
                logger.exception(f"Ошибка при обработке платежа {payment.payment_id}: {e}")

async def handle_my_cabinet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает информацию о подписке пользователя"""
    telegram_user = update.effective_user
    if not telegram_user or not update.message:
        return

    user_id = telegram_user.id
    logger.info(f"Пользователь {user_id} открыл кабинет")

    async with AsyncSessionLocal() as db:
        stmt = select(User).where(User.telegram_id == user_id).order_by(User.created_at.desc())
        result = await db.execute(stmt)
        users = result.scalars().all()
        
        if not users:
            await update.message.reply_text(
                "❌ У вас нет подписок! Начните с кнопки «🚀 Получить VPN».",
                reply_markup=get_main_keyboard()
            )
            return

        now = datetime.now()
        active_users = [u for u in users if u.is_active and u.expire_at > now]
        expired_users = [u for u in users if not u.is_active or u.expire_at <= now]
        
        stmt_ref = select(Referral).where(Referral.referrer_id == users[0].id)
        ref_result = await db.execute(stmt_ref)
        referrals = ref_result.scalars().all()
        
        active_referrals = 0
        for ref in referrals:
            ref_user_stmt = select(User).where(User.id == ref.referred_id, User.is_active == True, User.expire_at > now, User.is_trial == False)
            ref_user_result = await db.execute(ref_user_stmt)
            if ref_user_result.scalars().first():
                active_referrals += 1

        message_parts = ["📄 Ваш кабинет:\n"]
        message_parts.append(f"🤝 Приглашено пользователей: {len(referrals)}")
        message_parts.append(f"💎 Активные платящие рефералы: {active_referrals}")
        message_parts.append(f"{'✅ VIP-статус активен!' if users[0].is_vip else ''}\n")

        if active_users:
            message_parts.append("✅ Активные подписки:\n")
            for i, user in enumerate(active_users, 1):
                expire_str = user.expire_at.strftime("%d.%m.%Y %H:%M")
                part = f"""\n{i}. {'🎁 Тестовая' if user.is_trial else '💳 Платная'} подписка
   📅 До: {expire_str}
   🔗 Ссылка: {user.subscription_url}
"""
                message_parts.append(part)

        if expired_users:
            if active_users:
                message_parts.append("\n\n⏳ Истекшие подписки:\n")
            else:
                message_parts.append("⏳ Истекшие подписки:\n")
            for i, user in enumerate(expired_users, 1):
                expire_str = user.expire_at.strftime("%d.%m.%Y %H:%M")
                part = f"""\n{i}. Подписка истекла {expire_str}
"""
                message_parts.append(part)

        await update.message.reply_text(
            "".join(message_parts),
            reply_markup=get_subscription_keyboard()
        )

async def handle_referral_program(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_user = update.effective_user
    if not telegram_user or not update.message:
        return

    user_id = telegram_user.id

    async with AsyncSessionLocal() as db:
        stmt = select(User).where(User.telegram_id == user_id).order_by(User.created_at.desc())
        result = await db.execute(stmt)
        user = result.scalars().first()
        
        if not user:
            await update.message.reply_text("❌ Сначала получите VPN!", reply_markup=get_main_keyboard())
            return

        stmt_ref = select(Referral).where(Referral.referrer_id == user.id)
        ref_result = await db.execute(stmt_ref)
        referrals = ref_result.scalars().all()
        
        total_registrations = len(referrals)
        trial_activated = sum(1 for r in referrals if r.trial_activated)
        
        now = datetime.now()
        paying = 0
        active_paying = 0
        for ref in referrals:
            ref_user_stmt = select(User).where(User.id == ref.referred_id)
            ref_user_result = await db.execute(ref_user_stmt)
            ref_user = ref_user_result.scalars().first()
            if ref_user:
                if not ref_user.is_trial:
                    paying += 1
                if ref_user.is_active and ref_user.expire_at > now and not ref_user.is_trial:
                    active_paying += 1

        bot_username = (await context.bot.get_me()).username
        ref_link = f"https://t.me/{bot_username}?start={user.id}"

        message = f"""🤝 Партнёрская программа

👥 Всего регистраций: {total_registrations}
🎁 Активировали тест: {trial_activated}
💳 Оплатили: {paying}
💎 Активные платящие: {active_paying}

✅ Если у вас 3+ активных платящих реферала - вы получаете бесплатный VIP!

🔗 Ваша реферальная ссылка:
{ref_link}"""
        await update.message.reply_text(message, reply_markup=get_main_keyboard())

async def handle_support_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "🆘 Выберите категорию проблемы:",
        reply_markup=get_support_category_keyboard()
    )
    return SUPPORT_CATEGORY

async def handle_support_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message:
        return ConversationHandler.END

    text = update.message.text.strip()
    if text == "🔙 Назад":
        await start(update, context)
        return ConversationHandler.END

    category_map = {
        "❌ VPN не работает": SupportTicketCategory.VPN_NOT_WORKING,
        "📺 YouTube не работает": SupportTicketCategory.YOUTUBE_NOT_WORKING,
        "🐌 Низкая скорость": SupportTicketCategory.LOW_SPEED,
        "💳 Ошибка оплаты": SupportTicketCategory.PAYMENT_ERROR,
        "📝 Другое": SupportTicketCategory.OTHER,
    }

    category = category_map.get(text)
    if not category:
        await update.message.reply_text("Пожалуйста, выберите категорию из списка.")
        return SUPPORT_CATEGORY

    context.user_data['support_category'] = category
    await update.message.reply_text(
        "Опишите вашу проблему:",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 Назад")]], resize_keyboard=True)
    )
    return SUPPORT_MESSAGE

async def handle_support_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.effective_user:
        return ConversationHandler.END

    text = update.message.text.strip()
    if text == "🔙 Назад":
        await update.message.reply_text("Выберите категорию проблемы:", reply_markup=get_support_category_keyboard())
        return SUPPORT_CATEGORY

    telegram_user = update.effective_user
    category = context.user_data.get('support_category', SupportTicketCategory.OTHER)

    async with AsyncSessionLocal() as db:
        stmt_user = select(User).where(User.telegram_id == telegram_user.id).order_by(User.created_at.desc())
        user_result = await db.execute(stmt_user)
        user = user_result.scalars().first()
        
        ticket = SupportTicket(
            user_id=user.id if user else None,
            category=category,
            message=text
        )
        db.add(ticket)
        await db.commit()
        await db.refresh(ticket)

        admin_msg = f"""🆘 Новый тикет #{ticket.id}!
👤 Пользователь: @{telegram_user.username or telegram_user.id}
📂 Категория: {category.value}
💬 Сообщение:
{text}
"""
        if user:
            admin_msg += f"\n📊 Информация о пользователе:\n"
            admin_msg += f"   VPN Email: {user.vpn_email}\n"
            admin_msg += f"   Expire: {user.expire_at.strftime('%d.%m.%Y %H:%M') if user.expire_at else 'N/A'}\n"
        
        try:
            await context.bot.send_message(chat_id=TELEGRAM_ADMIN_ID, text=admin_msg)
        except Exception as e:
            logger.exception(f"Error sending ticket to admin: {e}")

        await update.message.reply_text("✅ Ваш запрос отправлен! Мы ответим вам в ближайшее время.", reply_markup=get_main_keyboard())
        return ConversationHandler.END

async def handle_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or str(update.effective_user.id) != TELEGRAM_ADMIN_ID:
        await update.message.reply_text("❌ У вас нет доступа к админ-панели.")
        return
    await update.message.reply_text("👨‍💼 Админ-панель:", reply_markup=get_admin_keyboard())

async def handle_admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or str(update.effective_user.id) != TELEGRAM_ADMIN_ID:
        return

    async with AsyncSessionLocal() as db:
        now = datetime.now()
        stmt_total = select(func.count(User.id))
        stmt_active = select(func.count(User.id)).where(User.is_active == True, User.expire_at > now)
        stmt_trial = select(func.count(User.id)).where(User.is_trial == True)
        stmt_paying = select(func.count(User.id)).where(User.is_active == True, User.expire_at > now, User.is_trial == False)
        stmt_payments = select(func.count(Payment.id)).where(Payment.processed == True)

        total = (await db.execute(stmt_total)).scalar()
        active = (await db.execute(stmt_active)).scalar()
        trial = (await db.execute(stmt_trial)).scalar()
        paying = (await db.execute(stmt_paying)).scalar()
        payments_count = (await db.execute(stmt_payments)).scalar()

        message = f"""📊 Статистика:
👥 Всего пользователей: {total}
✅ Активных: {active}
🎁 Тестовых: {trial}
💳 Платящих: {paying}
💰 Оплат: {payments_count}
"""
        await update.message.reply_text(message)

async def handle_admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.effective_user or str(update.effective_user.id) != TELEGRAM_ADMIN_ID:
        return ConversationHandler.END
    await update.message.reply_text("Выберите категорию для рассылки:\n- all\n- paying\n- trial\n- expired\n- vip")
    return ADMIN_BROADCAST_CATEGORY

async def handle_admin_broadcast_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.effective_user or str(update.effective_user.id) != TELEGRAM_ADMIN_ID:
        return ConversationHandler.END
    text = update.message.text.strip().lower()
    try:
        category = BroadcastCategory(text)
        context.user_data['broadcast_category'] = category
        await update.message.reply_text("Введите текст рассылки:")
        return ADMIN_BROADCAST_TEXT
    except ValueError:
        await update.message.reply_text("Неверная категория!")
        return ADMIN_BROADCAST_CATEGORY

async def handle_admin_broadcast_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.effective_user or str(update.effective_user.id) != TELEGRAM_ADMIN_ID:
        return ConversationHandler.END
    text = update.message.text.strip()
    category = context.user_data.get('broadcast_category', BroadcastCategory.ALL)

    async with AsyncSessionLocal() as db:
        now = datetime.now()
        stmt = select(User)
        if category == BroadcastCategory.PAYING:
            stmt = stmt.where(User.is_active == True, User.expire_at > now, User.is_trial == False)
        elif category == BroadcastCategory.TRIAL:
            stmt = stmt.where(User.is_trial == True)
        elif category == BroadcastCategory.EXPIRED:
            stmt = stmt.where(or_(User.is_active == False, User.expire_at <= now))
        elif category == BroadcastCategory.VIP:
            stmt = stmt.where(User.is_vip == True)
        
        result = await db.execute(stmt)
        users = result.scalars().all()
        
        broadcast = Broadcast(category=category, text=text)
        db.add(broadcast)
        await db.commit()
        await db.refresh(broadcast)
        
        sent = 0
        for user in users:
            try:
                await context.bot.send_message(chat_id=user.telegram_id, text=text)
                sent += 1
            except Exception as e:
                logger.exception(f"Error sending to {user.telegram_id}: {e}")
        
        broadcast.sent_count = sent
        await db.commit()
        await update.message.reply_text(f"✅ Рассылка отправлена! Получатели: {sent}/{len(users)}")
        return ConversationHandler.END

async def handle_admin_promo_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.effective_user or str(update.effective_user.id) != TELEGRAM_ADMIN_ID:
        return ConversationHandler.END
    await update.message.reply_text("Введите код промокода:")
    return ADMIN_PROMO_CODE

async def handle_admin_promo_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.effective_user or str(update.effective_user.id) != TELEGRAM_ADMIN_ID:
        return ConversationHandler.END
    context.user_data['promo_code'] = update.message.text.strip().upper()
    await update.message.reply_text("Введите тип (percent/fixed/bonus_days):")
    return ADMIN_PROMO_TYPE

async def handle_admin_promo_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.effective_user or str(update.effective_user.id) != TELEGRAM_ADMIN_ID:
        return ConversationHandler.END
    text = update.message.text.strip().lower()
    try:
        ptype = PromoCodeType(text)
        context.user_data['promo_type'] = ptype
        await update.message.reply_text("Введите значение (число):")
        return ADMIN_PROMO_VALUE
    except ValueError:
        await update.message.reply_text("Неверный тип!")
        return ADMIN_PROMO_TYPE

async def handle_admin_promo_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.effective_user or str(update.effective_user.id) != TELEGRAM_ADMIN_ID:
        return ConversationHandler.END
    try:
        context.user_data['promo_value'] = int(update.message.text.strip())
        await update.message.reply_text("Введите максимум использований (или 0 для неограниченно):")
        return ADMIN_PROMO_MAX_USES
    except ValueError:
        await update.message.reply_text("Введите число!")
        return ADMIN_PROMO_VALUE

async def handle_admin_promo_max_uses(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.effective_user or str(update.effective_user.id) != TELEGRAM_ADMIN_ID:
        return ConversationHandler.END
    try:
        max_uses = int(update.message.text.strip())
        context.user_data['promo_max_uses'] = max_uses if max_uses > 0 else None
        await update.message.reply_text("Введите дату истечения в формате DD.MM.YYYY (или 0 для без срока):")
        return ADMIN_PROMO_EXPIRE
    except ValueError:
        await update.message.reply_text("Введите число!")
        return ADMIN_PROMO_MAX_USES

async def handle_admin_promo_expire(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.effective_user or str(update.effective_user.id) != TELEGRAM_ADMIN_ID:
        return ConversationHandler.END
    text = update.message.text.strip()
    expire_at = None
    if text != "0":
        try:
            expire_at = datetime.strptime(text, "%d.%m.%Y")
        except ValueError:
            await update.message.reply_text("Неверный формат!")
            return ADMIN_PROMO_EXPIRE

    async with AsyncSessionLocal() as db:
        promo = PromoCode(
            code=context.user_data['promo_code'],
            type=context.user_data['promo_type'],
            value=context.user_data['promo_value'],
            max_uses=context.user_data['promo_max_uses'],
            expire_at=expire_at,
            is_active=True
        )
        db.add(promo)
        await db.commit()
        await db.refresh(promo)
        await update.message.reply_text(f"✅ Промокод создан!\nКод: {promo.code}\nТип: {promo.type.value}\nЗначение: {promo.value}", reply_markup=get_admin_keyboard())
        return ConversationHandler.END

async def send_reminders(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет напоминания об истечении подписки"""
    async with AsyncSessionLocal() as db:
        now = datetime.now()
        seven_days = timedelta(days=7)
        three_days = timedelta(days=3)
        one_day = timedelta(days=1)
        post_expire_3d = timedelta(days=3)

        stmt_7d = select(User).where(
            User.is_active == True,
            User.expire_at > now,
            User.expire_at <= now + seven_days,
            User.reminder_7d_sent == False
        )
        result_7d = await db.execute(stmt_7d)
        users_7d = result_7d.scalars().all()
        
        for user in users_7d:
            try:
                await context.bot.send_message(
                    chat_id=user.telegram_id,
                    text=f"""⚠️ Напоминание!

Ваша подписка истекает через 7 дней ({user.expire_at.strftime("%d.%m.%Y %H:%M")}).

Чтобы продлить, нажмите на «🔄 Продлить подписку» в меню!"""
                )
                user.reminder_7d_sent = True
            except Exception as e:
                logger.exception(f"Не удалось отправить напоминание пользователю {user.telegram_id}: {e}")

        stmt_3d = select(User).where(
            User.is_active == True,
            User.expire_at > now,
            User.expire_at <= now + three_days,
            User.reminder_3d_sent == False
        )
        result_3d = await db.execute(stmt_3d)
        users_3d = result_3d.scalars().all()
        
        for user in users_3d:
            try:
                await context.bot.send_message(
                    chat_id=user.telegram_id,
                    text=f"""⚠️ Напоминание!

Ваша подписка истекает через 3 дня ({user.expire_at.strftime("%d.%m.%Y %H:%M")}).

Чтобы продлить, нажмите на «🔄 Продлить подписку» в меню!"""
                )
                user.reminder_3d_sent = True
            except Exception as e:
                logger.exception(f"Не удалось отправить напоминание пользователю {user.telegram_id}: {e}")

        stmt_1d = select(User).where(
            User.is_active == True,
            User.expire_at > now,
            User.expire_at <= now + one_day,
            User.reminder_1d_sent == False
        )
        result_1d = await db.execute(stmt_1d)
        users_1d = result_1d.scalars().all()
        
        for user in users_1d:
            try:
                await context.bot.send_message(
                    chat_id=user.telegram_id,
                    text=f"""🔴 Внимание!

Ваша подписка истекает через 1 день ({user.expire_at.strftime("%d.%m.%Y %H:%M")}).

Чтобы не остаться без VPN, продлите подписку прямо сейчас!"""
                )
                user.reminder_1d_sent = True
            except Exception as e:
                logger.exception(f"Не удалось отправить напоминание пользователю {user.telegram_id}: {e}")

        stmt_expired = select(User).where(
            User.is_active == True,
            User.expire_at <= now,
            User.reminder_expired_sent == False
        )
        result_expired = await db.execute(stmt_expired)
        users_expired = result_expired.scalars().all()
        
        for user in users_expired:
            try:
                await context.bot.send_message(
                    chat_id=user.telegram_id,
                    text=f"""❌ Подписка истекла!

Ваша подписка истекла {user.expire_at.strftime("%d.%m.%Y %H:%M")}.

Чтобы восстановить доступ, продлите подписку в меню!"""
                )
                user.reminder_expired_sent = True
                user.is_active = False
            except Exception as e:
                logger.exception(f"Не удалось отправить напоминание пользователю {user.telegram_id}: {e}")

        stmt_post_expired = select(User).where(
            User.is_active == False,
            User.reminder_post_expired_3d_sent == False,
            User.expire_at <= now - post_expire_3d
        )
        result_post_expired = await db.execute(stmt_post_expired)
        users_post_expired = result_post_expired.scalars().all()
        
        for user in users_post_expired:
            try:
                await context.bot.send_message(
                    chat_id=user.telegram_id,
                    text=f"""😔 Мы скучаем!

Ваша подписка истекла уже 3 дня назад.

Вернитесь и получите скидку на продление!"""
                )
                user.reminder_post_expired_3d_sent = True
            except Exception as e:
                logger.exception(f"Не удалось отправить напоминание пользователю {user.telegram_id}: {e}")

        await db.commit()

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    logger.exception("Bot error", exc_info=err)
    if isinstance(err, Conflict):
        logger.error(
            "Telegram getUpdates conflict: запущен другой экземпляр бота с этим токеном. Останови его."
        )
        try:
            await context.application.stop()
        except Exception:
            pass

def main() -> None:
    lock_path = Path(__file__).parent / ".bot.lock"
    try:
        with open(lock_path, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            logger.info("Бот запущен, блокировка получена")
            
            application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

            conv_handler = ConversationHandler(
                entry_points=[
                    MessageHandler(filters.Regex(r"^🚀 Получить VPN$"), handle_get_vpn_start),
                    MessageHandler(filters.Regex(r"^🔄 Продлить подписку$"), handle_extend_start),
                    MessageHandler(filters.Regex(r"^🆘 Поддержка$"), handle_support_start),
                    MessageHandler(filters.Regex(r"^📢 Рассылка$"), handle_admin_broadcast_start),
                    MessageHandler(filters.Regex(r"^🎁 Промокоды$"), handle_admin_promo_start),
                ],
                states={
                    SELECTING_PLAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_plan_selection)],
                    CONFIRM_NEW_SUBSCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_confirmation)],
                    SELECTING_EXTEND_PLAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_extend_plan)],
                    WAITING_FOR_PAYMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_waiting_payment)],
                    ENTERING_PROMO_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_entering_promo)],
                    SUPPORT_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_support_category)],
                    SUPPORT_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_support_message)],
                    ADMIN_BROADCAST_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_broadcast_category)],
                    ADMIN_BROADCAST_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_broadcast_text)],
                    ADMIN_PROMO_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_promo_code)],
                    ADMIN_PROMO_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_promo_type)],
                    ADMIN_PROMO_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_promo_value)],
                    ADMIN_PROMO_MAX_USES: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_promo_max_uses)],
                    ADMIN_PROMO_EXPIRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_promo_expire)],
                },
                fallbacks=[
                    MessageHandler(filters.Regex(r"^🔙 Назад$"), lambda u, c: start(u, c) or ConversationHandler.END),
                    CommandHandler("cancel", lambda u, c: start(u, c) or ConversationHandler.END),
                    MessageHandler(filters.Regex(r"^❌ Отменить оплату$"), lambda u, c: start(u, c) or ConversationHandler.END),
                ],
            )
            application.add_handler(conv_handler)
            application.add_handler(CommandHandler("start", start))
            application.add_handler(CommandHandler("admin", handle_admin))
            application.add_handler(MessageHandler(filters.Regex(r"^📄 Мой кабинет$"), handle_my_cabinet))
            application.add_handler(MessageHandler(filters.Regex(r"^🤝 Партнёрская программа$"), handle_referral_program))
            application.add_handler(MessageHandler(filters.Regex(r"^🏠 Главное меню$"), start))
            application.add_handler(MessageHandler(filters.Regex(r"^📊 Статистика$"), handle_admin_stats))
            application.add_error_handler(on_error)

            job_queue = application.job_queue
            job_queue.run_repeating(check_payments, interval=60, first=5)
            job_queue.run_repeating(send_reminders, interval=3600, first=10)

            logger.info("🚀 Запускаем бота...")
            application.run_polling()

    except IOError:
        logger.error("Бот уже запущен (lock). Останови другие экземпляры и запусти снова.")
        return
    except Conflict:
        logger.error("Telegram getUpdates conflict: запущен другой экземпляр бота с этим токеном. Останови его.")
        return

if __name__ == "__main__":
    main()
