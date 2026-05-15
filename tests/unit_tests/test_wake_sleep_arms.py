"""Verify that wake_up / goto_sleep visibly move the arms.

Against mockup_sim, each named-pose goto is mirrored into present joint
state on the next control-loop tick. So polling the SDK's
``get_current_left_arm_joints`` / ``get_current_right_arm_joints`` before
and after wake_up (and after goto_sleep) must show non-zero deltas on
both arms.
"""

import asyncio
import threading

import numpy as np
import pytest
import uvicorn

from dreambo_torso.daemon.app.main import Args, create_app
from dreambo_torso.dreambo_torso import Dreambo


async def _start_server() -> tuple[uvicorn.Server, threading.Thread, int]:
    args = Args(
        mockup_sim=True,
        wake_up_on_start=False,  # we'll trigger wake_up manually
        no_media=True,
        autostart=True,
        fastapi_port=0,
    )
    app = create_app(args)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        await asyncio.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    return server, thread, port


async def _stop_server(server: uvicorn.Server, thread: threading.Thread) -> None:
    server.should_exit = True
    thread.join(timeout=10)


@pytest.mark.asyncio
async def test_arms_move_during_wake_and_sleep() -> None:
    server, thread, port = await _start_server()
    try:
        with Dreambo(host="localhost", port=port, media_backend="no_media") as mini:
            # Baseline (mockup_sim seeds itself at the 'sleep' pose).
            left_before = np.array(mini.get_current_left_arm_joints())
            right_before = np.array(mini.get_current_right_arm_joints())

            mini.wake_up()
            await asyncio.sleep(2.5)  # wake_up's goto + sound pause

            left_after_wake = np.array(mini.get_current_left_arm_joints())
            right_after_wake = np.array(mini.get_current_right_arm_joints())

            assert np.linalg.norm(left_after_wake - left_before) > 0.1, (
                f"Left arm didn't move during wake_up "
                f"(before={left_before}, after={left_after_wake})"
            )
            assert np.linalg.norm(right_after_wake - right_before) > 0.1, (
                f"Right arm didn't move during wake_up "
                f"(before={right_before}, after={right_after_wake})"
            )

            mini.goto_sleep()
            await asyncio.sleep(3.5)  # goto_sleep duration + tail

            left_after_sleep = np.array(mini.get_current_left_arm_joints())
            right_after_sleep = np.array(mini.get_current_right_arm_joints())

            assert np.linalg.norm(left_after_sleep - left_after_wake) > 0.1, (
                f"Left arm didn't move during goto_sleep "
                f"(after_wake={left_after_wake}, after_sleep={left_after_sleep})"
            )
            assert np.linalg.norm(right_after_sleep - right_after_wake) > 0.1, (
                f"Right arm didn't move during goto_sleep "
                f"(after_wake={right_after_wake}, after_sleep={right_after_sleep})"
            )
    finally:
        await _stop_server(server, thread)
