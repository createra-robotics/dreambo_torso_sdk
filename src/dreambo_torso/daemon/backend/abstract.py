"""Base class for Dreambo torso backends (simulated or real).

The new torso has four subsystems, each commanded in joint space:

- ``neck``      (3 DOF): yaw, pitch, roll. DM motors over CAN.
- ``left_arm``  (2 DOF): theta_a, theta_b. Spherical 5-bar shoulder.
- ``right_arm`` (2 DOF): theta_a, theta_b. Spherical 5-bar shoulder.
- ``nose``      (3 DOF): top, left, right.

The :class:`Backend` here owns target/present state per subsystem and
implements transport-agnostic command dispatch (WebSocket / WebRTC).
Subclasses implement the actual control loop and motor I/O.
"""

import asyncio
import json
import logging
import threading
import time
from abc import abstractmethod
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Any, Callable, Optional

import numpy as np
from numpy.typing import NDArray

import dreambo_torso
from dreambo_torso.io.protocol import (
    AnyCommand,
    AppendRecordCmd,
    ArmSide,
    GetMicrophoneVolumeCmd,
    GetMotorModeCmd,
    GetStateCmd,
    GetVersionCmd,
    GetVolumeCmd,
    GotoSleepCmd,
    GotoTargetCmd,
    MockupSimBackendStatus,
    MotorControlMode,
    MujocoBackendStatus,
    PlaySoundCmd,
    RecordedDataMsg,
    RobotBackendStatus,
    SetArmCmd,
    SetFullTargetCmd,
    SetMicrophoneVolumeCmd,
    SetMotorModeCmd,
    SetNeckCmd,
    SetNoseCmd,
    SetTorqueCmd,
    SetVolumeCmd,
    StartRecordingCmd,
    StopRecordingCmd,
    WakeUpCmd,
    command_adapter,
)
from dreambo_torso.io.publisher import Publisher
from dreambo_torso.media.audio_doa import AudioDoA
from dreambo_torso.motion.goto import GotoMove
from dreambo_torso.motion.move import JointTargets, Move
from dreambo_torso.motion.named_poses import NamedPose, NamedPoses
from dreambo_torso.utils.constants import URDF_ROOT_PATH
from dreambo_torso.utils.interpolation import InterpolationTechnique

# Joint counts per subsystem.
NECK_DOF = 3
ARM_DOF = 2
NOSE_DOF = 3


def _named_poses_path() -> Path:
    """Locate the bundled named_poses.yaml file."""
    return Path(str(files(dreambo_torso).joinpath("assets/config/named_poses.yaml")))


