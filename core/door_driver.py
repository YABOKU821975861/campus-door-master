"""
门禁动作驱动模块
支持开锁 (open) 和落锁 (keep_close) 两个动作，统一 401 自动重试
"""

import json
import logging
import time
from dataclasses import dataclass
from typing import List, Optional

import requests
import urllib3

from config import (
    BASE_URL,
    OPEN_DOOR_ENDPOINT,
    CLOSE_DOOR_ENDPOINT,
    CLIENT_TYPE,
    PLATFORM,
    OPEN_DOOR_TIMEOUT_SECONDS,
    ADO_VERIFY_SSL,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


class DoorError(Exception):
    """门禁操作异常基类"""
    pass


class DoorUnauthorizedError(DoorError):
    """Token 失效/未授权 (401)"""
    pass


class DoorRequestError(DoorError):
    """请求失败（网络、参数错误等）"""
    pass


class DoorResponseError(DoorError):
    """业务层面失败"""
    pass


@dataclass
class DoorActionResult:
    """门禁操作结果（开锁/落锁通用）"""
    success: bool
    action: str           # "open" 或 "close"
    message: str
    detail: dict
    lock_ids: List[str]
    response_time_ms: float


class DoorDriver:
    """
    门禁动作驱动器

    支持：
    1. 开锁 (open)  → POST /api/remote/openDoors/open
    2. 落锁 (keep_close) → POST /api/remote/openDoors/keep_close

    统一能力：
    - 自动获取并注入有效 Token
    - 401 / 空响应自动清缓存重试（最多 1 次）
    - 统一返回 DoorActionResult
    """

    def __init__(self, token_manager):
        self.token_manager = token_manager
        self.open_url = f"{BASE_URL.rstrip('/')}{OPEN_DOOR_ENDPOINT}"
        self.close_url = f"{BASE_URL.rstrip('/')}{CLOSE_DOOR_ENDPOINT}"

        self._session = requests.Session()
        self._session.verify = ADO_VERIFY_SSL
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Origin": BASE_URL,
            "X-Platform": PLATFORM,
            "x-client-type": CLIENT_TYPE,
            "Content-Type": "application/json",
        })

        logger.info(f"DoorDriver 初始化完成 | 开锁: {self.open_url} | 落锁: {self.close_url}")

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _build_headers(self, token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "x-client-type": CLIENT_TYPE,
            "X-Platform": PLATFORM,
            "Content-Type": "application/json",
        }

    def _build_payload(self, lock_ids: List[str]) -> dict:
        """目标接口要求 lock_ids 值为 JSON 数组字符串"""
        return {"lock_ids": json.dumps(lock_ids, ensure_ascii=False)}

    def _execute_action(
        self,
        url: str,
        action: str,
        lock_ids: List[str],
        reason: str,
    ) -> DoorActionResult:
        """
        执行门禁动作的核心方法（开锁/落锁共用）

        Args:
            url: 目标 API 完整 URL
            action: 动作标识 "open" / "close"
            lock_ids: 门锁 UUID 列表
            reason: 操作原因

        Returns:
            DoorActionResult

        Raises:
            DoorError: 操作失败
        """
        action_label = "开锁" if action == "open" else "落锁"
        start_time = time.time()
        last_error = None

        for attempt in range(1, 3):
            try:
                token = self.token_manager.get_token()
                headers = self._build_headers(token)
                payload = self._build_payload(lock_ids)

                logger.info(
                    f"执行{action_label} (尝试 {attempt}/2): "
                    f"lock_ids={lock_ids}, reason={reason}"
                )

                response = self._session.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=OPEN_DOOR_TIMEOUT_SECONDS,
                )

                response_time_ms = (time.time() - start_time) * 1000

                # --- 401 处理 ---
                if response.status_code == 401:
                    logger.warning(f"收到 401，Token 可能已失效")
                    if attempt == 1:
                        self.token_manager.invalidate()
                        continue
                    raise DoorUnauthorizedError("Token 刷新后仍收到 401")

                # --- 非 200 ---
                if response.status_code != 200:
                    raise DoorRequestError(
                        f"HTTP {response.status_code}: {response.text[:500]}"
                    )

                # --- 解析响应 ---
                try:
                    res_data = response.json()
                except Exception:
                    res_data = None

                # 空响应体 → 可能 Token 无效
                if res_data is None or (
                    isinstance(res_data, dict) and res_data.get("raw") == ""
                ):
                    logger.warning("收到空响应体，可能 Token 无效")
                    if attempt == 1:
                        self.token_manager.invalidate()
                        continue
                    raise DoorRequestError(f"{action_label}失败：服务器返回空响应")

                # --- 业务成功判定（目标接口 code=0 为成功） ---
                code = res_data.get("code")
                is_success = (
                    code == 0
                    or code == 200
                    or res_data.get("success") is True
                )

                message = res_data.get("message") or res_data.get("msg") or "未知响应"

                result = DoorActionResult(
                    success=is_success,
                    action=action,
                    message=message,
                    detail=res_data,
                    lock_ids=lock_ids,
                    response_time_ms=response_time_ms,
                )

                if is_success:
                    logger.info(f"{action_label}成功: {message}, 耗时 {response_time_ms:.0f}ms")
                else:
                    logger.warning(f"{action_label}失败: {message}, 响应: {res_data}")
                    raise DoorResponseError(message)

                return result

            except (DoorUnauthorizedError, DoorResponseError):
                raise
            except requests.Timeout:
                last_error = DoorRequestError(f"请求超时 ({OPEN_DOOR_TIMEOUT_SECONDS}s)")
                logger.warning(f"{action_label}超时 (尝试 {attempt}/2)")
            except requests.RequestException as e:
                last_error = DoorRequestError(f"网络请求异常: {e}")
                logger.warning(f"{action_label}网络异常 (尝试 {attempt}/2): {e}")
            except Exception as e:
                last_error = DoorRequestError(f"未知错误: {e}")
                logger.exception(f"{action_label}异常 (尝试 {attempt}/2)")

            if attempt < 2:
                time.sleep(0.5)

        raise last_error or DoorRequestError(f"{action_label}失败：达到最大重试次数")

    # ------------------------------------------------------------------
    # 公开接口 — 开锁
    # ------------------------------------------------------------------

    def open_door(
        self,
        lock_ids: Optional[List[str]] = None,
        reason: str = "API 调用开锁",
    ) -> DoorActionResult:
        """开锁操作"""
        if not lock_ids:
            raise DoorRequestError("门锁 ID 列表不能为空")
        return self._execute_action(
            url=self.open_url,
            action="open",
            lock_ids=lock_ids,
            reason=reason,
        )

    def open_door_by_room(
        self,
        room_name: str,
        reason: str = "API 调用开锁",
    ) -> DoorActionResult:
        """根据房间号开锁"""
        from rooms_config import get_lock_ids_by_room, room_exists

        if not room_exists(room_name):
            raise DoorRequestError(f"房间不存在: {room_name}")

        lock_ids = get_lock_ids_by_room(room_name)
        if not lock_ids:
            raise DoorRequestError(f"房间 {room_name} 未配置对应的门锁")

        logger.info(f"房间 {room_name} 对应 lock_ids: {lock_ids}")
        return self.open_door(lock_ids=lock_ids, reason=f"{reason} (房间: {room_name})")

    # ------------------------------------------------------------------
    # 公开接口 — 落锁
    # ------------------------------------------------------------------

    def close_door(
        self,
        lock_ids: Optional[List[str]] = None,
        reason: str = "API 调用落锁",
    ) -> DoorActionResult:
        """落锁操作"""
        if not lock_ids:
            raise DoorRequestError("门锁 ID 列表不能为空")
        return self._execute_action(
            url=self.close_url,
            action="close",
            lock_ids=lock_ids,
            reason=reason,
        )

    def close_door_by_room(
        self,
        room_name: str,
        reason: str = "API 调用落锁",
    ) -> DoorActionResult:
        """根据房间号落锁"""
        from rooms_config import get_lock_ids_by_room, room_exists

        if not room_exists(room_name):
            raise DoorRequestError(f"房间不存在: {room_name}")

        lock_ids = get_lock_ids_by_room(room_name)
        if not lock_ids:
            raise DoorRequestError(f"房间 {room_name} 未配置对应的门锁")

        logger.info(f"房间 {room_name} 对应 lock_ids: {lock_ids}")
        return self.close_door(lock_ids=lock_ids, reason=f"{reason} (房间: {room_name})")
