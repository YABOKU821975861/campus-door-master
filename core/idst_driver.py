"""IDST RF 设备控制驱动。"""

import hashlib
import json
import logging
import time
from typing import Any

import requests
import urllib3

from config import IDST_BASE_URL, IDST_RF_CONTROL_ENDPOINT, IDST_VERIFY_SSL, USER_AGENT
from core.idst_session_manager import IdstSessionManager, IdstSessionError

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)


class IdstDriverError(Exception):
    pass


class IdstDriver:
    def __init__(self, session_manager: IdstSessionManager):
        self.session_manager = session_manager
        self.url = f"{IDST_BASE_URL.rstrip('/')}{IDST_RF_CONTROL_ENDPOINT}"
        self.session = requests.Session()
        self.session.verify = IDST_VERIFY_SSL
        self.session.headers.update({"User-Agent": USER_AGENT})

    def control(self, payload: dict[str, Any]) -> dict:
        for attempt in range(2):
            try:
                credentials = self.session_manager.get_credentials(
                    force_refresh=attempt == 1
                )
                timestamp = str(int(time.time() * 1000))
                sign = hashlib.md5(
                    f"{credentials.token}{timestamp}{credentials.code}".encode()
                ).hexdigest()
                response = self.session.post(
                    self.url,
                    params={"access_token": credentials.token},
                    headers={
                        "Accept": "application/json, text/plain, */*",
                        "Content-Type": "application/json; charset=UTF-8",
                        "Origin": IDST_BASE_URL,
                        "Referer": f"{IDST_BASE_URL}/layout/device/deviceList",
                        "Sign": sign,
                        "Time": timestamp,
                        "platform": "PC",
                    },
                    data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    timeout=15,
                )
                data = response.json()
                if response.status_code in {401, 403} or data.get("status") in {401, 403}:
                    self.session_manager.invalidate()
                    if attempt == 0:
                        continue
                return data
            except (requests.RequestException, ValueError, IdstSessionError) as exc:
                if attempt == 0:
                    self.session_manager.invalidate()
                    continue
                raise IdstDriverError(f"IDST 请求失败: {exc}") from exc
        raise IdstDriverError("IDST 请求失败，重试后仍未成功")

    def control_device(self, device_id: str, rf_id: int, lock: int) -> dict:
        """按设备 ID 执行一次智能门禁控制。"""
        return self.control({
            "id": device_id,
            "ctrl": {
                "rf_id": rf_id,
                "smart_entrance_guard": {"lock": lock},
            },
        })