class Backend:
    """Base class for Dreambo torso backends, simulated or real."""

    def __init__(
        self,
        log_level: str = "INFO",
        use_audio: bool = True,
        wireless_version: bool = False,
    ) -> None:
        """Initialize the backend's state and concurrency primitives."""
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(log_level)
        self.use_audio = use_audio
        self.doa = AudioDoA() if use_audio else None
        self.should_stop = threading.Event()
        self.ready = threading.Event()

        # Present (sensed) joint positions per subsystem. Filled by the
        # subclass control loop on every tick.
        self.current_neck_joint_positions: (
            Annotated[NDArray[np.float64], (NECK_DOF,)] | None
        ) = None
        self.current_left_arm_joint_positions: (
            Annotated[NDArray[np.float64], (ARM_DOF,)] | None
        ) = None
        self.current_right_arm_joint_positions: (
            Annotated[NDArray[np.float64], (ARM_DOF,)] | None
        ) = None
        self.current_nose_joint_positions: (
            Annotated[NDArray[np.float64], (NOSE_DOF,)] | None
        ) = None

        # Target joint positions per subsystem. ``None`` means "leave alone".
        self.target_neck_joint_positions: (
            Annotated[NDArray[np.float64], (NECK_DOF,)] | None
        ) = None
        self.target_left_arm_joint_positions: (
            Annotated[NDArray[np.float64], (ARM_DOF,)] | None
        ) = None
        self.target_right_arm_joint_positions: (
            Annotated[NDArray[np.float64], (ARM_DOF,)] | None
        ) = None
        self.target_nose_joint_positions: (
            Annotated[NDArray[np.float64], (NOSE_DOF,)] | None
        ) = None

        self.joint_positions_publisher: Publisher | None = None
        self.recording_publisher: Publisher | None = None
        self.imu_publisher: Publisher | None = None
        self.error: str | None = None
        self.is_recording = False
        self.recorded_data: list[dict[str, Any]] = []

        self.is_shutting_down = False

        # Recording lock to guard buffer swaps and appends.
        self._rec_lock = threading.Lock()

        # Reference to the media server for play_sound delegation.
        self._media_server: Optional[Any] = None

        # Guard so a play_move and a goto don't trample each other.
        self._play_move_lock = threading.RLock()
        self._active_move_depth = 0

        # WebRTC support
        self._send_message_to_webrtc: Optional[Callable[[Optional[str], str], None]] = (
            None
        )

        # Named poses (init / wake / sleep / ...). Loaded lazily on first use.
        self._named_poses: NamedPoses | None = None

    # ------------------------------------------------------------------
    # Life cycle
    # ------------------------------------------------------------------

    def wrapped_run(self) -> None:
        """Run :meth:`run` in a try/except, storing any error before re-raising."""
        try:
            self.run()
        except Exception as e:
            self.error = str(e)
            self.close()
            raise

    def run(self) -> None:
        """Run the backend control loop. Subclasses override this."""
        raise NotImplementedError("Backend.run() must be overridden by subclasses.")

    def close(self) -> None:
        """Release shared resources. Subclasses extend with their own cleanup."""
        self.logger.debug("Backend.close() - cleaning up resources")
        self._media_server = None

    @property
    def is_move_running(self) -> bool:
        """Whether a play_move / goto is currently executing."""
        return self._active_move_depth > 0

    def _try_start_move(self) -> bool:
        """Attempt to grab the move guard non-blockingly; True iff acquired."""
        if not self._play_move_lock.acquire(blocking=False):
            return False
        self._active_move_depth += 1
        return True

    def _end_move(self) -> None:
        """Release the move guard. Pair with every successful :meth:`_try_start_move`."""
        if self._active_move_depth > 0:
            self._active_move_depth -= 1
        self._play_move_lock.release()

    def get_status(
        self,
    ) -> "RobotBackendStatus | MujocoBackendStatus | MockupSimBackendStatus":
        """Return backend status. Subclasses override this."""
        raise NotImplementedError(
            "Backend.get_status() must be overridden by subclasses."
        )

    # ------------------------------------------------------------------
    # Publishers
    # ------------------------------------------------------------------

    def set_joint_positions_publisher(self, publisher: Publisher) -> None:
        """Wire the publisher that emits :class:`JointPositionsMsg` at 50 Hz."""
        self.joint_positions_publisher = publisher

    def set_imu_publisher(self, publisher: Publisher) -> None:
        """Wire the publisher that emits :class:`ImuDataMsg` at 50 Hz."""
        self.imu_publisher = publisher

    def set_recording_publisher(self, publisher: Publisher) -> None:
        """Wire the publisher that emits :class:`RecordedDataMsg` on stop_recording."""
        self.recording_publisher = publisher

    # ------------------------------------------------------------------
    # Per-subsystem target setters
    # ------------------------------------------------------------------

    def set_target_neck_joint_positions(
        self, positions: Annotated[NDArray[np.float64], (NECK_DOF,)]
    ) -> None:
        """Set the target neck joint positions [yaw, pitch, roll]."""
        self.target_neck_joint_positions = np.asarray(positions, dtype=np.float64)

    def set_target_left_arm_joint_positions(
        self, positions: Annotated[NDArray[np.float64], (ARM_DOF,)]
    ) -> None:
        """Set the target left-arm joint positions [theta_a, theta_b]."""
        self.target_left_arm_joint_positions = np.asarray(positions, dtype=np.float64)

    def set_target_right_arm_joint_positions(
        self, positions: Annotated[NDArray[np.float64], (ARM_DOF,)]
    ) -> None:
        """Set the target right-arm joint positions [theta_a, theta_b]."""
        self.target_right_arm_joint_positions = np.asarray(positions, dtype=np.float64)

    def set_target_nose_joint_positions(
        self, positions: Annotated[NDArray[np.float64], (NOSE_DOF,)]
    ) -> None:
        """Set the target nose joint positions [top, left, right]."""
        self.target_nose_joint_positions = np.asarray(positions, dtype=np.float64)

    def set_target(
        self,
        neck: NDArray[np.float64] | None = None,
        left_arm: NDArray[np.float64] | None = None,
        right_arm: NDArray[np.float64] | None = None,
        nose: NDArray[np.float64] | None = None,
    ) -> None:
        """Apply any subset of subsystem targets in one call."""
        if neck is not None:
            self.set_target_neck_joint_positions(neck)
        if left_arm is not None:
            self.set_target_left_arm_joint_positions(left_arm)
        if right_arm is not None:
            self.set_target_right_arm_joint_positions(right_arm)
        if nose is not None:
            self.set_target_nose_joint_positions(nose)

    def _apply_joint_targets(self, targets: JointTargets) -> None:
        """Apply a :class:`JointTargets` (e.g. from a Move) to the target state."""
        if targets.neck is not None:
            self.set_target_neck_joint_positions(targets.neck)
        if targets.left_arm is not None:
            self.set_target_left_arm_joint_positions(targets.left_arm)
        if targets.right_arm is not None:
            self.set_target_right_arm_joint_positions(targets.right_arm)
        if targets.nose is not None:
            self.set_target_nose_joint_positions(targets.nose)

    # ------------------------------------------------------------------
    # Per-subsystem reads (abstract; subclasses fill in)
    # ------------------------------------------------------------------

    @abstractmethod
    def get_present_neck_joint_positions(
        self,
    ) -> Annotated[NDArray[np.float64], (NECK_DOF,)]:
        """Return the current neck joint positions."""

    @abstractmethod
    def get_present_left_arm_joint_positions(
        self,
    ) -> Annotated[NDArray[np.float64], (ARM_DOF,)]:
        """Return the current left-arm joint positions."""

    @abstractmethod
    def get_present_right_arm_joint_positions(
        self,
    ) -> Annotated[NDArray[np.float64], (ARM_DOF,)]:
        """Return the current right-arm joint positions."""

    @abstractmethod
    def get_present_nose_joint_positions(
        self,
    ) -> Annotated[NDArray[np.float64], (NOSE_DOF,)]:
        """Return the current nose joint positions."""

    # ------------------------------------------------------------------
    # Move playback
    # ------------------------------------------------------------------

    async def play_move(
        self,
        move: Move,
        play_frequency: float = 100.0,
        initial_goto_duration: float = 0.0,
    ) -> None:
        """Asynchronously play a :class:`Move`.

        Args:
            move: The :class:`Move` to play. Its :meth:`Move.evaluate`
                must return a :class:`JointTargets`.
            play_frequency: Evaluation frequency in Hz.
            initial_goto_duration: If > 0, first interpolate to the move's
                initial pose over this many seconds.

        """
        if not self._try_start_move():
            self.logger.warning("Ignoring play_move request: another move is running.")
            return

        try:
            if initial_goto_duration > 0.0:
                start_targets = move.evaluate(0.0)
                await self.goto_target(
                    neck=start_targets.neck,
                    left_arm=start_targets.left_arm,
                    right_arm=start_targets.right_arm,
                    nose=start_targets.nose,
                    duration=initial_goto_duration,
                )

            sleep_period = 1.0 / play_frequency

            if move.sound_path is not None:
                self.play_sound(str(move.sound_path))

            t0 = time.time()
            while time.time() - t0 < move.duration:
                t = time.time() - t0
                self._apply_joint_targets(move.evaluate(t))

                elapsed = time.time() - t0 - t
                if elapsed < sleep_period:
                    await asyncio.sleep(sleep_period - elapsed)
                else:
                    await asyncio.sleep(0.001)
        finally:
            self._end_move()

    async def goto_target(
        self,
        neck: NDArray[np.float64] | None = None,
        left_arm: NDArray[np.float64] | None = None,
        right_arm: NDArray[np.float64] | None = None,
        nose: NDArray[np.float64] | None = None,
        duration: float = 0.5,
        method: InterpolationTechnique = InterpolationTechnique.MIN_JERK,
    ) -> None:
        """Smoothly interpolate any subset of subsystems to the given targets."""
        target_neck = np.asarray(neck, dtype=np.float64) if neck is not None else None
        target_left = (
            np.asarray(left_arm, dtype=np.float64) if left_arm is not None else None
        )
        target_right = (
            np.asarray(right_arm, dtype=np.float64) if right_arm is not None else None
        )
        target_nose = np.asarray(nose, dtype=np.float64) if nose is not None else None

        await self.play_move(
            move=GotoMove(
                start_neck=self.get_present_neck_joint_positions(),
                target_neck=target_neck,
                start_left_arm=self.get_present_left_arm_joint_positions(),
                target_left_arm=target_left,
                start_right_arm=self.get_present_right_arm_joint_positions(),
                target_right_arm=target_right,
                start_nose=self.get_present_nose_joint_positions(),
                target_nose=target_nose,
                duration=duration,
                method=method,
            )
        )

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def append_record(self, record: dict[str, Any]) -> None:
        """Append a record to the active recording buffer (no-op when idle)."""
        if not self.is_recording:
            return
        with self._rec_lock:
            if self.is_recording:
                self.recorded_data.append(record)

    def start_recording(self) -> None:
        """Begin a new recording, discarding any previous buffer."""
        with self._rec_lock:
            self.recorded_data = []
            self.is_recording = True

    def stop_recording(self) -> None:
        """End recording and publish the buffered data."""
        with self._rec_lock:
            self.is_recording = False
            recorded_data, self.recorded_data = self.recorded_data, []
        if self.recording_publisher is not None:
            self.recording_publisher.put(RecordedDataMsg(data=recorded_data))
        else:
            self.logger.warning(
                "stop_recording called but recording_publisher is not set; dropping data."
            )

    # ------------------------------------------------------------------
    # Named poses (init / wake / sleep / ...)
    # ------------------------------------------------------------------

    def _load_named_poses(self) -> NamedPoses:
        """Load and cache the bundled named_poses.yaml."""
        if self._named_poses is None:
            self._named_poses = NamedPoses.load(_named_poses_path())
        return self._named_poses

    async def _goto_named_pose(self, name: str, duration: float) -> None:
        """Interpolate every subsystem of the named pose to its target."""
        pose: NamedPose = self._load_named_poses()[name]
        await self.goto_target(
            neck=pose.neck,
            left_arm=pose.left_arm,
            right_arm=pose.right_arm,
            nose=pose.nose,
            duration=duration,
        )

    async def wake_up(self) -> None:
        """Run the 'wake' named pose with the wake_up.wav cue."""
        await self._goto_named_pose("wake", duration=1.5)
        await asyncio.sleep(0.1)
        self.play_sound("wake_up.wav")
        await asyncio.sleep(0.5)

    async def goto_sleep(self) -> None:
        """Run the 'sleep' named pose with the go_sleep.wav cue.

        Releases servo torque on arms and nose the moment the pose
        finishes interpolating so the SM40BLs are not held at the
        mechanical envelope: prior versions kept torque on for a
        further 1 s, which sagged the shared Feetech rail and made
        the periodic hardware-error check report every motor as
        comm-failed. Robot-backend only — the helper is a no-op on
        the mockup/sim where ``self.c`` doesn't exist.
        """
        self.play_sound("go_sleep.wav")
        await self._goto_named_pose("sleep", duration=2.0)
        controller = getattr(self, "c", None)
        if controller is not None:
            try:
                controller.enable_arms(False)
                controller.enable_nose(False)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "goto_sleep: failed to release arm/nose torque: %s", exc
                )

    # ------------------------------------------------------------------
    # URDF
    # ------------------------------------------------------------------

    def get_urdf(self) -> str:
        """Return the URDF describing the robot."""
        urdf_path = Path(URDF_ROOT_PATH) / "robot.urdf"
        with open(urdf_path, "r") as f:
            return f.read()

    # ------------------------------------------------------------------
    # Multimedia
    # ------------------------------------------------------------------

    def play_sound(self, sound_file: str) -> None:
        """Delegate to the media server; no-op in no_media mode."""
        if self._media_server is not None:
            self._media_server.play_sound(sound_file)

    def stop_sound(self) -> None:
        """Delegate to the media server; no-op in no_media mode."""
        if self._media_server is not None:
            self._media_server.stop_sound()

    # ------------------------------------------------------------------
    # Motor control (abstract)
    # ------------------------------------------------------------------

    @abstractmethod
    def get_motor_control_mode(self) -> MotorControlMode:
        """Return the current motor control mode."""

    @abstractmethod
    def set_motor_control_mode(self, mode: MotorControlMode) -> None:
        """Set the motor control mode (enabled / disabled)."""

    @abstractmethod
    def set_motor_torque_ids(self, ids: list[str], on: bool) -> None:
        """Toggle torque on the named motors."""

    def write_raw_packet(self, packet: bytes) -> bytes:
        """Write a raw packet to the motor controller (real-robot backend only)."""
        raise NotImplementedError(
            "write_raw_packet is only available on the real-robot backend."
        )

    # ------------------------------------------------------------------
    # Transport-agnostic command dispatch
    # ------------------------------------------------------------------

    def process_command(
        self,
        cmd: AnyCommand,
        send_response: Callable[[dict[str, Any]], None],
    ) -> None:
        """Dispatch a validated command to the matching handler."""
        block_targets = self.is_move_running

        def _maybe_ignore(field: str) -> bool:
            if not block_targets:
                return False
            self.logger.warning(
                f"Ignoring {field} command: a move is currently running."
            )
            return True

        if isinstance(cmd, SetNeckCmd):
            if not _maybe_ignore("set_neck"):
                self.set_target_neck_joint_positions(np.array(cmd.joints))
            send_response({"status": "ok", "command": "set_neck"})

        elif isinstance(cmd, SetArmCmd):
            if not _maybe_ignore("set_arm"):
                if cmd.side == ArmSide.Left:
                    self.set_target_left_arm_joint_positions(np.array(cmd.joints))
                else:
                    self.set_target_right_arm_joint_positions(np.array(cmd.joints))
            send_response(
                {"status": "ok", "command": "set_arm", "side": cmd.side.value}
            )

        elif isinstance(cmd, SetNoseCmd):
            if not _maybe_ignore("set_nose"):
                self.set_target_nose_joint_positions(np.array(cmd.joints))
            send_response({"status": "ok", "command": "set_nose"})

        elif isinstance(cmd, SetFullTargetCmd):
            if not _maybe_ignore("set_full_target"):
                self.set_target(
                    neck=np.array(cmd.neck) if cmd.neck is not None else None,
                    left_arm=np.array(cmd.left_arm)
                    if cmd.left_arm is not None
                    else None,
                    right_arm=np.array(cmd.right_arm)
                    if cmd.right_arm is not None
                    else None,
                    nose=np.array(cmd.nose) if cmd.nose is not None else None,
                )
            send_response({"status": "ok", "command": "set_full_target"})

        elif isinstance(cmd, GotoTargetCmd):
            neck = np.array(cmd.neck) if cmd.neck is not None else None
            left = np.array(cmd.left_arm) if cmd.left_arm is not None else None
            right = np.array(cmd.right_arm) if cmd.right_arm is not None else None
            nose = np.array(cmd.nose) if cmd.nose is not None else None
            asyncio.create_task(
                self._async_goto(send_response, neck, left, right, nose, cmd.duration)
            )

        elif isinstance(cmd, WakeUpCmd):
            asyncio.create_task(self._async_wake_up(send_response))

        elif isinstance(cmd, GotoSleepCmd):
            asyncio.create_task(self._async_goto_sleep(send_response))

        elif isinstance(cmd, PlaySoundCmd):
            self.play_sound(cmd.file)
            send_response({"status": "ok", "command": "play_sound"})

        elif isinstance(cmd, SetMotorModeCmd):
            self.set_motor_control_mode(MotorControlMode(cmd.mode))
            send_response({"motor_mode": cmd.mode, "status": "ok"})

        elif isinstance(cmd, SetTorqueCmd):
            if cmd.ids is not None:
                self.set_motor_torque_ids(cmd.ids, cmd.on)
            elif cmd.on:
                self.set_motor_control_mode(MotorControlMode.Enabled)
            else:
                self.set_motor_control_mode(MotorControlMode.Disabled)
            send_response({"status": "ok", "command": "set_torque"})

        elif isinstance(cmd, GetMotorModeCmd):
            send_response({"motor_mode": self.get_motor_control_mode().value})

        elif isinstance(cmd, GetStateCmd):
            state = {
                "neck": self._safe_present(self.get_present_neck_joint_positions),
                "left_arm": self._safe_present(
                    self.get_present_left_arm_joint_positions
                ),
                "right_arm": self._safe_present(
                    self.get_present_right_arm_joint_positions
                ),
                "nose": self._safe_present(self.get_present_nose_joint_positions),
                "motor_mode": self.get_motor_control_mode().value,
                "is_recording": self.is_recording,
                "is_move_running": self.is_move_running,
            }
            send_response({"state": state})

        elif isinstance(cmd, GetVersionCmd):
            from importlib.metadata import version

            send_response({"version": version("dreambo_torso")})

        elif isinstance(
            cmd,
            (
                SetVolumeCmd,
                GetVolumeCmd,
                SetMicrophoneVolumeCmd,
                GetMicrophoneVolumeCmd,
            ),
        ):
            self._handle_volume_command(cmd, send_response)

        elif isinstance(cmd, StartRecordingCmd):
            self.start_recording()
            send_response(
                {"status": "ok", "command": "start_recording", "is_recording": True}
            )
        elif isinstance(cmd, StopRecordingCmd):
            self.stop_recording()
            send_response(
                {"status": "ok", "command": "stop_recording", "is_recording": False}
            )
        elif isinstance(cmd, AppendRecordCmd):
            self.append_record(cmd.record)
            send_response({"status": "ok", "command": "append_record"})

    def _safe_present(
        self, getter: Callable[[], NDArray[np.float64]]
    ) -> list[float] | None:
        """Call *getter* and return its result as a list, or None if no data yet."""
        try:
            arr = getter()
        except (AssertionError, NotImplementedError, AttributeError):
            return None
        return arr.tolist() if arr is not None else None

    def _handle_volume_command(
        self,
        cmd: SetVolumeCmd
        | GetVolumeCmd
        | SetMicrophoneVolumeCmd
        | GetMicrophoneVolumeCmd,
        send_response: Callable[[dict[str, Any]], None],
    ) -> None:
        from dreambo_torso.daemon.app.routers.volume_control import get_volume_control

        try:
            vc = get_volume_control()
        except Exception as e:
            self.logger.warning("Volume command failed (no control): %s", e)
            send_response(
                {"error": f"Volume control unavailable: {e}", "command": cmd.type}
            )
            return

        if isinstance(cmd, SetVolumeCmd):
            ok = vc.set_output_volume(cmd.volume)
            send_response(
                {
                    "status": "ok" if ok else "error",
                    "command": "set_volume",
                    "volume": cmd.volume if ok else vc.get_output_volume(),
                }
            )
        elif isinstance(cmd, GetVolumeCmd):
            send_response({"command": "get_volume", "volume": vc.get_output_volume()})
        elif isinstance(cmd, SetMicrophoneVolumeCmd):
            ok = vc.set_input_volume(cmd.volume)
            send_response(
                {
                    "status": "ok" if ok else "error",
                    "command": "set_microphone_volume",
                    "volume": cmd.volume if ok else vc.get_input_volume(),
                }
            )
        else:  # GetMicrophoneVolumeCmd
            send_response(
                {"command": "get_microphone_volume", "volume": vc.get_input_volume()}
            )

    async def _async_goto(
        self,
        send_response: Callable[[dict[str, Any]], None],
        neck: NDArray[np.float64] | None,
        left_arm: NDArray[np.float64] | None,
        right_arm: NDArray[np.float64] | None,
        nose: NDArray[np.float64] | None,
        duration: float,
    ) -> None:
        """Run :meth:`goto_target` and report completion via *send_response*."""
        try:
            await self.goto_target(
                neck=neck,
                left_arm=left_arm,
                right_arm=right_arm,
                nose=nose,
                duration=duration,
            )
            send_response({"status": "ok", "command": "goto_target", "completed": True})
        except Exception as e:
            send_response({"error": str(e), "command": "goto_target"})

    async def _async_wake_up(
        self, send_response: Callable[[dict[str, Any]], None]
    ) -> None:
        """Run :meth:`wake_up` and report completion via *send_response*."""
        try:
            await self.wake_up()
            send_response({"status": "ok", "command": "wake_up", "completed": True})
        except Exception as e:
            send_response({"error": str(e), "command": "wake_up"})

    async def _async_goto_sleep(
        self, send_response: Callable[[dict[str, Any]], None]
    ) -> None:
        """Run :meth:`goto_sleep` and report completion via *send_response*."""
        try:
            await self.goto_sleep()
            send_response({"status": "ok", "command": "goto_sleep", "completed": True})
        except Exception as e:
            send_response({"error": str(e), "command": "goto_sleep"})

    # ------------------------------------------------------------------
    # WebRTC data channel
    # ------------------------------------------------------------------

    def setup_media_server(self, media_server: Any) -> None:
        """Wire the media server for play_sound + WebRTC data-channel messages."""
        self._media_server = media_server

        _loop = asyncio.new_event_loop()
        threading.Thread(target=_loop.run_forever, daemon=True).start()

        def _threadsafe_handler(peer_id: str, message: str) -> None:
            _loop.call_soon_threadsafe(self._handle_webrtc_message, peer_id, message)

        media_server.set_message_handler(_threadsafe_handler)
        self._send_message_to_webrtc = media_server.send_data_message

    def _handle_webrtc_message(self, peer_id: str, message: str) -> None:
        def send(resp: dict[str, Any]) -> None:
            self._send_webrtc_response(peer_id, resp)

        try:
            cmd = command_adapter.validate_json(message)
        except Exception as e:
            self.logger.error(f"WebRTC invalid command: {e}")
            send({"error": f"Invalid command: {e}"})
            return
        try:
            self.process_command(cmd, send_response=send)
        except Exception as e:
            self.logger.error(f"WebRTC command error: {e}")
            send({"error": str(e)})

    def _send_webrtc_response(self, peer_id: str, response: dict[str, Any]) -> None:
        if self._send_message_to_webrtc:
            self._send_message_to_webrtc(peer_id, json.dumps(response))
