import uuid
import logging
from datetime import datetime, timedelta
from typing import Tuple, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.user import User, Server, Referral
from app.services.xui_client import AsyncXUIClient

logger = logging.getLogger(__name__)


class AsyncVPNService:
    DEFAULT_MONTHS = 1
    DEFAULT_TRAFFIC_LIMIT_GB = 0  # Безлимитный трафик
    DEFAULT_DEVICE_LIMIT = 3
    DEFAULT_PROTOCOL = "all"

    def __init__(self, db: AsyncSession):
        self.db = db
        self.xui_client = AsyncXUIClient()
        self.inbound_id = 1  # По умолчанию
        self._inbound_initialized = False
    
    async def _ensure_inbound(self):
        if not self._inbound_initialized:
            self.inbound_id = await self.xui_client.find_vless_inbound() or 1
            logger.info(f"Using inbound ID: {self.inbound_id}")
            self._inbound_initialized = True
    
    async def has_active_subscriptions(self, telegram_id: int) -> bool:
        now = datetime.now()
        stmt = select(User).where(
            User.telegram_id == telegram_id,
            User.is_active == True,
            User.expire_at > now
        )
        result = await self.db.execute(stmt)
        active_users = result.scalars().all()
        return len(active_users) > 0
    
    async def get_best_server(self) -> Optional[Server]:
        stmt = select(Server).where(
            Server.is_active == True,
            Server.current_users < Server.max_users
        ).order_by(Server.current_users.asc())
        result = await self.db.execute(stmt)
        return result.scalars().first()
    
    async def create_trial_user(
        self, telegram_id: int, base_username: str, referrer_id: Optional[int] = None
    ) -> Tuple[User, str, str]:
        await self._ensure_inbound()
        username = await self._build_username(telegram_id, base_username)
        user_uuid = str(uuid.uuid4())
        expire_at = datetime.now() + timedelta(days=3)
        expire_timestamp = int(expire_at.timestamp() * 1000)

        logger.info(f"Creating trial user for telegram_id {telegram_id}: {username}")

        server = await self.get_best_server()

        db_user = User(
            telegram_id=telegram_id,
            username=username,
            vpn_email=username,
            uuid=user_uuid,
            expire_at=expire_at,
            traffic_limit_gb=0,
            device_limit=3,
            is_active=True,
            protocol=self.DEFAULT_PROTOCOL,
            is_trial=True,
            trial_used=True,
            server_id=server.id if server else None
        )

        self.db.add(db_user)
        await self.db.commit()
        await self.db.refresh(db_user)

        if referrer_id:
            db_user.referrer_id = referrer_id
            referral = Referral(referrer_id=referrer_id, referred_id=db_user.id)
            self.db.add(referral)
            await self.db.commit()

        vless_url = ""
        subscription_url = ""
        try:
            subscription_url = await self.xui_client.add_client_to_all_inbounds(
                email=username,
                uuid=user_uuid,
                expire_timestamp=expire_timestamp,
                device_limit=3,
                enable=True
            )

            db_user.subscription_url = subscription_url
            await self.db.commit()
            await self.db.refresh(db_user)

            logger.info("✅ Trial user created and added to all inbounds")

            try:
                inbound = await self.xui_client.get_inbound_by_id(self.inbound_id)
                existing_client = await self.xui_client.get_client_from_inbound(self.inbound_id, username)
                if inbound and existing_client:
                    vless_url = self.xui_client.generate_vless_url(inbound, existing_client)
            except Exception as vless_err:
                logger.warning(f"Could not generate vless_url: {vless_err}", exc_info=True)

        except Exception as e:
            logger.error(f"Error working with XUI: {str(e)}", exc_info=True)
            db_user.is_active = False
            await self.db.commit()
            await self.db.refresh(db_user)
            raise

        return db_user, vless_url, subscription_url
    
    async def create_new_user_with_duration(
        self, telegram_id: int, base_username: str, duration_months: int, bonus_days: int = 0
    ) -> Tuple[User, str, str]:
        await self._ensure_inbound()
        username = await self._build_username(telegram_id, base_username)
        user_uuid = str(uuid.uuid4())
        expire_at = datetime.now() + timedelta(days=30 * duration_months + bonus_days)
        expire_timestamp = int(expire_at.timestamp() * 1000)

        logger.info(f"Creating new user for telegram_id {telegram_id}: {username} for {duration_months} months + {bonus_days} days")

        server = await self.get_best_server()

        db_user = User(
            telegram_id=telegram_id,
            username=username,
            vpn_email=username,
            uuid=user_uuid,
            expire_at=expire_at,
            traffic_limit_gb=0,
            device_limit=3,
            is_active=True,
            protocol=self.DEFAULT_PROTOCOL,
            server_id=server.id if server else None
        )

        self.db.add(db_user)
        await self.db.commit()
        await self.db.refresh(db_user)

        vless_url = ""
        subscription_url = ""
        try:
            subscription_url = await self.xui_client.add_client_to_all_inbounds(
                email=username,
                uuid=user_uuid,
                expire_timestamp=expire_timestamp,
                device_limit=3,
                enable=True
            )

            db_user.subscription_url = subscription_url
            await self.db.commit()
            await self.db.refresh(db_user)

            logger.info("✅ User created and added to all inbounds")

            try:
                inbound = await self.xui_client.get_inbound_by_id(self.inbound_id)
                existing_client = await self.xui_client.get_client_from_inbound(self.inbound_id, username)
                if inbound and existing_client:
                    vless_url = self.xui_client.generate_vless_url(inbound, existing_client)
            except Exception as vless_err:
                logger.warning(f"Could not generate vless_url: {vless_err}", exc_info=True)

        except Exception as e:
            logger.error(f"Error working with XUI: {str(e)}", exc_info=True)
            db_user.is_active = False
            await self.db.commit()
            await self.db.refresh(db_user)
            raise

        return db_user, vless_url, subscription_url
    
    async def extend_subscription(self, user: User, duration_months: int, bonus_days: int = 0) -> User:
        await self._ensure_inbound()
        now = datetime.now()
        if user.expire_at < now:
            new_expire_at = now + timedelta(days=30 * duration_months + bonus_days)
        else:
            new_expire_at = user.expire_at + timedelta(days=30 * duration_months + bonus_days)
        
        new_expire_timestamp = int(new_expire_at.timestamp() * 1000)
        
        logger.info(f"Extending subscription for user {user.username} for {duration_months} months + {bonus_days} days, new expire: {new_expire_at}")
        
        user.expire_at = new_expire_at
        user.reminder_7d_sent = False
        user.reminder_3d_sent = False
        user.reminder_1d_sent = False
        user.reminder_expired_sent = False
        user.reminder_post_expired_3d_sent = False
        
        try:
            await self.xui_client.update_client_expire(
                email=user.vpn_email,
                expire_timestamp=new_expire_timestamp
            )
            logger.info("✅ Client expire updated in XUI")
        except Exception as e:
            logger.error(f"Error updating client in XUI: {str(e)}", exc_info=True)
            raise
        
        await self.db.commit()
        await self.db.refresh(user)
        
        return user

    async def _build_username(self, telegram_id: int, base_username: str) -> str:
        clean_username = "".join(c for c in base_username if c.isalnum() or c in ('_', '-')).lower()
        if not clean_username:
            clean_username = f"user_{telegram_id}"
        
        prefix = f"{clean_username}_"
        stmt = select(User.username).where(
            User.telegram_id == telegram_id,
            User.username.startswith(prefix)
        )
        result = await self.db.execute(stmt)
        existing_usernames = [row[0] for row in result.all() if row[0]]

        next_index = 1
        for username in existing_usernames:
            suffix = username.removeprefix(prefix)
            if suffix.isdigit():
                next_index = max(next_index, int(suffix) + 1)

        return f"{prefix}{next_index}"

    async def get_or_create_user_for_telegram(self, telegram_id: int, base_username: str) -> Tuple[User, str, str]:
        await self._ensure_inbound()
        stmt = select(User).where(User.telegram_id == telegram_id).order_by(User.created_at.desc())
        result = await self.db.execute(stmt)
        existing_user = result.scalars().first()
        
        if existing_user and existing_user.subscription_url:
            logger.info(f"Found existing user for telegram_id {telegram_id}: {existing_user.username}")
            return existing_user, "", existing_user.subscription_url
        
        username = await self._build_username(telegram_id, base_username)
        user_uuid = str(uuid.uuid4())
        expire_at = datetime.now() + timedelta(days=30 * self.DEFAULT_MONTHS)
        expire_timestamp = int(expire_at.timestamp() * 1000)

        logger.info(f"Creating new user for telegram_id {telegram_id}: {username}")

        db_user = User(
            telegram_id=telegram_id,
            username=username,
            vpn_email=username,
            uuid=user_uuid,
            expire_at=expire_at,
            traffic_limit_gb=2000,
            device_limit=self.DEFAULT_DEVICE_LIMIT,
            is_active=True,
            protocol=self.DEFAULT_PROTOCOL
        )

        self.db.add(db_user)
        await self.db.commit()
        await self.db.refresh(db_user)

        vless_url = ""
        subscription_url = ""
        try:
            subscription_url = await self.xui_client.add_client_to_all_inbounds(
                email=username,
                uuid=user_uuid,
                expire_timestamp=expire_timestamp,
                device_limit=self.DEFAULT_DEVICE_LIMIT,
                enable=True
            )

            db_user.subscription_url = subscription_url
            await self.db.commit()
            await self.db.refresh(db_user)

            logger.info("✅ User created and added to all inbounds")

            try:
                inbound = await self.xui_client.get_inbound_by_id(self.inbound_id)
                existing_client = await self.xui_client.get_client_from_inbound(self.inbound_id, username)
                if inbound and existing_client:
                    vless_url = self.xui_client.generate_vless_url(inbound, existing_client)
            except Exception as vless_err:
                logger.warning(f"Could not generate vless_url: {vless_err}", exc_info=True)

        except Exception as e:
            logger.error(f"Error working with XUI: {str(e)}", exc_info=True)
            db_user.is_active = False
            await self.db.commit()
            await self.db.refresh(db_user)
            raise

        return db_user, vless_url, subscription_url
    
    async def check_and_update_vip_status(self, user: User) -> bool:
        stmt = select(Referral).where(Referral.referrer_id == user.id)
        result = await self.db.execute(stmt)
        referrals = result.scalars().all()
        
        active_paying = 0
        now = datetime.now()
        for ref in referrals:
            ref_stmt = select(User).where(
                User.id == ref.referred_id,
                User.is_active == True,
                User.expire_at > now,
                User.is_trial == False
            )
            ref_result = await self.db.execute(ref_stmt)
            ref_user = ref_result.scalars().first()
            if ref_user:
                active_paying += 1
        
        was_vip = user.is_vip
        user.is_vip = active_paying >= 3
        
        if was_vip != user.is_vip:
            await self.db.commit()
            await self.db.refresh(user)
        
        return user.is_vip
