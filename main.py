"""
校园智能门禁中转服务 - FastAPI 主入口
提供标准 RESTful API 供外部/AI 调用
"""

import asyncio
import logging
import secrets
import sys
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from threading import Lock
from typing import List, Optional
from logging.handlers import RotatingFileHandler

from fastapi import Depends, FastAPI, HTTPException, Request, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

from config import (
    HOST,
    PORT,
    DEBUG,
    LOG_LEVEL,
    LOG_FORMAT,
    LOG_DATE_FORMAT,
    LOG_FILE_PATH,
    LOG_TO_CONSOLE,
    API_KEYS,
    API_KEY_MIN_LENGTH,
    API_RATE_LIMIT,
    API_RATE_WINDOW_SECONDS,
    API_KEY_STORAGE_PATH,
    LOG_MAX_BYTES,
    LOG_BACKUP_COUNT,
    PREWARM_ADO_TOKEN,
)
from core.token_manager import TokenManager, TokenError, TokenFetchError
from core.door_driver import DoorDriver, DoorError, DoorRequestError, DoorUnauthorizedError, DoorResponseError, DoorActionResult
from core.idst_session_manager import IdstSessionManager
from core.idst_driver import IdstDriver
from api.idst_routes import create_idst_router
from rooms_config import get_lock_ids_by_room, get_lock_ids_by_rooms, room_exists

# =============================================================================
# 日志配置
# =============================================================================
def setup_logging():
    """配置全局日志"""
    log_level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    
    # 创建根 logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # 清除现有 handlers
    root_logger.handlers.clear()
    
    # 格式化器
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    
    # 文件 handler
    file_handler = RotatingFileHandler(
        LOG_FILE_PATH,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(log_level)
    root_logger.addHandler(file_handler)
    
    # 控制台 handler（可选）
    if LOG_TO_CONSOLE:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(log_level)
        root_logger.addHandler(console_handler)
    
    # 设置第三方库日志级别
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


# 初始化日志
setup_logging()
logger = logging.getLogger(__name__)
logger.info("API 鉴权密钥已加载；密钥文件: %s", API_KEY_STORAGE_PATH)


# =============================================================================
# API 鉴权
# =============================================================================
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_rate_limit_lock = Lock()
_request_times_by_client: dict[str, deque[float]] = defaultdict(deque)


def _check_rate_limit(client_id: str) -> Optional[int]:
    """返回剩余等待秒数；返回 None 表示允许请求。"""
    now = time.monotonic()
    cutoff = now - API_RATE_WINDOW_SECONDS

    with _rate_limit_lock:
        timestamps = _request_times_by_client[client_id]
        while timestamps and timestamps[0] <= cutoff:
            timestamps.popleft()

        if len(timestamps) >= API_RATE_LIMIT:
            return max(1, int(timestamps[0] + API_RATE_WINDOW_SECONDS - now))

        timestamps.append(now)

        # 清理长期不活跃客户端，避免客户端 IP 数量增长导致内存持续增加。
        if len(_request_times_by_client) > 10000:
            inactive = [
                key for key, values in _request_times_by_client.items()
                if not values or values[-1] <= cutoff
            ]
            for key in inactive:
                _request_times_by_client.pop(key, None)

    return None


async def require_api_key(
    request: Request,
    x_api_key: Optional[str] = Security(api_key_header),
):
    """校验中转服务 API Key；鉴权信息位于请求头，不占用业务请求体。"""
    if not API_KEYS or any(len(key) < API_KEY_MIN_LENGTH for key in API_KEYS):
        logger.error("ADO_API_KEY 未配置，拒绝访问受保护接口")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"服务端未配置有效 API 鉴权密钥（至少 {API_KEY_MIN_LENGTH} 个字符）",
        )

    client_id = request.client.host if request.client else "unknown"
    retry_after = _check_rate_limit(client_id)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="请求过于频繁，请稍后再试",
            headers={"Retry-After": str(retry_after)},
        )

    if not x_api_key or not any(
        secrets.compare_digest(x_api_key, configured_key)
        for configured_key in API_KEYS
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key 无效或缺失",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return True


# =============================================================================
# 全局单例实例
# =============================================================================
token_manager = TokenManager()
door_driver = DoorDriver(token_manager)
idst_session_manager = IdstSessionManager()
idst_driver = IdstDriver(idst_session_manager)
idst_router = create_idst_router(require_api_key, idst_driver, idst_session_manager)


# =============================================================================
# Pydantic 模型定义
# =============================================================================
class DoorOpenRequest(BaseModel):
    """门禁操作请求体（开锁/落锁通用）- 支持批量房间/直接传 lock_ids"""
    rooms: List[str] = Field(
        default_factory=list,
        description="房间号列表（如 [\"910\",\"1-803\"]），支持智能容错，多房间自动合并去重"
    )
    lock_ids: List[str] = Field(
        default_factory=list,
        description="门锁 ID 列表（备用方案，当 rooms 未提供时使用）"
    )
    reason: str = Field(
        default="AI 助手调度操作",
        description="操作原因/备注"
    )


class DoorOpenResponse(BaseModel):
    """门禁操作响应体（开锁/落锁通用）"""
    code: int = Field(description="业务状态码：200 成功，非 200 失败")
    message: str = Field(description="响应消息")
    detail: Optional[dict] = Field(default=None, description="详细响应数据")
    executed_locks_count: int = Field(default=0, description="实际操作的门锁数量")


class TokenResponse(BaseModel):
    """Token 响应体"""
    code: int
    message: str
    token: Optional[str] = None
    cache_age_seconds: Optional[float] = None


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str
    service: str
    version: str
    token_valid: bool
    cache_age_seconds: Optional[float] = None


# =============================================================================
# 应用生命周期管理
# =============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动/关闭生命周期"""
    # 启动时
    logger.info("=" * 50)
    logger.info("Campus Door Master 服务启动中...")
    logger.info("=" * 50)
    
    # 可选后台预热，不让上游登录阻塞 API 启动。
    prewarm_task = None
    if PREWARM_ADO_TOKEN:
        async def prewarm_ado_token():
            try:
                token = await asyncio.to_thread(token_manager.get_token, True)
                logger.info("启动预热 ADO Token 成功，长度: %s", len(token))
            except TokenError as exc:
                logger.warning("启动预热 ADO Token 失败（不阻塞服务）: %s", exc)

        prewarm_task = asyncio.create_task(prewarm_ado_token())
    
    yield

    if prewarm_task and not prewarm_task.done():
        prewarm_task.cancel()
    
    # 关闭时
    logger.info("Campus Door Master 服务正在关闭...")


# =============================================================================
# FastAPI 应用实例
# =============================================================================
app = FastAPI(
    title="Campus Door Master",
    description="校园智能门禁中转服务 - 为 AI Agent 提供标准化开门 API",
    version="1.0.0",
    debug=DEBUG,
    lifespan=lifespan,
)

# CORS 配置（允许所有来源，生产环境建议限制）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(idst_router)


# =============================================================================
# 全局异常处理
# =============================================================================
@app.exception_handler(DoorUnauthorizedError)
async def door_unauthorized_handler(request: Request, exc: DoorUnauthorizedError):
    logger.error(f"开门鉴权失败: {exc}")
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"code": 401, "message": "Token 失效或凭证无效，请联系管理员", "detail": str(exc)},
    )


