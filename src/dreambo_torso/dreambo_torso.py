"""High-level SDK class for the Dreambo torso.

The new torso exposes four joint-space subsystems — neck, left_arm,
right_arm, nose — plus media (camera, microphone, sound) and recording.
There is no head pose, no antennas, no body_yaw, and no Stewart platform.
"""

import asyncio
import logging
import time
import warnings
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Dict, List, Literal, Optional, cast

import numpy as np
import numpy.typing as npt
from asgiref.sync import async_to_sync
from dreambo_torso_kinematics import DreamboArmKinematics

from dreambo_torso.daemon.utils import daemon_check, is_local_camera_available
from dreambo_torso.io.protocol import (
    AppendRecordCmd,
    ArmSide,
    DaemonStatus,
    GotoTaskRequest,
    SetArmCmd,
    SetFullTargetCmd,
    SetNeckCmd,
    SetNoseCmd,
    SetTorqueCmd,
    StartRecordingCmd,
    StopRecordingCmd,
)
from dreambo_torso.io.ws_client import WSClient
from dreambo_torso.media.media_manager import MediaBackend, MediaManager
from dreambo_torso.motion.move import JointTargets, Move
from dreambo_torso.utils.interpolation import InterpolationTechnique

ConnectionMode = Literal["auto", "localhost_only", "network"]


def _as_list(
    value: Optional[npt.NDArray[np.float64] | List[float]],
) -> Optional[List[float]]:
    """Coerce *value* to a Python list of floats, or pass through None."""
    if value is None:
        return None
    return list(np.asarray(value, dtype=np.float64).reshape(-1))


