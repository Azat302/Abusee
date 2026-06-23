import os
import json
import re
import httpx
import logging
from dotenv import load_dotenv
from typing import Dict, Optional, List

# Загружаем переменные окружения ТОЛЬКО ДЛЯ ЧТЕНИЯ
load_dotenv()

logger = logging.getLogger(__name__)


class AsyncXUIClient:
    DEFAULT_DEVICE_LIMIT = 3

    def __init__(self):
        # Читаем переменные ТОЛЬКО ВО ВРЕМЯ ИНИЦИАЛИЗАЦИИ, не меняем их
        self.base_url = os.getenv("XUI_URL", "http://localhost:2053").rstrip("/")
        import urllib.parse
        parsed = urllib.parse.urlparse(self.base_url)
        # Создаем subscription URL с портом 8443
        self.subscription_base_url = f"{parsed.scheme}://{parsed.hostname}:8443"
        self.username = os.getenv("XUI_USERNAME", "admin")
        self.password = os.getenv("XUI_PASSWORD", "admin")
        
        # Асинхронная сессия
        self.client: Optional[httpx.AsyncClient] = None
        self.logged_in = False
        self.csrf_token = None
        
        logger.debug(f"AsyncXUIClient initialized with base_url: {self.base_url}")
        logger.debug(f"Username: {self.username}")
    
    async def _ensure_client(self):
        if self.client is None or self.client.is_closed:
            self.client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
    
    async def __aenter__(self):
        await self._ensure_client()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client and not self.client.is_closed:
            await self.client.aclose()
    
    def _log_request(self, method: str, url: str, data: Optional[Dict] = None):
        logger.debug(f"=== {method} {url} ===")
        if self.client:
            logger.debug(f"Client cookies: {dict(self.client.cookies)}")
        if data:
            logger.debug(f"Request data: {json.dumps(data, indent=2, ensure_ascii=False)}")
    
    def _log_response(self, response: httpx.Response):
        logger.debug(f"Response status code: {response.status_code}")
        logger.debug(f"Response headers: {dict(response.headers)}")
        if self.client:
            logger.debug(f"Response cookies: {dict(self.client.cookies)}")
        try:
            logger.debug(f"Response body: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
        except:
            logger.debug(f"Response body: {response.text}")
    
    def _normalize_json_field(self, value, default):
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                logger.warning("Failed to decode inbound JSON field, using default value")
                return default.copy() if isinstance(default, dict) else default
        if isinstance(value, dict):
            return value
        return default.copy() if isinstance(default, dict) else default
    
    async def login(self) -> bool:
        await self._ensure_client()
        logger.info("=== Attempting to login to XUI (async) ===")
        try:
            logger.debug("First GET to base URL to get cookies and CSRF token...")
            get_url = self.base_url
            self._log_request("GET", get_url)
            get_resp = await self.client.get(get_url)
            self._log_response(get_resp)
            
            self.csrf_token = None
            csrf_match = re.search(r'<meta name="csrf-token" content="([^"]+)">', get_resp.text)
            if csrf_match:
                self.csrf_token = csrf_match.group(1)
                logger.debug(f"Extracted CSRF token: {self.csrf_token}")
            else:
                logger.warning("No CSRF token found in HTML")
            
            url = f"{self.base_url}/login"
            data = {
                "username": self.username,
                "password": self.password
            }
            
            headers = {}
            if self.csrf_token:
                headers["X-CSRF-Token"] = self.csrf_token
            
            self._log_request("POST", url, data)
            response = await self.client.post(url, data=data, headers=headers)
            self._log_response(response)
            
            if response.is_success:
                result = response.json()
                if result.get("success", False):
                    self.logged_in = True
                    logger.info("✅ Successfully logged in to XUI")
                    return True
                else:
                    logger.error(f"❌ Login failed - API returned success=False: {response.text}")
            else:
                logger.error(f"❌ Login failed - status code: {response.status_code}")
        except Exception as e:
            logger.error(f"❌ Login exception: {str(e)}", exc_info=True)
        return False
    
    async def get_inbounds(self) -> List[Dict]:
        await self._ensure_client()
        logger.info("=== Fetching inbounds (async) ===")
        if not self.logged_in:
            logger.info("Not logged in, trying to login first")
            if not await self.login():
                logger.error("Failed to login before fetching inbounds")
                return []
        
        try:
            url = f"{self.base_url}/panel/api/inbounds/list"
            self._log_request("GET", url)
            response = await self.client.get(url)
            self._log_response(response)
            
            if response.is_success:
                result = response.json()
                if result.get("success", False):
                    inbounds = result.get("obj", [])
                    logger.info(f"✅ Found {len(inbounds)} inbounds")
                    return inbounds
                else:
                    logger.error(f"❌ Get inbounds failed - API returned success=False")
        except Exception as e:
            logger.error(f"❌ Get inbounds exception: {str(e)}", exc_info=True)
        return []
    
    async def create_client(
        self,
        inbound_id: int,
        email: str,
        uuid: str,
        total_traffic_bytes: int,
        expire_timestamp: int,
        device_limit: int = DEFAULT_DEVICE_LIMIT,
        enable: bool = True,
        sub_id: Optional[str] = None
    ) -> Optional[Dict]:
        await self._ensure_client()
        logger.info(f"=== Creating client {email} for inbound {inbound_id} (async) ===")
        
        if not self.logged_in:
            logger.info("Not logged in, trying to login first")
            if not await self.login():
                raise Exception("Failed to login to XUI")
        
        try:
            inbounds = await self.get_inbounds()
            target_inbound = None
            for inbound in inbounds:
                if inbound.get("id") == inbound_id:
                    target_inbound = inbound
                    break
            
            if not target_inbound:
                raise Exception(f"Could not find inbound {inbound_id}")
            
            import secrets
            if not sub_id:
                sub_id = secrets.token_urlsafe(16).replace("_", "").replace("-", "")
            password = secrets.token_urlsafe(12).replace("_", "").replace("-", "")
            
            limit_ip = max(1, int(device_limit))
            new_client = {
                "id": uuid,
                "email": email,
                "enable": enable,
                "flow": "xtls-rprx-vision",
                "limitIp": limit_ip,
                "totalGB": 0,
                "expiryTime": expire_timestamp,
                "tgId": "",
                "subId": sub_id,
                "password": password,
                "security": "auto",
                "reset": 0
            }
            
            existing_settings = self._normalize_json_field(target_inbound.get("settings", {}), {})
            existing_clients = existing_settings.get("clients", [])
            existing_clients.append(new_client)
            existing_settings["clients"] = existing_clients
            stream_settings = self._normalize_json_field(target_inbound.get("streamSettings", {}), {})
            sniffing_settings = self._normalize_json_field(target_inbound.get("sniffing", {}), {})
            
            data = {
                "id": inbound_id,
                "remark": target_inbound.get("remark", ""),
                "enable": target_inbound.get("enable", True),
                "listen": target_inbound.get("listen", ""),
                "port": target_inbound.get("port", 0),
                "protocol": target_inbound.get("protocol", "vless"),
                "expiryTime": target_inbound.get("expiryTime", 0),
                "settings": json.dumps(existing_settings),
                "streamSettings": json.dumps(stream_settings),
                "sniffing": json.dumps(sniffing_settings),
            }
            
            url = f"{self.base_url}/panel/api/inbounds/update/{inbound_id}"
            self._log_request("POST", url, data)
            
            headers = {}
            if self.csrf_token:
                headers["X-CSRF-Token"] = self.csrf_token
            
            response = await self.client.post(url, data=data, headers=headers)
            self._log_response(response)
            
            if not response.is_success:
                raise Exception(f"Update failed with status {response.status_code}: {response.text}")
            
            result = response.json()
            if not result.get("success", False):
                raise Exception(f"API returned success=False: {response.text}")
            
            logger.info(f"✅ Client {email} added to inbound {inbound_id} successfully!")
            return {
                "client_id": inbound_id,
                "uuid": uuid,
                "email": email,
                "subId": sub_id,
                "success": True,
                "raw_response": result
            }
        except Exception as e:
            logger.error(f"❌ Create client failed: {str(e)}", exc_info=True)
            raise
    
    async def get_client(self, inbound_id: int, email: str) -> Optional[Dict]:
        await self._ensure_client()
        if not self.logged_in:
            if not await self.login():
                return None
        try:
            url = f"{self.base_url}/panel/api/inbounds/getClientTraffics/{email}"
            response = await self.client.get(url)
            
            if response.is_success:
                result = response.json()
                if result.get("success", False):
                    client = result.get("obj")
                    if isinstance(client, dict):
                        return client
        except Exception as e:
            logger.error(f"Error fetching client: {str(e)}")
        
        inbounds = await self.get_inbounds()
        for inbound in inbounds:
            if inbound_id and inbound.get("id") != inbound_id:
                continue
            for client_stat in inbound.get("clientStats", []):
                if client_stat.get("email") == email:
                    return client_stat
        return None
    
    async def update_client(
        self,
        inbound_id: int,
        email: str,
        uuid: str,
        total_traffic_bytes: int,
        expire_timestamp: int,
        device_limit: int = DEFAULT_DEVICE_LIMIT,
        enable: bool = True
    ) -> Optional[Dict]:
        await self._ensure_client()
        if not self.logged_in:
            if not await self.login():
                return None
        try:
            url = f"{self.base_url}/panel/api/inbounds/updateClient/{uuid}"
            logger.info(f"Updating client {email} (async)")
            
            client = {
                "id": uuid,
                "email": email,
                "enable": enable,
                "flow": "xtls-rprx-vision",
                "limitIp": max(1, int(device_limit)),
                "totalGB": total_traffic_bytes / (1024 ** 3),
                "expiryTime": expire_timestamp,
                "tgId": "",
                "subId": ""
            }
            
            settings = {"clients": [client]}
            data = {
                "id": inbound_id,
                "settings": json.dumps(settings)
            }
            
            response = await self.client.post(url, json=data)
            self._log_response(response)
            
            if response.is_success:
                result = response.json()
                if result.get("success", False):
                    logger.info(f"Client {email} updated successfully")
                    return {"success": True}
        except Exception as e:
            logger.error(f"Error updating client: {str(e)}")
        return None
    
    async def delete_client(self, inbound_id: int, email: str) -> bool:
        await self._ensure_client()
        if not self.logged_in:
            if not await self.login():
                return False
        try:
            url = f"{self.base_url}/panel/api/inbounds/delClient/{inbound_id}"
            data = {"email": email}
            logger.info(f"Deleting client {email} from inbound {inbound_id} (async)")
            
            response = await self.client.post(url, json=data)
            self._log_response(response)
            
            if response.is_success:
                result = response.json()
                if result.get("success", False):
                    logger.info(f"Client {email} deleted successfully")
                    return True
        except Exception as e:
            logger.error(f"Error deleting client: {str(e)}")
        return False
    
    async def find_vless_inbound(self) -> Optional[int]:
        logger.info("Looking for VLESS inbound (async)...")
        inbounds = await self.get_inbounds()
        logger.debug(f"All inbounds: {json.dumps(inbounds, indent=2, ensure_ascii=False)}")
        
        for inbound in inbounds:
            if inbound.get("protocol") == "vless":
                logger.info(f"✅ Found VLESS inbound with id: {inbound['id']}")
                return inbound.get("id")
        
        logger.warning("❌ No VLESS inbound found!")
        return None
    
    async def get_client_from_inbound(self, inbound_id: int, email: str) -> Optional[Dict]:
        logger.info(f"Checking for existing client with email {email} in inbound {inbound_id} (async)")
        inbounds = await self.get_inbounds()
        for inbound in inbounds:
            if inbound.get("id") == inbound_id:
                settings = inbound.get("settings", {})
                if isinstance(settings, str):
                    try:
                        settings = json.loads(settings)
                    except:
                        return None
                clients = settings.get("clients", [])
                for client in clients:
                    if client.get("email") == email:
                        logger.info(f"✅ Found existing client: {email}")
                        return client
        logger.info(f"Client {email} not found in inbound {inbound_id}")
        return None
    
    async def get_inbound_by_id(self, inbound_id: int) -> Optional[Dict]:
        await self._ensure_client()
        if not self.logged_in:
            if not await self.login():
                return None
        url = f"{self.base_url}/panel/api/inbounds/get/{inbound_id}"
        try:
            response = await self.client.get(url)
            if response.is_success:
                result = response.json()
                if result.get("success"):
                    return result.get("obj")
        except Exception as e:
            logger.error(f"Error getting inbound {inbound_id}: {e}")
        return None
    
    def generate_vless_url(self, inbound: Dict, client: Dict) -> str:
        uuid_val = client.get("id")
        port = inbound.get("port")
        stream_settings = self._normalize_json_field(inbound.get("streamSettings", {}), {})
        reality_settings = stream_settings.get("realitySettings", {})
        server_name = reality_settings.get("serverNames", [None])[0]
        public_key = reality_settings.get("settings", {}).get("publicKey")
        fingerprint = reality_settings.get("settings", {}).get("fingerprint")
        short_id = reality_settings.get("shortIds", [""])[0]
        spider_x = reality_settings.get("settings", {}).get("spiderX", "/")
        
        import urllib.parse
        parsed_url = urllib.parse.urlparse(self.base_url)
        host = parsed_url.netloc.split(':')[0]
        
        params = {
            "type": stream_settings.get("network", "tcp"),
            "security": "reality",
            "pbk": public_key,
            "fp": fingerprint,
            "sni": server_name if server_name else "www.amd.com",
            "sid": short_id,
            "spx": spider_x,
            "flow": client.get("flow", "xtls-rprx-vision")
        }
        param_str = "&".join([f"{k}={v}" for k, v in params.items() if v])
        vless_url = f"vless://{uuid_val}@{host}:{port}?{param_str}#{inbound.get('remark', 'VPN')}"
        return vless_url
    
    async def add_client_to_all_inbounds(
        self,
        email: str,
        uuid: str,
        expire_timestamp: int,
        device_limit: int = DEFAULT_DEVICE_LIMIT,
        enable: bool = True
    ) -> Optional[str]:
        inbounds = await self.get_inbounds()
        logger.info(f"Добавляем клиента {email} в {len(inbounds)} инбаундов (async)")
        
        real_sub_id = None
        for inbound in inbounds:
            existing_client = await self.get_client_from_inbound(inbound.get("id"), email)
            if existing_client and existing_client.get("subId"):
                real_sub_id = existing_client.get("subId")
                logger.info(f"Найден существующий subId: {real_sub_id}")
                break
        
        if not real_sub_id:
            import secrets
            real_sub_id = secrets.token_urlsafe(16).replace("_", "").replace("-", "")
            logger.info(f"Сгенерирован новый subId: {real_sub_id}")
        
        for inbound in inbounds:
            inbound_id = inbound.get("id")
            existing_client = await self.get_client_from_inbound(inbound_id, email)
            if existing_client:
                logger.info(f"Клиент {email} уже существует в инбаунде {inbound_id}")
                continue
            
            try:
                await self.create_client(
                    inbound_id=inbound_id,
                    email=email,
                    uuid=uuid,
                    total_traffic_bytes=0,
                    expire_timestamp=expire_timestamp,
                    device_limit=device_limit,
                    enable=enable,
                    sub_id=real_sub_id
                )
                logger.info(f"Клиент {email} добавлен в инбаунд {inbound_id} с subId {real_sub_id}")
            except Exception as e:
                logger.error(f"Ошибка добавления клиента в инбаунд {inbound_id}: {e}")
                continue
        
        subscription_url = f"{self.subscription_base_url}/sub/{real_sub_id}"
        return subscription_url
    
    async def get_client_stats(self, email: str) -> Optional[Dict]:
        if not self.logged_in:
            if not await self.login():
                return None
        
        inbounds = await self.get_inbounds()
        total_up = 0
        total_down = 0
        clients = []
        
        for inbound in inbounds:
            client = await self.get_client_from_inbound(inbound.get("id"), email)
            if client:
                clients.append(client)
                for stat in inbound.get("clientStats", []):
                    if stat.get("email") == email:
                        total_up += stat.get("up", 0)
                        total_down += stat.get("down", 0)
        
        if clients:
            return {
                "email": email,
                "clients": clients,
                "total_up": total_up,
                "total_down": total_down,
                "device_limit": clients[0].get("limitIp", 1) if clients else 1,
                "enable": clients[0].get("enable", True) if clients else True
            }
        return None
    
    async def update_client_expire(self, email: str, expire_timestamp: int) -> bool:
        logger.info(f"Updating expire for client {email} to {expire_timestamp} (async)")
        
        if not self.logged_in:
            if not await self.login():
                return False
        
        inbounds = await self.get_inbounds()
        success = True
        
        for inbound in inbounds:
            inbound_id = inbound.get("id")
            if not inbound_id:
                continue
            
            client = await self.get_client_from_inbound(inbound_id, email)
            if not client:
                continue
            
            try:
                await self.update_client(
                    inbound_id=inbound_id,
                    email=email,
                    uuid=client.get("id"),
                    total_traffic_bytes=0,
                    expire_timestamp=expire_timestamp,
                    device_limit=client.get("limitIp", 1),
                    enable=client.get("enable", True)
                )
                logger.info(f"Updated client {email} in inbound {inbound_id}")
            except Exception as e:
                logger.error(f"Failed to update client {email} in inbound {inbound_id}: {e}")
                success = False
        
        return success
