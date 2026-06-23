from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
import logging

from app.database.database import get_db
from app.models.user import User
from app.models.schemas import (
    UserResponse, StatusResponse
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_model=StatusResponse)
def read_root():
    return StatusResponse(
        status="ok",
        message="VPN Service Backend is running"
    )


@router.get("/users", response_model=List[UserResponse])
def get_users(db: Session = Depends(get_db)):
    logger.info("Fetching all users")
    users = db.query(User).all()
    logger.info(f"Found {len(users)} users")
    for user in users:
        logger.info(f"  - User: id={user.id}, username={user.username}")
    return users
