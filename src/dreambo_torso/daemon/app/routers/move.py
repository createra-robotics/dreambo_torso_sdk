"""Movement HTTP / WebSocket routes for the Dreambo torso daemon."""

import asyncio
import json
from typing import Any, Coroutine
from uuid import UUID, uuid4

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from modelscope.hub.errors import NotExistError
from pydantic import BaseModel

from dreambo_torso.motion.recorded_move import RecordedMoves
from dreambo_torso.utils.interpolation import InterpolationTechnique

from ....daemon.backend.abstract import Backend
from ..dependencies import get_backend, ws_get_backend
from ..models import FullBodyTarget

move_tasks: dict[UUID, asyncio.Task[None]] = {}
move_listeners: list[WebSocket] = []


router = APIRouter(prefix="/move")


class GotoModelRequest(BaseModel):
    """Request model for the goto endpoint."""

    neck: list[float] | None = None         # [yaw, pitch, roll]
    left_arm: list[float] | None = None     # [theta_a, theta_b]
    right_arm: list[float] | None = None    # [theta_a, theta_b]
    nose: list[float] | None = None         # [top, left, right]
    duration: float
    interpolation: InterpolationTechnique = InterpolationTechnique.MIN_JERK

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "neck": [0.0, 0.2, 0.0],
                    "left_arm": [0.0, 0.0],
                    "right_arm": [0.0, 0.0],
                    "nose": [0.0, 0.0, 0.0],
                    "duration": 2.0,
                    "interpolation": "minjerk",
                },
                {
                    "neck": [0.0, 0.4, 0.0],
                    "duration": 1.0,
                    "interpolation": "linear",
                },
            ],
        }
    }


class MoveUUID(BaseModel):
    """Model representing a unique identifier for a move task."""

    uuid: UUID


def create_move_task(coro: Coroutine[Any, Any, None]) -> MoveUUID:
    """Create a new move task using async task coroutine."""
    uuid = uuid4()

    async def notify_listeners(message: str, details: str = "") -> None:
        for ws in move_listeners:
            try:
                await ws.send_json(
                    {"type": message, "uuid": str(uuid), "details": details}
                )
            except (RuntimeError, WebSocketDisconnect):
                move_listeners.remove(ws)

    async def wrap_coro() -> None:
        try:
            await notify_listeners("move_started")
            await coro
            await notify_listeners("move_completed")
        except Exception as e:
            await notify_listeners("move_failed", details=str(e))
        except asyncio.CancelledError:
            await notify_listeners("move_cancelled")
        finally:
            move_tasks.pop(uuid, None)

    task = asyncio.create_task(wrap_coro())
    move_tasks[uuid] = task
    return MoveUUID(uuid=uuid)


async def stop_move_task(uuid: UUID) -> dict[str, str]:
    """Cancel a running move task by UUID."""
    if uuid not in move_tasks:
        raise KeyError(f"Running move with UUID {uuid} not found")

    task = move_tasks.pop(uuid, None)
    assert task is not None
    if task.cancel():
        try:
            await task
        except asyncio.CancelledError:
            pass

    return {"message": f"Stopped move with UUID: {uuid}"}


@router.get("/running")
async def get_running_moves() -> list[MoveUUID]:
    """List currently running move tasks."""
    return [MoveUUID(uuid=uuid) for uuid in move_tasks.keys()]


@router.post("/goto")
async def goto(
    goto_req: GotoModelRequest, backend: Backend = Depends(get_backend)
) -> MoveUUID:
    """Request a movement to per-subsystem joint targets."""
    return create_move_task(
        backend.goto_target(
            neck=np.array(goto_req.neck) if goto_req.neck else None,
            left_arm=np.array(goto_req.left_arm) if goto_req.left_arm else None,
            right_arm=np.array(goto_req.right_arm) if goto_req.right_arm else None,
            nose=np.array(goto_req.nose) if goto_req.nose else None,
            duration=goto_req.duration,
            method=goto_req.interpolation,
        )
    )


@router.post("/play/wake_up")
async def play_wake_up(backend: Backend = Depends(get_backend)) -> MoveUUID:
    """Trigger the wake-up named pose + sound."""
    return create_move_task(backend.wake_up())


@router.post("/play/goto_sleep")
async def play_goto_sleep(backend: Backend = Depends(get_backend)) -> MoveUUID:
    """Trigger the sleep named pose + sound."""
    return create_move_task(backend.goto_sleep())


@router.get("/recorded-move-datasets/list/{dataset_name:path}")
async def list_recorded_move_dataset(dataset_name: str) -> list[str]:
    """List available recorded moves in a dataset."""
    try:
        moves = RecordedMoves(dataset_name)
    except NotExistError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return moves.list_moves()


@router.post("/play/recorded-move-dataset/{dataset_name:path}/{move_name}")
async def play_recorded_move_dataset(
    dataset_name: str,
    move_name: str,
    backend: Backend = Depends(get_backend),
) -> MoveUUID:
    """Play a recorded move from a ModelScope dataset."""
    try:
        recorded_moves = RecordedMoves(dataset_name)
    except NotExistError as e:
        raise HTTPException(status_code=404, detail=str(e))
    try:
        move = recorded_moves.get(move_name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return create_move_task(backend.play_move(move))


@router.post("/stop")
async def stop_move(uuid: MoveUUID) -> dict[str, str]:
    """Stop a running move task."""
    return await stop_move_task(uuid.uuid)


@router.websocket("/ws/updates")
async def ws_move_updates(websocket: WebSocket) -> None:
    """Stream move updates to listeners."""
    await websocket.accept()
    try:
        move_listeners.append(websocket)
        while True:
            _ = await websocket.receive_text()
    except WebSocketDisconnect:
        move_listeners.remove(websocket)


# --- FullBodyTarget streaming and single set_target ---
@router.post("/set_target")
async def set_target(
    target: FullBodyTarget,
    backend: Backend = Depends(get_backend),
) -> dict[str, str]:
    """Apply per-subsystem joint targets immediately (no interpolation)."""
    if backend.is_move_running:
        backend.logger.warning("Ignoring set_target request: move already running.")
        return {"status": "ignored", "reason": "move_running"}
    backend.set_target(
        neck=np.array(target.target_neck) if target.target_neck else None,
        left_arm=np.array(target.target_left_arm) if target.target_left_arm else None,
        right_arm=np.array(target.target_right_arm) if target.target_right_arm else None,
        nose=np.array(target.target_nose) if target.target_nose else None,
    )
    return {"status": "ok"}


@router.websocket("/ws/set_target")
async def ws_set_target(
    websocket: WebSocket, backend: Backend = Depends(ws_get_backend)
) -> None:
    """Stream :class:`FullBodyTarget` updates to the daemon."""
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            try:
                target = FullBodyTarget.model_validate_json(data)
                await set_target(target, backend)
            except Exception as e:
                await websocket.send_text(
                    json.dumps({"status": "error", "detail": str(e)})
                )
    except WebSocketDisconnect:
        pass


@router.websocket("/ws/raw/write")
async def write(
    websocket: WebSocket,
    backend: Backend = Depends(ws_get_backend),
) -> None:
    """Forward raw packets to the motor controller and stream back its responses."""
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_bytes()
            raw_response_packet: bytes = backend.write_raw_packet(data)
            await websocket.send_bytes(raw_response_packet)
    except WebSocketDisconnect:
        pass
