"""
Token 管理模块
负责 Token 的自动获取、缓存与定时刷新

策略：
- 启动时获取一次 Token 并缓存
- 后续 10 分钟内直接返回缓存
- 超过 10 分钟自动重新获取
- 开门遇到 401 时立即刷新重试
"""

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, asdict
from typing import Optional

import requests
import urllib3

from config import (
    BASE_URL,
    LOGIN_ENDPOINT,
    ENCRYPTED_PASSWORD,
    USERNAME,
    LOGIN_TIMEOUT_SECONDS,
    TOKEN_STORAGE_PATH,
    TOKEN_MAX_RETRIES,
    TOKEN_RETRY_INTERVAL_SECONDS,
    CLIENT_TYPE,
    PLATFORM,
    USER_AGENT,
    ADO_VERIFY_SSL,
)
from core.captcha_ocr import CaptchaOCR, CaptchaError

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

# Token 缓存有效期（秒）：10 分钟
TOKEN_CACHE_TTL = 600


class TokenError(Exception):
    """Token 相关异常基类"""
    pass


class TokenExpiredError(TokenError):
    """Token 已过期"""
    pass


class TokenFetchError(TokenError):
    """Token 获取失败"""
    pass


class TokenRefreshError(TokenError):
    """Token 刷新失败"""
    pass


@dataclass
class TokenInfo:
    """Token 信息数据类"""
    access_token: str
    fetched_at: float  # 获取时间戳（Unix 秒）

    @property
    def is_cache_valid(self) -> bool:
        """判断缓存是否还在有效期内（10 分钟）"""
        return (time.time() - self.fetched_at) < TOKEN_CACHE_TTL

    @property
    def cache_age_seconds(self) -> float:
        """缓存已存活时间（秒）"""
        return time.time() - self.fetched_at

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TokenInfo":
        return cls(**data)


