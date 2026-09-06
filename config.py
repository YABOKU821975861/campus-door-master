"""
校园智能门禁中转服务 - 全局配置模块
集中管理所有配置项：账号、密码、API地址、端口、日志路径等
"""

import os
import secrets
from pathlib import Path
from typing import List

from dotenv import load_dotenv

# 项目根目录（基于当前文件位置推导，确保相对路径正确）
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / "campus-door-master.env")

# =============================================================================
# 服务基础配置
# =============================================================================
# API 服务监听地址与端口
HOST: str = "0.0.0.0"
PORT: int = 8000

# 中转服务 API 鉴权密钥。
# 优先使用环境变量；未配置时首次启动自动生成并持久化，后续启动保持不变。
# ADO_API_KEYS 支持用逗号配置多个密钥，便于无停机轮换；ADO_API_KEY 保持兼容单密钥部署。
# 调用方通过请求头 X-API-Key 传递。
API_KEY_STORAGE_PATH: Path = BASE_DIR / "storage" / "api_key"


def _load_or_create_api_key() -> str:
    configured = os.getenv("ADO_API_KEYS") or os.getenv("ADO_API_KEY", "")
    if configured.strip():
        return configured

    API_KEY_STORAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with API_KEY_STORAGE_PATH.open("x", encoding="utf-8") as key_file:
            key_file.write(f"{secrets.token_urlsafe(48)}\n")
    except FileExistsError:
        pass

    try:
        API_KEY_STORAGE_PATH.chmod(0o600)
        return API_KEY_STORAGE_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


_api_keys_value = _load_or_create_api_key()
API_KEYS: tuple[str, ...] = tuple(
    key.strip() for key in _api_keys_value.split(",") if key.strip()
)
API_KEY: str = API_KEYS[0] if API_KEYS else ""
API_KEY_MIN_LENGTH: int = 32

# 单客户端基础限流：默认每分钟最多 30 个受保护请求。
API_RATE_LIMIT: int = int(os.getenv("ADO_API_RATE_LIMIT", "30"))
API_RATE_WINDOW_SECONDS: int = int(os.getenv("ADO_API_RATE_WINDOW_SECONDS", "60"))

# 是否开启调试模式（生产环境建议设为 False）
DEBUG: bool = os.getenv("ADO_DEBUG", "false").lower() in {"1", "true", "yes", "on"}

# =============================================================================
# 目标门禁系统凭证与地址
# =============================================================================
# 登录账号（学号/工号）
USERNAME: str = os.getenv("ADO_USERNAME", "")

# 加密后的密码串（抓包获取的加密字符串）
ENCRYPTED_PASSWORD: str = os.getenv("ADO_PASSWORD", "")

# 门禁系统基础 URL（不含尾部斜杠）
BASE_URL: str = os.getenv("ADO_BASE_URL", "")

# 登录接口路径
LOGIN_ENDPOINT: str = os.getenv("ADO_LOGIN_ENDPOINT", "/api/login")

# 验证码接口路径
CAPTCHA_ENDPOINT: str = os.getenv("ADO_CAPTCHA_ENDPOINT", "/api/captcha")

# 开锁接口路径
OPEN_DOOR_ENDPOINT: str = os.getenv(
    "ADO_OPEN_DOOR_ENDPOINT", "/api/remote/openDoors/open"
)

# 落锁接口路径
CLOSE_DOOR_ENDPOINT: str = os.getenv(
    "ADO_CLOSE_DOOR_ENDPOINT", "/api/remote/openDoors/keep_close"
)

# =============================================================================
# 请求头配置
# =============================================================================
# 客户端类型标识
CLIENT_TYPE: str = "teacher"

# 平台标识
PLATFORM: str = "web"

# User-Agent
USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)

# =============================================================================
# Token 管理配置
# =============================================================================
# Token 缓存文件路径（相对路径，存储于 storage/ 目录）
TOKEN_STORAGE_PATH: Path = BASE_DIR / "storage" / "token.json"

# Token 最大重试次数（获取/刷新失败时）
TOKEN_MAX_RETRIES: int = 3

# Token 重试间隔（秒）
TOKEN_RETRY_INTERVAL_SECONDS: int = 2

# =============================================================================
# 验证码 OCR 配置
# =============================================================================
# OCR 识别最大重试次数
CAPTCHA_MAX_RETRIES: int = 3

# 验证码请求超时（秒）
CAPTCHA_TIMEOUT_SECONDS: int = 5

# 登录请求超时（秒）
LOGIN_TIMEOUT_SECONDS: int = 5

# 开门请求超时（秒）
OPEN_DOOR_TIMEOUT_SECONDS: int = 10

# =============================================================================
# 日志配置
# =============================================================================
# 日志文件路径（相对路径，存储于 logs/ 目录）
LOG_FILE_PATH: Path = BASE_DIR / "logs" / "app.log"

# 日志级别：DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_LEVEL: str = "INFO"

# 日志格式
LOG_FORMAT: str = (
    "%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s"
)

# 日志日期格式
LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"

# 是否同时输出到控制台
LOG_TO_CONSOLE: bool = True
LOG_MAX_BYTES: int = int(os.getenv("ADO_LOG_MAX_BYTES", str(10 * 1024 * 1024)))
LOG_BACKUP_COUNT: int = int(os.getenv("ADO_LOG_BACKUP_COUNT", "5"))
PREWARM_ADO_TOKEN: bool = os.getenv("ADO_PREWARM_TOKEN", "false").lower() in {"1", "true", "yes", "on"}

# =============================================================================
# SSL/安全配置
# =============================================================================
# 是否验证 SSL 证书（目标站点使用自签证书，默认关闭验证）
ADO_VERIFY_SSL: bool = os.getenv("ADO_VERIFY_SSL", "false").lower() in {"1", "true", "yes", "on"}

# =============================================================================
# IDST 设备接口配置（与 ADO 门禁体系独立）
# =============================================================================
IDST_BASE_URL: str = os.getenv("IDST_BASE_URL", "https://172.20.196.253")
IDST_LOGIN_ENDPOINT: str = os.getenv("IDST_LOGIN_ENDPOINT", "/api2/site/login")
IDST_CAPTCHA_ENDPOINT: str = os.getenv("IDST_CAPTCHA_ENDPOINT", "/api2/site/captcha-image")
IDST_RF_CONTROL_ENDPOINT: str = os.getenv("IDST_RF_CONTROL_ENDPOINT", "/api2/device/rf-ctrl")
IDST_USERNAME: str = os.getenv("IDST_USERNAME", "")
IDST_PASSWORD: str = os.getenv("IDST_PASSWORD", "")
IDST_LOGIN_TIMEOUT_SECONDS: int = int(os.getenv("IDST_LOGIN_TIMEOUT_SECONDS", "10"))
IDST_WS_TIMEOUT_SECONDS: int = int(os.getenv("IDST_WS_TIMEOUT_SECONDS", "10"))
IDST_TOKEN_CACHE_TTL: int = int(os.getenv("IDST_TOKEN_CACHE_TTL", "600"))
IDST_TOKEN_STORAGE_PATH: Path = BASE_DIR / "storage" / "idst_token.json"
IDST_VERIFY_SSL: bool = os.getenv("IDST_VERIFY_SSL", "false").lower() in {"1", "true", "yes", "on"}

# =============================================================================
# 运行时自动创建所需目录
# =============================================================================
def ensure_directories() -> None:
    """确保存储和日志目录存在"""
    TOKEN_STORAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)


# 模块加载时自动创建目录
ensure_directories()
