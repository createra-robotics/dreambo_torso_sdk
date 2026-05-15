"""Integration tests for the daemon + SDK against the mockup-sim backend."""

import asyncio
import threading

import numpy as np
import pytest
import uvicorn

from dreambo_torso.daemon.app.main import Args, create_app
from dreambo_torso.daemon.daemon import Daemon
from dreambo_torso.dreambo_torso import Dreambo


async def _start_app_server(
    **daemon_kwargs: object,
) -> tuple[Daemon, uvicorn.Server, threading.Thread, int]:
    """Start a full FastAPI + daemon server in a background thread."""
    args = Args(
        mockup_sim=True,
        wake_up_on_start=False,
        no_media=True,
        autostart=True,
        fastapi_port=0,  # let OS pick a free port
    )

    app = create_app(args)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    while not server.started:
        await asyncio.sleep(0.05)

    sockets = server.servers[0].sockets
    port: int = sockets[0].getsockname()[1]

    return app.state.daemon, server, thread, port


async def _stop_app_server(server: uvicorn.Server, thread: threading.Thread) -> None:
    """Gracefully shut down the uvicorn server."""
    server.should_exit = True
    thread.join(timeout=10)


@pytest.mark.asyncio
async def test_daemon_start_stop() -> None:
    daemon, server, thread, _port = await _start_app_server()
    await daemon.stop(goto_sleep_on_stop=False)
    await _stop_app_server(server, thread)


@pytest.mark.asyncio
async def test_daemon_multiple_start_stop() -> None:
    daemon, server, thread, _port = await _start_app_server()
    await daemon.stop(goto_sleep_on_stop=False)
    await _stop_app_server(server, thread)

    daemon2, server2, thread2, _port2 = await _start_app_server()
    await daemon2.stop(goto_sleep_on_stop=False)
    await _stop_app_server(server2, thread2)


@pytest.mark.asyncio
async def test_daemon_client_disconnection() -> None:
    daemon, server, thread, port = await _start_app_server()

    client_connected = asyncio.Event()

    async def simple_client() -> None:
        with Dreambo(host="localhost", port=port, media_backend="no_media") as mini:
            status = mini.client.get_status()
            assert status.state == "running"
            assert status.error is None
            assert status.backend_status is not None
            assert status.backend_status.motor_control_mode == "enabled"
            assert status.backend_status.error is None
            client_connected.set()

    async def wait_for_client() -> None:
        await client_connected.wait()
        await daemon.stop(goto_sleep_on_stop=False)
        await _stop_app_server(server, thread)

    await asyncio.gather(simple_client(), wait_for_client())


@pytest.mark.asyncio
async def test_multi_robot_isolation() -> None:
    """Two daemons on different ports must be fully independent.

    A neck command to robot 1 must not move robot 2.
    """
    daemon1, server1, thread1, port1 = await _start_app_server()
    daemon2, server2, thread2, port2 = await _start_app_server()

    try:
        with (
            Dreambo(host="localhost", port=port1, media_backend="no_media") as mini1,
            Dreambo(host="localhost", port=port2, media_backend="no_media") as mini2,
        ):
            assert mini1.client.get_status().state == "running"
            assert mini2.client.get_status().state == "running"

            neck1_before = mini1.get_current_neck_joints()
            neck2_before = mini2.get_current_neck_joints()

            mini1.set_neck([0.3, 0.2, 0.1])
            await asyncio.sleep(0.5)

            neck1_after = mini1.get_current_neck_joints()
            neck2_after = mini2.get_current_neck_joints()

            delta1 = np.max(np.abs(np.array(neck1_after) - np.array(neck1_before)))
            assert delta1 > 0.05, (
                f"Robot 1 neck did not move after command (max delta={delta1})"
            )

            delta2 = np.max(np.abs(np.array(neck2_after) - np.array(neck2_before)))
            assert delta2 < 0.01, (
                f"Robot 2 neck moved after commanding robot 1 (max delta={delta2})"
            )

    finally:
        await daemon1.stop(goto_sleep_on_stop=False)
        await daemon2.stop(goto_sleep_on_stop=False)
        await _stop_app_server(server1, thread1)
        await _stop_app_server(server2, thread2)