class TokenManager:
    """
    Token 管理器：单例模式
    
    策略：
    1. 启动时获取一次新 Token
    2. 缓存 10 分钟，到期自动刷新
    3. 开门遇到 401 时立即强制刷新
    """

    _instance: Optional["TokenManager"] = None
    _lock = threading.RLock()

    def __new__(cls) -> "TokenManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._token: Optional[TokenInfo] = None
        self._fetch_lock = threading.Lock()
        self._session = requests.Session()
        self._session.verify = ADO_VERIFY_SSL
        self._session.headers.update({
            "User-Agent": USER_AGENT,
            "Origin": BASE_URL,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Content-Type": "application/x-www-form-urlencoded",
        })

        self._captcha_ocr = CaptchaOCR(session=self._session)

        self._initialized = True
        logger.info("TokenManager 初始化完成")

    @property
    def login_url(self) -> str:
        return f"{BASE_URL.rstrip('/')}{LOGIN_ENDPOINT}"

    def _save_token_to_storage(self) -> None:
        """将 Token 持久化到本地文件"""
        try:
            if self._token:
                with open(TOKEN_STORAGE_PATH, "w", encoding="utf-8") as f:
                    json.dump(self._token.to_dict(), f, ensure_ascii=False, indent=2)
                os.chmod(TOKEN_STORAGE_PATH, 0o600)
                logger.debug("Token 已持久化到本地存储")
        except Exception as e:
            logger.error(f"Token 持久化失败: {e}")

    def _perform_login(self, key: str, captcha_code: str) -> Optional[str]:
        """
        执行登录请求获取 Token
        
        Returns:
            access_token 或 None
        """
        payload = {
            "grant_type": "password",
            "username": USERNAME,
            "password": ENCRYPTED_PASSWORD,
            "remember": "true",
            "key": key,
            "captcha": captcha_code,
        }

        try:
            logger.debug(f"提交登录请求: {self.login_url}")
            response = self._session.post(
                self.login_url,
                data=payload,
                timeout=LOGIN_TIMEOUT_SECONDS
            )

            if response.status_code != 200:
                logger.error(f"登录失败 HTTP {response.status_code}: {response.text[:200]}")
                return None

            res_json = response.json()

            # 兼容多种返回格式提取 token
            token = (
                res_json.get("access_token")
                or res_json.get("token")
                or res_json.get("data", {}).get("token")
                or res_json.get("data", {}).get("access_token")
            )

            if not token:
                logger.error(f"登录响应中未找到 token: {res_json}")
                return None

            logger.info("登录成功，已获取新 Token")
            return token

        except requests.RequestException as e:
            logger.error(f"登录请求网络异常: {e}")
        except Exception as e:
            logger.exception(f"登录过程中发生未知异常: {e}")

        return None

    def _fetch_new_token(self) -> str:
        """
        完整的获取新 Token 流程（含验证码获取与识别）
        
        Returns:
            新的 access_token
            
        Raises:
            TokenFetchError: 获取失败
        """
        last_error = None

        for attempt in range(1, TOKEN_MAX_RETRIES + 1):
            try:
                logger.info(f"开始获取新 Token (尝试 {attempt}/{TOKEN_MAX_RETRIES})")

                # 1. 获取并识别验证码
                captcha_result = self._captcha_ocr.get_captcha()

                # 2. 使用验证码登录获取 Token
                token = self._perform_login(captcha_result.key, captcha_result.code)

                if token:
                    # 3. 写入缓存
                    self._token = TokenInfo(
                        access_token=token,
                        fetched_at=time.time(),
                    )
                    self._save_token_to_storage()
                    return token

                last_error = TokenFetchError("登录请求成功但未返回有效 Token")

            except CaptchaError as e:
                last_error = TokenFetchError(f"验证码处理失败: {e}")
                logger.warning(f"获取 Token 失败 (尝试 {attempt}/{TOKEN_MAX_RETRIES}): {e}")
            except Exception as e:
                last_error = TokenFetchError(f"未知错误: {e}")
                logger.exception(f"获取 Token 异常 (尝试 {attempt}/{TOKEN_MAX_RETRIES})")

            if attempt < TOKEN_MAX_RETRIES:
                time.sleep(TOKEN_RETRY_INTERVAL_SECONDS)

        raise last_error or TokenFetchError("获取 Token 失败：达到最大重试次数")

    def get_token(self, force_refresh: bool = False) -> str:
        """
        获取当前有效 Token（线程安全）
        
        规则：
        - 强制刷新 或 无缓存 → 获取新 Token
        - 缓存超过 10 分钟 → 获取新 Token
        - 缓存在有效期内 → 直接返回缓存
        
        Args:
            force_refresh: 是否强制刷新
            
        Returns:
            access_token 字符串
        """
        with self._fetch_lock:
            # 强制刷新 或 首次获取
            if force_refresh or self._token is None:
                logger.info("强制刷新或无缓存，获取新 Token")
                return self._fetch_new_token()

            # 缓存还在有效期内（10 分钟）
            if self._token.is_cache_valid:
                remaining = TOKEN_CACHE_TTL - self._token.cache_age_seconds
                logger.debug(f"返回缓存 Token，剩余有效期: {remaining:.0f} 秒")
                return self._token.access_token

            # 缓存已过期，重新获取
            logger.info(f"Token 缓存已过期（已存活 {self._token.cache_age_seconds:.0f} 秒），重新获取")
            return self._fetch_new_token()

    def force_refresh(self) -> str:
        """强制刷新 Token（同步阻塞）"""
        return self.get_token(force_refresh=True)

    def invalidate(self) -> None:
        """使当前缓存失效（不删文件，仅清内存），下次 get_token 会重新获取"""
        with self._fetch_lock:
            self._token = None
            logger.info("Token 内存缓存已清空")

    def get_token_info(self) -> Optional[TokenInfo]:
        """获取当前 Token 详细信息（不触发刷新）"""
        return self._token

    def clear_token(self) -> None:
        """彻底清除 Token（内存 + 文件）"""
        with self._fetch_lock:
            self._token = None
            try:
                if TOKEN_STORAGE_PATH.exists():
                    TOKEN_STORAGE_PATH.unlink()
                logger.info("Token 已彻底清除（内存 + 文件）")
            except Exception as e:
                logger.error(f"清除 Token 文件失败: {e}")
