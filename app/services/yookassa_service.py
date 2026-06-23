import os
import uuid
import httpx
import logging
from dotenv import load_dotenv
from typing import Optional, Dict

load_dotenv()

logger = logging.getLogger(__name__)

YOOKASSA_SHOP_ID = os.getenv("YOO_SHOP_ID")
YOOKASSA_SECRET_KEY = os.getenv("YOO_SECRET_KEY")
BASE_URL = "https://api.yookassa.ru/v3"


class AsyncYooKassaService:
    @staticmethod
    def _get_auth_headers():
        import base64
        credentials = f"{YOOKASSA_SHOP_ID}:{YOOKASSA_SECRET_KEY}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/json",
            "Idempotence-Key": ""
        }
    
    @staticmethod
    async def create_payment(
        amount: float,
        description: str,
        return_url: str,
        metadata: Optional[Dict] = None
    ) -> Dict:
        idempotence_key = str(uuid.uuid4())
        payload = {
            "amount": {
                "value": f"{amount:.2f}",
                "currency": "RUB"
            },
            "confirmation": {
                "type": "redirect",
                "return_url": return_url
            },
            "capture": True,
            "description": description,
            "metadata": metadata or {}
        }
        
        headers = AsyncYooKassaService._get_auth_headers()
        headers["Idempotence-Key"] = idempotence_key
        
        logger.info(f"Creating payment of {amount} RUB with idempotence key {idempotence_key}")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{BASE_URL}/payments",
                json=payload,
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"Payment created successfully, id: {result.get('id')}")
            return result
    
    @staticmethod
    async def get_payment(payment_id: str) -> Dict:
        headers = AsyncYooKassaService._get_auth_headers()
        del headers["Idempotence-Key"]
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE_URL}/payments/{payment_id}",
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            return response.json()
    
    @staticmethod
    async def cancel_payment(payment_id: str) -> Dict:
        idempotence_key = str(uuid.uuid4())
        headers = AsyncYooKassaService._get_auth_headers()
        headers["Idempotence-Key"] = idempotence_key
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{BASE_URL}/payments/{payment_id}/cancel",
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            return response.json()
