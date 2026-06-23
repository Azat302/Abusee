from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class UserBase(BaseModel):
    username: str


class UserCreate(UserBase):
    months: int
    traffic_limit_gb: int


class VPNCreateRequest(BaseModel):
    username: str
    months: int
    traffic_limit_gb: int
    device_limit: int = 1


class VPNCreateResponse(BaseModel):
    user_id: int
    uuid: str
    expire_at: datetime
    subscription_url: Optional[str] = None


class UserResponse(UserBase):
    id: int
    telegram_id: Optional[int] = None
    vpn_email: Optional[str] = None
    uuid: str
    expire_at: datetime
    traffic_limit_gb: int
    xui_client_id: Optional[int] = None
    subscription_url: Optional[str] = None
    is_active: bool
    protocol: Optional[str] = None
    device_limit: int
    created_at: datetime

    class Config:
        from_attributes = True


class StatusResponse(BaseModel):
    status: str
    message: str