class Dreambo:
    """Client for the Dreambo torso daemon.

    Drives the four joint-space subsystems and exposes media (camera,
    microphone, sound) plus recording. The arm subsystems also accept a
    higher-level pointing-direction API (``set_arm_direction`` /
    ``goto_arm_direction``) that resolves to motor pairs via the
    spherical 5-bar IK from ``dreambo_torso_kinematics``.
    """

    def __init__(
        self,
        robot_name: str = "dreambo_torso",
        host: str = "dreambo_torso.local",
        port: int = 8000,
        connection_mode: ConnectionMode = "auto",
        spawn_daemon: bool = False,
        use_sim: bool = False,
        timeout: float = 5.0,
        log_level: str = "INFO",
        media_backend: str = "default",
        localhost_only: Optional[bool] = None,
    ) -> None:
        """Connect to the daemon and prepare the media manager."""
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(log_level)
        self.robot_name = robot_name
        self.host = host
        self.port = port
        daemon_check(spawn_daemon, use_sim)
        normalized_mode = self._normalize_connection_mode(
            connection_mode, localhost_only
        )
        self.client, self.connection_mode = self._initialize_client(
            normalized_mode, timeout
        )
        self._daemon_http_url = f"http://{self.client.host}:{self.client.port}"
        self.is_recording = False
        self._move_cancelled = False
        self._media_released = False
        self._log_level = log_level
        self._media_backend = media_backend
        self._arm_kin: Dict[str, DreamboArmKinematics] = {}
        self.media_manager = self._configure_mediamanager(media_backend, log_level)

    def __del__(self) -> None:
        """Disconnect the underlying WebSocket client."""
        if hasattr(self, "client"):
            self.client.disconnect()

    def __enter__(self) -> "Dreambo":
        """Enter the runtime context (no-op; provided for ergonomics)."""
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:  # type: ignore[no-untyped-def]
        """Leave the runtime context, re-acquiring media if needed and disconnecting."""
        if self._media_released:
            self.acquire_media()
        self.media_manager.close()
        self.client.disconnect()

    # ------------------------------------------------------------------
    # Media plumbing
    # ------------------------------------------------------------------

    @property
    def media(self) -> MediaManager:
        """The :class:`MediaManager` (camera + microphone + audio playback)."""
        return self.media_manager

    @property
    def media_released(self) -> bool:
        """Whether the daemon's media hardware has been released for direct access."""
        return self._media_released

    def release_media(self) -> None:
        """Hand camera/audio hardware over to direct (non-daemon) clients."""
        if self._media_released:
            return
        self.client.release_media()
        if hasattr(self, "media_manager"):
            self.media_manager.close()
        self._media_released = True
        self.logger.info("Media released — camera/mic available for direct access.")

    def acquire_media(self) -> None:
        """Re-acquire camera/audio hardware via the daemon."""
        if not self._media_released:
            return
        if not self.client.acquire_media():
            self.logger.error("Failed to re-acquire media on daemon.")
            return
        self.media_manager.close()
        self.media_manager = self._configure_mediamanager(
            self._media_backend, self._log_level
        )
        self._media_released = False
        self.logger.info("Media re-acquired by daemon.")

    @property
    def imu(self) -> Dict[str, List[float] | float] | None:
        """The latest cached IMU sample, or None if no IMU is wired up."""
        imu_msg = self.client.get_current_imu_data()
        if imu_msg is None:
            return None
        return imu_msg.model_dump(exclude={"type"})

    def _configure_mediamanager(
        self, media_backend: str, log_level: str
    ) -> MediaManager:
        """Pick a :class:`MediaBackend` and return a configured :class:`MediaManager`."""
        daemon_status = self.client.get_status()
        self._warn_if_daemon_version_mismatch(daemon_status)

        specs_name = getattr(daemon_status, "camera_specs_name", "")
        from dreambo_torso.media.camera_constants import get_camera_specs_by_name

        camera_specs = get_camera_specs_by_name(specs_name) if specs_name else None

        if media_backend.lower() == "no_media":
            self.logger.info("No media backend requested by user.")
            if (
                not getattr(daemon_status, "no_media", False)
                and not self._media_released
            ):
                self.release_media()
            mbackend = MediaBackend.NO_MEDIA
        elif getattr(daemon_status, "no_media", False):
            self.logger.info(
                "Daemon reports no_media=True — skipping media initialisation."
            )
            mbackend = MediaBackend.NO_MEDIA
        elif media_backend.lower() in ("default", "auto"):
            if self.connection_mode == "localhost_only" and is_local_camera_available():
                self.logger.info(
                    "Auto-detected local IPC endpoint. Using LOCAL backend."
                )
                mbackend = MediaBackend.LOCAL
            else:
                self.logger.info(
                    "No local IPC endpoint. Using WebRTC backend for streaming."
                )
                mbackend = MediaBackend.WEBRTC
        else:
            try:
                mbackend = MediaBackend(media_backend.lower())
            except ValueError:
                self.logger.warning(
                    f"Unknown media backend '{media_backend}', falling back to auto-detect."
                )
                if (
                    self.connection_mode == "localhost_only"
                    and is_local_camera_available()
                ):
                    mbackend = MediaBackend.LOCAL
                else:
                    mbackend = MediaBackend.WEBRTC

        return MediaManager(
            backend=mbackend,
            log_level=log_level,
            signalling_host=daemon_status.wlan_ip or "localhost",
            camera_specs=camera_specs,
            daemon_url=self._daemon_http_url,
        )

    @staticmethod
    def _get_sdk_version() -> str | None:
        try:
            return version("dreambo_torso")
        except PackageNotFoundError:
            return None

    def _warn_if_daemon_version_mismatch(self, daemon_status: DaemonStatus) -> None:
        sdk_version = self._get_sdk_version()
        daemon_version = daemon_status.version
        if sdk_version is None or daemon_version is None:
            return
        if sdk_version.strip() == daemon_version.strip():
            return
        warnings.warn(
            f"Dreambo SDK and daemon versions do not match: "
            f"SDK={sdk_version}, daemon={daemon_version}.",
            RuntimeWarning,
            stacklevel=3,
        )

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    def _normalize_connection_mode(
        self,
        connection_mode: ConnectionMode,
        legacy_localhost_only: Optional[bool],
    ) -> ConnectionMode:
        normalized = connection_mode.lower()
        if normalized not in {"auto", "localhost_only", "network"}:
            raise ValueError(
                "Invalid connection_mode. Use 'auto', 'localhost_only', or 'network'."
            )
        resolved = cast(ConnectionMode, normalized)
        if legacy_localhost_only is None:
            return resolved
        self.logger.warning(
            "The 'localhost_only' argument is deprecated; switch to connection_mode."
        )
        if resolved != "auto":
            return resolved
        return "localhost_only" if legacy_localhost_only else "network"

    def _initialize_client(
        self, requested_mode: ConnectionMode, timeout: float
    ) -> tuple[WSClient, ConnectionMode]:
        requested_mode = cast(ConnectionMode, requested_mode.lower())
        if requested_mode == "auto":
            try:
                client = self._connect_single(
                    host="localhost", port=self.port, timeout=timeout
                )
                selected: ConnectionMode = "localhost_only"
            except Exception as err:
                self.logger.info(
                    "Auto connection: localhost attempt failed (%s). Trying %s.",
                    err,
                    self.host,
                )
                try:
                    client = self._connect_single(
                        host=self.host, port=self.port, timeout=timeout
                    )
                except (ConnectionError, TimeoutError):
                    raise ConnectionError(
                        "Auto connection: both localhost and remote attempts failed."
                    )
                selected = "network"
            self.logger.info("Connection mode selected: %s", selected)
            return client, selected

        if requested_mode == "localhost_only":
            try:
                client = self._connect_single(
                    host="localhost", port=self.port, timeout=timeout
                )
            except (ConnectionError, TimeoutError):
                raise ConnectionError(
                    "Could not connect to daemon on localhost. Is the Dreambo daemon running?"
                )
            selected = "localhost_only"
        else:
            try:
                client = self._connect_single(
                    host=self.host, port=self.port, timeout=timeout
                )
            except (ConnectionError, TimeoutError):
                raise ConnectionError("Network connection attempt failed.")
            selected = "network"

        self.logger.info("Connection mode selected: %s", selected)
        return client, selected

    def _connect_single(self, host: str, port: int, timeout: float) -> WSClient:
        client = WSClient(host, port)
        client.wait_for_connection(timeout=timeout)
        return client

    # ------------------------------------------------------------------
    # Subsystem commands
    # ------------------------------------------------------------------

    def set_neck(self, joints: npt.NDArray[np.float64] | List[float]) -> None:
        """Set the target neck joint positions [yaw, pitch, roll] (radians)."""
        joints_list = _as_list(joints)
        assert joints_list is not None and len(joints_list) == 3, (
            f"Neck joints must have length 3, got {joints_list}."
        )
        self.client.send_command(SetNeckCmd(joints=joints_list))
        self._record({"time": time.time(), "neck": joints_list})

    def set_arm(
        self,
        side: Literal["left", "right"],
        joints: npt.NDArray[np.float64] | List[float],
    ) -> None:
        """Set the target joint positions of one arm [theta_a, theta_b] (radians)."""
        joints_list = _as_list(joints)
        assert joints_list is not None and len(joints_list) == 2, (
            f"Arm joints must have length 2, got {joints_list}."
        )
        self.client.send_command(SetArmCmd(side=ArmSide(side), joints=joints_list))
        self._record({"time": time.time(), f"{side}_arm": joints_list})

    def _arm_kinematics(self, side: Literal["left", "right"]) -> DreamboArmKinematics:
        """Return (and lazily cache) the kinematics object for *side*."""
        if side not in self._arm_kin:
            self._arm_kin[side] = (
                DreamboArmKinematics.default_left()
                if side == "left"
                else DreamboArmKinematics.default_right()
            )
        return self._arm_kin[side]

    def _resolve_arm_direction(
        self,
        side: Literal["left", "right"],
        direction: npt.NDArray[np.float64] | List[float],
    ) -> List[float]:
        """Resolve a shoulder-local pointing direction to ``[theta_a, theta_b]``.

        The branch closest to the current arm state is selected. Raises
        ``RuntimeError`` (via the kinematics crate) if the direction is
        outside the reachable workspace.
        """
        dir_list = _as_list(direction)
        assert dir_list is not None and len(dir_list) == 3, (
            f"Arm direction must be a 3-vector, got {dir_list}."
        )
        near = tuple(self.get_current_joints()[f"{side}_arm"])
        theta_a, theta_b = self._arm_kinematics(side).ik_from_direction(
            dir_list, near=near
        )
        return [theta_a, theta_b]

    def set_arm_direction(
        self,
        side: Literal["left", "right"],
        direction: npt.NDArray[np.float64] | List[float],
    ) -> None:
        """Point the arm along *direction* (shoulder-local 3-vector).

        Same vector for both arms — the mirror flag on the right-arm
        geometry handles symmetry. IK picks the ``(theta_a, theta_b)``
        branch closest to the current arm state and the SDK then drives
        both servos together via ``set_arm``.
        """
        self.set_arm(side, self._resolve_arm_direction(side, direction))

    def goto_arm_direction(
        self,
        side: Literal["left", "right"],
        direction: npt.NDArray[np.float64] | List[float],
        duration: float = 0.5,
        method: InterpolationTechnique = InterpolationTechnique.MIN_JERK,
    ) -> None:
        """Smoothly move the arm to point along *direction*."""
        joints = self._resolve_arm_direction(side, direction)
        kwargs: Dict[str, Any] = {f"{side}_arm": joints}
        self.goto_target(duration=duration, method=method, **kwargs)

    def get_arm_direction(self, side: Literal["left", "right"]) -> List[float]:
        """Return the arm's current pointing direction (shoulder-local 3-vector)."""
        theta_a, theta_b = self.get_current_joints()[f"{side}_arm"]
        return list(self._arm_kinematics(side).direction(theta_a, theta_b))

    def set_nose(self, joints: npt.NDArray[np.float64] | List[float]) -> None:
        """Set the target nose joint positions [top, left, right] (radians)."""
        joints_list = _as_list(joints)
        assert joints_list is not None and len(joints_list) == 3, (
            f"Nose joints must have length 3, got {joints_list}."
        )
        self.client.send_command(SetNoseCmd(joints=joints_list))
        self._record({"time": time.time(), "nose": joints_list})

    def set_target(
        self,
        neck: Optional[npt.NDArray[np.float64] | List[float]] = None,
        left_arm: Optional[npt.NDArray[np.float64] | List[float]] = None,
        right_arm: Optional[npt.NDArray[np.float64] | List[float]] = None,
        nose: Optional[npt.NDArray[np.float64] | List[float]] = None,
    ) -> None:
        """Apply any subset of subsystem targets in a single message."""
        neck_list = _as_list(neck)
        left_list = _as_list(left_arm)
        right_list = _as_list(right_arm)
        nose_list = _as_list(nose)

        if all(v is None for v in (neck_list, left_list, right_list, nose_list)):
            raise ValueError(
                "At least one of neck, left_arm, right_arm or nose must be provided."
            )

        self.client.send_command(
            SetFullTargetCmd(
                neck=neck_list,
                left_arm=left_list,
                right_arm=right_list,
                nose=nose_list,
            )
        )

        record: Dict[str, Any] = {"time": time.time()}
        if neck_list is not None:
            record["neck"] = neck_list
        if left_list is not None:
            record["left_arm"] = left_list
        if right_list is not None:
            record["right_arm"] = right_list
        if nose_list is not None:
            record["nose"] = nose_list
        self._record(record)

    def goto_target(
        self,
        neck: Optional[npt.NDArray[np.float64] | List[float]] = None,
        left_arm: Optional[npt.NDArray[np.float64] | List[float]] = None,
        right_arm: Optional[npt.NDArray[np.float64] | List[float]] = None,
        nose: Optional[npt.NDArray[np.float64] | List[float]] = None,
        duration: float = 0.5,
        method: InterpolationTechnique = InterpolationTechnique.MIN_JERK,
    ) -> None:
        """Smoothly interpolate any subset of subsystems to the given targets."""
        if all(v is None for v in (neck, left_arm, right_arm, nose)):
            raise ValueError(
                "At least one of neck, left_arm, right_arm or nose must be provided."
            )
        if duration <= 0.0:
            raise ValueError(
                "Duration must be positive. Use set_target() for immediate moves."
            )

        req = GotoTaskRequest(
            neck=_as_list(neck),
            left_arm=_as_list(left_arm),
            right_arm=_as_list(right_arm),
            nose=_as_list(nose),
            duration=duration,
            method=method,
        )
        task_uid = self.client.send_task_request(req)
        self.client.wait_for_task_completion(task_uid, timeout=duration + 1.0)

    # ------------------------------------------------------------------
    # Wake / sleep — delegated to the daemon's named poses
    # ------------------------------------------------------------------

    def wake_up(self) -> None:
        """Run the daemon's 'wake' named pose + wake_up.wav."""
        from dreambo_torso.io.protocol import WakeUpCmd

        self.client.send_command(WakeUpCmd())

    def goto_sleep(self) -> None:
        """Run the daemon's 'sleep' named pose + go_sleep.wav."""
        from dreambo_torso.io.protocol import GotoSleepCmd

        self.client.send_command(GotoSleepCmd())

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def get_current_joints(self) -> Dict[str, List[float]]:
        """Return a snapshot of every subsystem's present joint positions."""
        msg = self.client.get_current_joints()
        return {
            "neck": list(msg.neck),
            "left_arm": list(msg.left_arm),
            "right_arm": list(msg.right_arm),
            "nose": list(msg.nose),
        }

    def get_current_neck_joints(self) -> List[float]:
        """Return the latest neck joint positions [yaw, pitch, roll]."""
        return list(self.client.get_current_joints().neck)

    def get_current_left_arm_joints(self) -> List[float]:
        """Return the latest left-arm joint positions [theta_a, theta_b]."""
        return list(self.client.get_current_joints().left_arm)

    def get_current_right_arm_joints(self) -> List[float]:
        """Return the latest right-arm joint positions [theta_a, theta_b]."""
        return list(self.client.get_current_joints().right_arm)

    def get_current_nose_joints(self) -> List[float]:
        """Return the latest nose joint positions [top, left, right]."""
        return list(self.client.get_current_joints().nose)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def start_recording(self) -> None:
        """Begin a recording on the daemon."""
        self.client.send_command(StartRecordingCmd())
        self.is_recording = True

    def stop_recording(
        self,
    ) -> Optional[List[Dict[str, Any]]]:
        """End the recording and return the buffered data, if any."""
        self.client.send_command(StopRecordingCmd())
        self.is_recording = False
        if not self.client.wait_for_recorded_data(timeout=5):
            raise RuntimeError("Daemon did not provide recorded data in time!")
        return self.client.get_recorded_data(wait=False)

    def _record(self, record: Dict[str, Any]) -> None:
        """Append a record to the in-flight recording buffer (no-op when idle)."""
        if not self.is_recording:
            return
        self.client.send_command(AppendRecordCmd(record=record))

    # ------------------------------------------------------------------
    # Motor torque
    # ------------------------------------------------------------------

    def enable_motors(self, ids: List[str] | None = None) -> None:
        """Enable motor torque (optionally only on specific motor names)."""
        self.client.send_command(SetTorqueCmd(on=True, ids=ids))

    def disable_motors(self, ids: List[str] | None = None) -> None:
        """Disable motor torque (optionally only on specific motor names)."""
        self.client.send_command(SetTorqueCmd(on=False, ids=ids))

    # ------------------------------------------------------------------
    # Move playback
    # ------------------------------------------------------------------

    def cancel_move(self) -> None:
        """Cancel the currently playing :meth:`play_move`."""
        self._move_cancelled = True
        self.media_manager.stop_playing()
        self.logger.info("Move cancellation requested")

    async def async_play_move(
        self,
        move: Move,
        play_frequency: float = 100.0,
        initial_goto_duration: float = 0.0,
        sound: bool = True,
    ) -> None:
        """Asynchronously play a :class:`Move` (per-subsystem joint trajectories)."""
        self._move_cancelled = False

        if initial_goto_duration > 0.0:
            start_targets: JointTargets = move.evaluate(0.0)
            self.goto_target(
                neck=start_targets.neck,
                left_arm=start_targets.left_arm,
                right_arm=start_targets.right_arm,
                nose=start_targets.nose,
                duration=initial_goto_duration,
            )

        sleep_period = 1.0 / play_frequency

        if move.sound_path is not None and sound:
            self.media_manager.play_sound(str(move.sound_path))

        t0 = time.time()
        while time.time() - t0 < move.duration:
            if self._move_cancelled:
                self.logger.info("Move cancelled, stopping playback")
                break

            t = min(time.time() - t0, move.duration - 1e-2)
            targets = move.evaluate(t)

            if targets.neck is not None:
                self.set_neck(targets.neck)
            if targets.left_arm is not None:
                self.set_arm("left", targets.left_arm)
            if targets.right_arm is not None:
                self.set_arm("right", targets.right_arm)
            if targets.nose is not None:
                self.set_nose(targets.nose)

            elapsed = time.time() - t0 - t
            if elapsed < sleep_period:
                await asyncio.sleep(sleep_period - elapsed)
            else:
                await asyncio.sleep(0.001)

    play_move = async_to_sync(async_play_move)
