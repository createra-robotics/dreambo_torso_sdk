"""State HTTP / WebSocket routes for the Dreambo torso daemon."""

import asyncio
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from ....daemon.backend.abstract import Backend
from ..dependencies import get_backend, ws_get_backend
from ..models import DoAInfo, FullState

router = APIRouter(prefix="/state")


def _to_list(arr: Any) -> list[float] | None:
    """Convert a numpy array (or None) to a plain list of floats."""
    if arr is None:
        return None
    return arr.tolist() if hasattr(arr, "tolist") else list(arr)


@router.get("/present_neck")
async def get_neck(backend: Backend = Depends(get_backend)) -> list[float]:
    """Return the current neck joint positions [yaw, pitch, roll]."""
    return backend.get_present_neck_joint_positions().tolist()


@router.get("/present_left_arm")
async def get_left_arm(backend: Backend = Depends(get_backend)) -> list[float]:
    """Return the current left-arm joint positions [theta_a, theta_b]."""
    return backend.get_present_left_arm_joint_positions().tolist()


@router.get("/present_right_arm")
async def get_right_arm(backend: Backend = Depends(get_backend)) -> list[float]:
    """Return the current right-arm joint positions [theta_a, theta_b]."""
    return backend.get_present_right_arm_joint_positions().tolist()


@router.get("/present_nose")
async def get_nose(backend: Backend = Depends(get_backend)) -> list[float]:
    """Return the current nose joint positions [top, left, right]."""
    return backend.get_present_nose_joint_positions().tolist()


@router.get("/doa")
async def get_doa(
    backend: Backend = Depends(get_backend),
) -> DoAInfo | None:
    """Return the Direction of Arrival angle (radians) and speech flag."""
    if not backend.doa:
        return None
    result = backend.doa.get_DoA()
    if result is None:
        return None
    return DoAInfo(angle=result[0], speech_detected=result[1])


@router.get("/full")
async def get_full_state(
    with_control_mode: bool = True,
    with_neck: bool = True,
    with_left_arm: bool = True,
    with_right_arm: bool = True,
    with_nose: bool = True,
    with_target_neck: bool = False,
    with_target_left_arm: bool = False,
    with_target_right_arm: bool = False,
    with_target_nose: bool = False,
    with_doa: bool = False,
    backend: Backend = Depends(get_backend),
) -> FullState:
    """Return the full robot state with optional per-subsystem fields."""
    result: dict[str, Any] = {}

    if with_control_mode:
        result["control_mode"] = backend.get_motor_control_mode().value

    if with_neck:
        result["neck"] = backend.get_present_neck_joint_positions().tolist()
    if with_left_arm:
        result["left_arm"] = backend.get_present_left_arm_joint_positions().tolist()
    if with_right_arm:
        result["right_arm"] = backend.get_present_right_arm_joint_positions().tolist()
    if with_nose:
        result["nose"] = backend.get_present_nose_joint_positions().tolist()

    if with_target_neck:
        result["target_neck"] = _to_list(backend.target_neck_joint_positions)
    if with_target_left_arm:
        result["target_left_arm"] = _to_list(backend.target_left_arm_joint_positions)
    if with_target_right_arm:
        result["target_right_arm"] = _to_list(backend.target_right_arm_joint_positions)
    if with_target_nose:
        result["target_nose"] = _to_list(backend.target_nose_joint_positions)

    if with_doa and backend.doa:
        doa_result = backend.doa.get_DoA()
        if doa_result:
            result["doa"] = DoAInfo(angle=doa_result[0], speech_detected=doa_result[1])

    result["timestamp"] = datetime.now(timezone.utc)
    return FullState.model_validate(result)


@router.websocket("/ws/full")
async def ws_full_state(
    websocket: WebSocket,
    frequency: float = 10.0,
    with_neck: bool = True,
    with_left_arm: bool = True,
    with_right_arm: bool = True,
    with_nose: bool = True,
    with_target_neck: bool = False,
    with_target_left_arm: bool = False,
    with_target_right_arm: bool = False,
    with_target_nose: bool = False,
    with_doa: bool = False,
    backend: Backend = Depends(ws_get_backend),
) -> None:
    """Stream the full state of the robot over a WebSocket at ``frequency`` Hz."""
    await websocket.accept()
    period = 1.0 / frequency

    try:
        while True:
            full_state = await get_full_state(
                with_neck=with_neck,
                with_left_arm=with_left_arm,
                with_right_arm=with_right_arm,
                with_nose=with_nose,
                with_target_neck=with_target_neck,
                with_target_left_arm=with_target_left_arm,
                with_target_right_arm=with_target_right_arm,
                with_target_nose=with_target_nose,
                with_doa=with_doa,
                backend=backend,
            )
            await websocket.send_text(full_state.model_dump_json())
            await asyncio.sleep(period)
    except WebSocketDisconnect:
        pass