@app.exception_handler(DoorResponseError)
async def door_response_error_handler(request: Request, exc: DoorResponseError):
    logger.warning(f"开门业务失败: {exc}")
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"code": 400, "message": str(exc), "detail": {}},
    )


@app.exception_handler(DoorError)
async def door_error_handler(request: Request, exc: DoorError):
    logger.error(f"开门操作异常: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"code": 500, "message": "开门服务内部错误", "detail": str(exc)},
    )


@app.exception_handler(TokenError)
async def token_error_handler(request: Request, exc: TokenError):
    logger.error(f"Token 管理异常: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"code": 500, "message": "Token 服务异常", "detail": str(exc)},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"未处理的异常: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"code": 500, "message": "服务器内部错误", "detail": "请联系管理员"},
    )


# =============================================================================
# API 路由定义
# =============================================================================
@app.get("/health", response_model=HealthResponse, tags=["系统"])
async def health_check():
    """健康检查接口"""
    token_info = token_manager.get_token_info()
    return HealthResponse(
        status="ok",
        service="Campus Door Master",
        version="1.0.0",
        token_valid=token_info is not None and token_info.is_cache_valid,
        cache_age_seconds=token_info.cache_age_seconds if token_info else None,
    )


@app.post(
    "/api/v1/doors/open",
    response_model=DoorOpenResponse,
    tags=["门禁控制"],
    dependencies=[Depends(require_api_key)],
)
async def open_door(request: DoorOpenRequest):
    """
    开锁接口（支持批量）

    传入方式优先级：
    1. rooms（推荐）：房间号列表，自动解析合并 lock_ids
    2. lock_ids：直接传门锁 UUID 列表（备用）
    """
    logger.info(
        f"收到开锁请求: rooms={request.rooms}, lock_ids={request.lock_ids}, "
        f"reason={request.reason}"
    )

    try:
        if request.rooms:
            lock_ids = get_lock_ids_by_rooms(request.rooms)
            if not lock_ids:
                raise DoorRequestError(
                    f"未找到有效门锁: rooms={request.rooms}"
                )
            result = door_driver.open_door(
                lock_ids=lock_ids,
                reason=request.reason,
            )
        elif request.lock_ids:
            result = door_driver.open_door(
                lock_ids=request.lock_ids,
                reason=request.reason,
            )
        else:
            raise DoorRequestError("必须提供 rooms 或 lock_ids")

        return DoorOpenResponse(
            code=200 if result.success else 400,
            message=result.message,
            detail=result.detail,
            executed_locks_count=len(result.lock_ids),
        )

    except DoorUnauthorizedError:
        raise
    except DoorResponseError:
        raise
    except DoorRequestError as e:
        logger.warning(f"开锁请求参数错误: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except DoorError as e:
        logger.error(f"开锁操作失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/api/v1/doors/close",
    response_model=DoorOpenResponse,
    tags=["门禁控制"],
    dependencies=[Depends(require_api_key)],
)
async def close_door(request: DoorOpenRequest):
    """
    落锁接口（支持批量）

    传入方式优先级：
    1. rooms（推荐）：房间号列表，自动解析合并 lock_ids
    2. lock_ids：直接传门锁 UUID 列表（备用）
    """
    logger.info(
        f"收到落锁请求: rooms={request.rooms}, lock_ids={request.lock_ids}, "
        f"reason={request.reason}"
    )

    try:
        if request.rooms:
            lock_ids = get_lock_ids_by_rooms(request.rooms)
            if not lock_ids:
                raise DoorRequestError(
                    f"未找到有效门锁: rooms={request.rooms}"
                )
            result = door_driver.close_door(
                lock_ids=lock_ids,
                reason=request.reason,
            )
        elif request.lock_ids:
            result = door_driver.close_door(
                lock_ids=request.lock_ids,
                reason=request.reason,
            )
        else:
            raise DoorRequestError("必须提供 rooms 或 lock_ids")

        return DoorOpenResponse(
            code=200 if result.success else 400,
            message=result.message,
            detail=result.detail,
            executed_locks_count=len(result.lock_ids),
        )

    except DoorUnauthorizedError:
        raise
    except DoorResponseError:
        raise
    except DoorRequestError as e:
        logger.warning(f"落锁请求参数错误: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except DoorError as e:
        logger.error(f"落锁操作失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/api/v1/token/refresh",
    response_model=TokenResponse,
    tags=["Token 管理"],
    dependencies=[Depends(require_api_key)],
)
async def refresh_token():
    """手动强制刷新 Token"""
    logger.info("收到手动刷新 Token 请求")

    try:
        token_manager.force_refresh()
        token_info = token_manager.get_token_info()

        return TokenResponse(
            code=200,
            message="Token 刷新成功",
            token=None,
            cache_age_seconds=token_info.cache_age_seconds if token_info else None,
        )
    except TokenFetchError as e:
        logger.error(f"手动刷新 Token 失败: {e}")
        raise HTTPException(status_code=500, detail=f"Token 刷新失败: {e}")
    except TokenError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/api/v1/token/status",
    response_model=TokenResponse,
    tags=["Token 管理"],
    dependencies=[Depends(require_api_key)],
)
async def token_status():
    """查询当前 Token 状态（不触发刷新）"""
    token_info = token_manager.get_token_info()

    if token_info is None:
        return TokenResponse(
            code=404,
            message="无可用 Token",
            token=None,
            cache_age_seconds=None,
        )

    return TokenResponse(
        code=200,
        message="Token 缓存有效" if token_info.is_cache_valid else "Token 缓存已过期",
        token=token_info.access_token[:20] + "..." if len(token_info.access_token) > 20 else token_info.access_token,
        cache_age_seconds=token_info.cache_age_seconds,
    )


# =============================================================================
# 启动入口
# =============================================================================
if __name__ == "__main__":
    import uvicorn
    
    logger.info(f"启动服务: http://{HOST}:{PORT}")
    uvicorn.run(
        "main:app",
        host=HOST,
        port=PORT,
        reload=DEBUG,
        log_level=LOG_LEVEL.lower(),
        access_log=DEBUG,
    )
