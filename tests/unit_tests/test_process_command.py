"""Tests for Backend.process_command, the transport-agnostic command dispatcher."""

import asyncio
import json
from typing import Any, Callable

import numpy as np
import pytest

from dreambo_torso.daemon.backend.mockup_sim.backend import MockupSimBackend
from dreambo_torso.io.protocol import GotoTargetCmd


def _make_backend() -> MockupSimBackend:
    """Build a lightweight backend with audio disabled."""
    return MockupSimBackend(use_audio=False)


def _patch_async_goto(backend: MockupSimBackend) -> dict[str, Any]:
    """Replace ``_async_goto`` with a spy that records call arguments."""
    captured: dict[str, Any] = {}

    async def fake_async_goto(
        send_response: Callable[[dict[str, Any]], None],
        neck: Any,
        left_arm: Any,
        right_arm: Any,
        nose: Any,
        duration: float,
    ) -> None:
        captured["neck"] = neck
        captured["left_arm"] = left_arm
        captured["right_arm"] = right_arm
        captured["nose"] = nose
        captured["duration"] = duration
        send_response({"status": "ok", "command": "goto_target", "completed": True})

    backend._async_goto = fake_async_goto  # type: ignore[assignment]
    return captured


@pytest.mark.asyncio
async def test_goto_target_dispatches_per_subsystem() -> None:
    """A GotoTargetCmd with several channels must reach goto_target intact."""
    backend = _make_backend()
    captured = _patch_async_goto(backend)

    cmd = GotoTargetCmd(
        neck=[0.0, 0.3, 0.0],
        left_arm=[0.1, 0.2],
        duration=0.5,
    )
    backend.process_command(cmd, send_response=lambda _: None)
    await asyncio.sleep(0)

    np.testing.assert_array_equal(captured["neck"], np.array([0.0, 0.3, 0.0]))
    np.testing.assert_array_equal(captured["left_arm"], np.array([0.1, 0.2]))
    assert captured["right_arm"] is None
    assert captured["nose"] is None
    assert captured["duration"] == 0.5


@pytest.mark.asyncio
async def test_goto_target_via_webrtc_json_message() -> None:
    """Full WebRTC entry path: JSON in, parsed cmd through process_command."""
    backend = _make_backend()
    captured = _patch_async_goto(backend)

    message = json.dumps(
        {
            "type": "goto_target",
            "neck": [0.0, 0.4, 0.0],
            "duration": 0.5,
        }
    )

    backend._handle_webrtc_message(peer_id="test-peer", message=message)
    await asyncio.sleep(0)

    np.testing.assert_array_equal(captured["neck"], np.array([0.0, 0.4, 0.0]))
    assert captured["left_arm"] is None
    assert captured["right_arm"] is None
    assert captured["nose"] is None
