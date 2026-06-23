from sqlalchemy import Column, Integer, String, DateTime, Boolean, Float, ForeignKey, Text, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database.database import Base
import enum


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(Integer, index=True, nullable=True)
    username = Column(String, index=True)
    vpn_email = Column(String, unique=True, index=True, nullable=True)
    uuid = Column(String, unique=True, index=True)
    expire_at = Column(DateTime)
    traffic_limit_gb = Column(Integer)
    xui_client_id = Column(Integer, nullable=True)
    subscription_url = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    protocol = Column(String, nullable=True, default="vless")
    device_limit = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    reminder_7d_sent = Column(Boolean, default=False)
    reminder_3d_sent = Column(Boolean, default=False)
    reminder_1d_sent = Column(Boolean, default=False)
    reminder_expired_sent = Column(Boolean, default=False)
    reminder_post_expired_3d_sent = Column(Boolean, default=False)
    is_trial = Column(Boolean, default=False)
    trial_used = Column(Boolean, default=False)
    is_vip = Column(Boolean, default=False)
    referrer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    server_id = Column(Integer, ForeignKey("servers.id"), nullable=True)

    payments = relationship("Payment", back_populates="user")
    referrals = relationship("Referral", foreign_keys="Referral.referrer_id", back_populates="referrer")
    referred_by = relationship("Referral", foreign_keys="Referral.referred_id", back_populates="referred", uselist=False)
    server = relationship("Server", back_populates="users")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    payment_id = Column(String, unique=True, index=True)
    status = Column(String, index=True)
    amount = Column(Float)
    currency = Column(String, default="RUB")
    description = Column(String)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    telegram_id = Column(Integer, index=True)
    processed = Column(Boolean, default=False)
    promo_code_id = Column(Integer, ForeignKey("promo_codes.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="payments")
    promo_code = relationship("PromoCode", back_populates="payments")


class Referral(Base):
    __tablename__ = "referrals"

    id = Column(Integer, primary_key=True, index=True)
    referrer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    referred_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    trial_activated = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    referrer = relationship("User", foreign_keys=[referrer_id], back_populates="referrals")
    referred = relationship("User", foreign_keys=[referred_id], back_populates="referred_by")


class PromoCodeType(str, enum.Enum):
    PERCENT = "percent"
    FIXED = "fixed"
    BONUS_DAYS = "bonus_days"


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True, nullable=False)
    type = Column(SQLEnum(PromoCodeType), nullable=False)
    value = Column(Integer, nullable=False)
    max_uses = Column(Integer, nullable=True)
    current_uses = Column(Integer, default=0)
    expire_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    payments = relationship("Payment", back_populates="promo_code")
    activations = relationship("PromoActivation", back_populates="promo_code")


class PromoActivation(Base):
    __tablename__ = "promo_activations"

    id = Column(Integer, primary_key=True, index=True)
    promo_code_id = Column(Integer, ForeignKey("promo_codes.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    promo_code = relationship("PromoCode", back_populates="activations")


class Server(Base):
    __tablename__ = "servers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    country = Column(String, nullable=False)
    ip = Column(String, nullable=False)
    xui_url = Column(String, nullable=False)
    xui_username = Column(String, nullable=False)
    xui_password = Column(String, nullable=False)
    max_users = Column(Integer, default=100)
    current_users = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    cpu_usage = Column(Float, nullable=True)
    ram_usage = Column(Float, nullable=True)
    disk_usage = Column(Float, nullable=True)
    last_monitored_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    users = relationship("User", back_populates="server")


class BroadcastCategory(str, enum.Enum):
    ALL = "all"
    PAYING = "paying"
    TRIAL = "trial"
    EXPIRED = "expired"
    VIP = "vip"


class Broadcast(Base):
    __tablename__ = "broadcasts"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(SQLEnum(BroadcastCategory), nullable=False)
    text = Column(Text, nullable=False)
    photo_url = Column(String, nullable=True)
    button_text = Column(String, nullable=True)
    button_url = Column(String, nullable=True)
    sent_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class NotificationType(str, enum.Enum):
    TRIAL_START = "trial_start"
    TRIAL_ENDING = "trial_ending"
    TRIAL_ENDED = "trial_ended"
    SUBSCRIPTION_ENDING = "subscription_ending"
    SUBSCRIPTION_ENDED = "subscription_ended"


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    type = Column(SQLEnum(NotificationType), nullable=False)
    sent_at = Column(DateTime(timezone=True), server_default=func.now())


class SupportTicketCategory(str, enum.Enum):
    VPN_NOT_WORKING = "vpn_not_working"
    YOUTUBE_NOT_WORKING = "youtube_not_working"
    LOW_SPEED = "low_speed"
    PAYMENT_ERROR = "payment_error"
    OTHER = "other"


class SupportTicketStatus(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    category = Column(SQLEnum(SupportTicketCategory), nullable=False)
    message = Column(Text, nullable=False)
    status = Column(SQLEnum(SupportTicketStatus), default=SupportTicketStatus.OPEN)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User")
