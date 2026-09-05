"""IDST 会话管理：登录获取 token，并通过 WebSocket 获取动态 code。"""

import json
import logging
import os
import ssl
import threading
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import requests
import urllib3
from websocket import create_connection

from config import (
    IDST_BASE_URL,
    IDST_LOGIN_ENDPOINT,
    IDST_CAPTCHA_ENDPOINT,
    IDST_USERNAME,
    IDST_PASSWORD,
    IDST_LOGIN_TIMEOUT_SECONDS,
    IDST_WS_TIMEOUT_SECONDS,
    IDST_TOKEN_CACHE_TTL,
    IDST_TOKEN_STORAGE_PATH,
    IDST_VERIFY_SSL,
    USER_AGENT,
)
from core.captcha_ocr import CaptchaOCR, CaptchaError

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)


class IdstSessionError(Exception):
    pass


class IdstLoginError(IdstSessionError):
    pass


@dataclass
class IdstCredentials:
    token: str
    code: str
    fetched_at: float

    @property
    def is_valid(self) -> bool:
        return (time.time() - self.fetched_at) < IDST_TOKEN_CACHE_TTL


class IdstSessionManager:
    """独立于 ADO 门禁 TokenManager 的 IDST token/code 管理器。"""

    _instance: Optional["IdstSessionManager"] = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._lock = threading.RLock()
        self._credentials: Optional[IdstCredentials] = None
        self._ws = None
        self._session = requests.Session()
        self._session.verify = IDST_VERIFY_SSL
        self._session.headers.update({
            "User-Agent": USER_AGENT,
            "Origin": IDST_BASE_URL,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        self._captcha = CaptchaOCR(session=self._session)
        self._captcha.captcha_url = (
            f"{IDST_BASE_URL.rstrip('/')}{IDST_CAPTCHA_ENDPOINT}"
        )
        self._captcha.captcha_method = "POST"
        self._initialized = True
        self._load_cached_credentials()

    @property
    def login_url(self) -> str:
        return f"{IDST_BASE_URL.rstrip('/')}{IDST_LOGIN_ENDPOINT}"

    @property
    def ws_url(self) -> str:
        parsed = urlparse(IDST_BASE_URL)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        return f"{scheme}://{parsed.netloc}/wss/"

    def _extract_token(self, data: dict) -> Optional[str]:
        return (
            data.get("token")
            or data.get("access_token")
            or data.get("data", {}).get("token")
            or data.get("data", {}).get("access_token")
        )

    def _login(self) -> str:
        if not IDST_USERNAME or not IDST_PASSWORD:
            raise IdstLoginError("未配置 IDST_USERNAME/IDST_PASSWORD")
        last_error = None
        for attempt in range(1, 4):
            try:
                captcha = self._captcha.get_captcha()
                response = self._session.post(
                    self.login_url,
                    json={
                        "username": IDST_USERNAME,
                        "password": IDST_PASSWORD,
                        "key": captcha.key,
                        "verify_code": captcha.code,
                    },
                    timeout=IDST_LOGIN_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                data = response.json()
                token = self._extract_token(data)
                if token:
                    return token
                last_error = IdstLoginError(f"登录响应中未找到 token: {data}")
                logger.warning("IDST 登录失败（尝试 %s/3）: %s", attempt, data)
            except (CaptchaError, requests.RequestException, ValueError) as exc:
                last_error = IdstLoginError(f"IDST 登录失败: {exc}")
                logger.warning("IDST 登录失败（尝试 %s/3）: %s", attempt, exc)
        raise last_error or IdstLoginError("IDST 登录失败")

    def _close_ws(self) -> None:
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

    def _save_credentials(self) -> None:
        if self._credentials is None:
            return
        try:
            IDST_TOKEN_STORAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
            temp_path = IDST_TOKEN_STORAGE_PATH.with_suffix(".tmp")
            temp_path.write_text(json.dumps({
                "access_token": self._credentials.token,
                "code": self._credentials.code,
                "fetched_at": self._credentials.fetched_at,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, IDST_TOKEN_STORAGE_PATH)
        except OSError as exc:
            logger.warning("IDST token 持久化失败: %s", exc)

    def _load_cached_credentials(self) -> None:
        try:
            if not IDST_TOKEN_STORAGE_PATH.exists():
                return
            data = json.loads(IDST_TOKEN_STORAGE_PATH.read_text(encoding="utf-8"))
            token = data.get("access_token") or data.get("token")
            code = data.get("code")
            fetched_at = float(data.get("fetched_at", 0))
            if token and code and (time.time() - fetched_at) < IDST_TOKEN_CACHE_TTL:
                self._credentials = IdstCredentials(token, code, fetched_at)
                logger.info("已加载缓存的 IDST token（不会输出凭据）")
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("读取 IDST token 缓存失败，将重新登录: %s", exc)

    def _get_code(self, token: str) -> str:
        self._close_ws()
        try:
            # websocket-client 使用环境代理时可能导致内网地址走代理；显式关闭。
            self._ws = create_connection(
                self.ws_url,
                timeout=IDST_WS_TIMEOUT_SECONDS,
                ping_interval=20,
                ping_timeout=10,
                origin=IDST_BASE_URL,
                http_proxy_host=None,
                http_proxy_port=None,
                sslopt={
                    "cert_reqs": ssl.CERT_REQUIRED if IDST_VERIFY_SSL else ssl.CERT_NONE,
                },
            )
            self._ws.send(json.dumps({
                "route": "site/login",
                "data": {"token": token, "type": "login"},
            }))

            deadline = time.monotonic() + IDST_WS_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                raw = self._ws.recv()
                message = json.loads(raw)
                data = message.get("data") or {}
                if data.get("code") and data.get("time"):
                    logger.info("IDST WebSocket 登录成功，已获取 code")
                    return str(data["code"])
                if message.get("status") in {401, 10001, 10002}:
                    raise IdstLoginError(f"WebSocket 鉴权失败: {message}")
            raise IdstLoginError("WebSocket 超时，未返回 data.code")
        except IdstLoginError:
            raise
        except Exception as exc:
            raise IdstLoginError(f"IDST WebSocket 连接失败: {exc}") from exc

    def refresh(self) -> IdstCredentials:
        with self._lock:
            token = self._login()
            code = self._get_code(token)
            self._credentials = IdstCredentials(token, code, time.time())
            self._save_credentials()
            return self._credentials

    def get_credentials(self, force_refresh: bool = False) -> IdstCredentials:
        with self._lock:
            # code 与 WebSocket 会话绑定；断线时重新登录并获取 code。
            ws_ok = self._ws is not None and getattr(self._ws, "connected", False)
            if force_refresh or self._credentials is None or not self._credentials.is_valid:
                return self.refresh()
            if not ws_ok:
                try:
                    self._credentials.code = self._get_code(self._credentials.token)
                    self._credentials.fetched_at = time.time()
                    self._save_credentials()
                except IdstSessionError:
                    return self.refresh()
            return self._credentials

    def invalidate(self) -> None:
        with self._lock:
            self._credentials = None
            self._close_ws()

    def status(self) -> Optional[dict]:
        with self._lock:
            if self._credentials is None:
                return None
            return {
                "token_valid": bool(self._credentials.token),
                "code_valid": bool(self._credentials.code),
                "age_seconds": round(time.time() - self._credentials.fetched_at, 1),
                "websocket_connected": bool(
                    self._ws is not None and getattr(self._ws, "connected", False)
                ),
            }
