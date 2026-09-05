"""IDST HTTP 路由，与 ADO 门禁路由隔离。"""

from typing import Callable, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from idst_rooms_config import get_idst_device
from core.idst_driver import IdstDriver, IdstDriverError
from core.idst_session_manager import IdstSessionManager, IdstSessionError


class IdstRfControlRequest(BaseModel):
    id: str
    ctrl: dict


class IdstControlRequest(BaseModel):
    rooms: List[str] = Field(default_factory=list)
    device_ids: List[str] = Field(default_factory=list)
    reason: str = Field(default="IDST 开门操作")


def create_idst_router(
    require_api_key: Callable,
    idst_driver: IdstDriver,
    idst_session_manager: IdstSessionManager,
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/v1/idst/rf-control", dependencies=[Depends(require_api_key)])
    async def idst_rf_control(request: IdstRfControlRequest):
        try:
            return await run_in_threadpool(idst_driver.control, request.model_dump())
        except IdstSessionError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except IdstDriverError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.post("/api/v1/idst/control", dependencies=[Depends(require_api_key)])
    @router.post("/api/v1/idst/open", dependencies=[Depends(require_api_key)])
    async def idst_control(request: IdstControlRequest):
        device_ids = list(request.device_ids)
        device_rf_ids = {}
        unknown_rooms = []
        for room in request.rooms:
            device = get_idst_device(room)
            if device and device["id"] not in device_ids:
                device_ids.append(device["id"])
                device_rf_ids[device["id"]] = device["rf_id"]
            elif not device:
                unknown_rooms.append(room)

        if unknown_rooms:
            raise HTTPException(status_code=400, detail=f"未找到 IDST 房间映射: {unknown_rooms}")
        if not device_ids:
            raise HTTPException(status_code=400, detail="必须提供 rooms 或 device_ids")

        results = []
        try:
            for device_id in device_ids:
                # IDST 当前只提供开门业务，rf_id 按房间映射自动选择。
                rf_id = device_rf_ids.get(device_id, 5)
                result = await run_in_threadpool(
                    idst_driver.control_device, device_id, rf_id, 1
                )
                results.append({
                    "device_id": device_id,
                    "reason": request.reason,
                    "result": result,
                })
        except IdstSessionError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except IdstDriverError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        success = all(item["result"].get("status") == 0 for item in results)
        return {
            "code": 200 if success else 400,
            "message": "操作成功" if success else "部分或全部设备操作失败",
            "results": results,
        }

    @router.get("/api/v1/idst/session/status", dependencies=[Depends(require_api_key)])
    async def idst_session_status():
        return {
            "code": 200,
            "message": "IDST 会话状态",
            "data": idst_session_manager.status(),
        }

    @router.post("/api/v1/idst/session/refresh", dependencies=[Depends(require_api_key)])
    async def refresh_idst_session():
        try:
            credentials = await run_in_threadpool(idst_session_manager.refresh)
            return {
                "code": 200,
                "message": "IDST 会话刷新成功",
                "data": {
                    "token_length": len(credentials.token),
                    "code_received": bool(credentials.code),
                },
            }
        except IdstSessionError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    return router
