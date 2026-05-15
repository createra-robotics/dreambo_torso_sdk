"""Protocol definitions for Dreambo client/server communication.

All messages use a {"type": "...", ...payload} envelope.

Subsystems on the new Dreambo torso:
    - neck:      3-DOF serial gimbal (yaw, pitch, roll), DM motors over CAN.
    - left_arm:  2-DOF spherical 5-bar (theta_a, theta_b), Feetech servos.
    - right_arm: 2-DOF spherical 5-bar (theta_a, theta_b), Feetech servos.
    - nose:      3 independent Feetech servos (top, left, right).

Client->Server command types:
    set_neck, set_arm, set_nose, set_full_target, goto_target,
    wake_up, goto_sleep, play_sound,
    set_motor_mode, set_torque, get_motor_mode,
    get_state, get_version, start_recording, stop_recording, append_record,
    set_volume, get_volume, set_microphone_volume, get_microphone_volume

Server->Client message types:
    joint_positions, imu_data, recorded_data, daemon_status, task_progress
"""

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, TypeAdapter

from dreambo_torso.utils.interpolation import InterpolationTechnique

# ------------------------------------------------------------------
# Shared enums
# ------------------------------------------------------------------


class MotorControlMode(str, Enum):
    """Enum for motor control modes."""

    Enabled = "enabled"
    Disabled = "disabled"


class ArmSide(str, Enum):
    """Which arm a command targets."""

    Left = "left"
    Right = "right"


class DaemonState(str, Enum):
    """Enum representing the state of the Dreambo robot daemon."""

    NOT_INITIALIZED = "not_initialized"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


# ------------------------------------------------------------------
# Backend status models
# ------------------------------------------------------------------
class RobotBackendStatus(BaseModel):
    """Status of the Robot Backend."""

    ready: bool
    motor_control_mode: MotorControlMode
    last_alive: float | None
    control_loop_stats: dict[str, Any]
    error: str | None = None


class MujocoBackendStatus(BaseModel):
    """Status of the Mujoco backend."""

    motor_control_mode: MotorControlMode
    error: str | None = None


class MockupSimBackendStatus(BaseModel):
    """Status of the MockupSim backend."""

    motor_control_mode: MotorControlMode
    error: str | None = None


class DaemonStatus(BaseModel):
    """Status of the Dreambo torso daemon."""

    type: Literal["daemon_status"] = "daemon_status"
    robot_name: str
    state: DaemonState
    wireless_version: bool
    desktop_app_daemon: bool
    simulation_enabled: Optional[bool]
    mockup_sim_enabled: Optional[bool]
    no_media: bool = False
    media_released: bool = False
    camera_specs_name: str = ""
    backend_status: Optional[
        RobotBackendStatus | MujocoBackendStatus | MockupSimBackendStatus
    ]
    error: Optional[str] = None
    wlan_ip: Optional[str] = None
    version: Optional[str] = None


# ------------------------------------------------------------------
# Client -> Server commands
# ------------------------------------------------------------------


class SetNeckCmd(BaseModel):
    """Set the target neck joint positions [yaw, pitch, roll] (radians)."""

    type: Literal["set_neck"] = "set_neck"
    joints: list[float] = Field(..., min_length=3, max_length=3)


class SetArmCmd(BaseModel):
    """Set the target joint positions of one arm [theta_a, theta_b] (radians)."""

    type: Literal["set_arm"] = "set_arm"
    side: ArmSide
    joints: list[float] = Field(..., min_length=2, max_length=2)


class SetNoseCmd(BaseModel):
    """Set the target nose joint positions [top, left, right] (radians)."""

    type: Literal["set_nose"] = "set_nose"
    joints: list[float] = Field(..., min_length=3, max_length=3)


class SetFullTargetCmd(BaseModel):
    """Set any subset of subsystems in a single message.

    Each subsystem field is optional; only those that are non-None are
    applied. Avoids the overhead of multiple WebSocket round-trips when
    coordinating several subsystems.
    """

    type: Literal["set_full_target"] = "set_full_target"
    neck: list[float] | None = None        # [yaw, pitch, roll]
    left_arm: list[float] | None = None    # [theta_a, theta_b]
    right_arm: list[float] | None = None   # [theta_a, theta_b]
    nose: list[float] | None = None        # [top, left, right]


class GotoTargetCmd(BaseModel):
    """Smooth interpolated goto for any subset of subsystems."""

    type: Literal["goto_target"] = "goto_target"
    neck: list[float] | None = None
    left_arm: list[float] | None = None
    right_arm: list[float] | None = None
    nose: list[float] | None = None
    duration: float = 0.5


class WakeUpCmd(BaseModel):
    """Wake up the robot (run the named 'wake' pose + audio)."""

    type: Literal["wake_up"] = "wake_up"


class GotoSleepCmd(BaseModel):
    """Put the robot to sleep (run the named 'sleep' pose + audio)."""

    type: Literal["goto_sleep"] = "goto_sleep"


class PlaySoundCmd(BaseModel):
    """Play a sound file."""

    type: Literal["play_sound"] = "play_sound"
    file: str


class SetMotorModeCmd(BaseModel):
    """Set the motor control mode (enabled, disabled)."""

    type: Literal["set_motor_mode"] = "set_motor_mode"
    mode: str


class SetTorqueCmd(BaseModel):
    """Set torque on/off, optionally for specific motor IDs."""

    type: Literal["set_torque"] = "set_torque"
    on: bool
    ids: list[str] | None = None


class GetMotorModeCmd(BaseModel):
    """Query the current motor control mode."""

    type: Literal["get_motor_mode"] = "get_motor_mode"


class GetStateCmd(BaseModel):
    """Query the full robot state."""

    type: Literal["get_state"] = "get_state"


class GetVersionCmd(BaseModel):
    """Query the version."""

    type: Literal["get_version"] = "get_version"


class StartRecordingCmd(BaseModel):
    """Start recording joint data."""

    type: Literal["start_recording"] = "start_recording"


class StopRecordingCmd(BaseModel):
    """Stop recording and publish recorded data."""

    type: Literal["stop_recording"] = "stop_recording"


class AppendRecordCmd(BaseModel):
    """Append a single record to the recording buffer."""

    type: Literal["append_record"] = "append_record"
    record: dict[str, Any]


# Volume / microphone commands. Volume is a global robot setting (not
# per-session), so a remote client's change persists after they
# disconnect — same semantics as the local REST /api/volume endpoints.
class SetVolumeCmd(BaseModel):
    """Set the output (speaker) volume, 0-100."""

    type: Literal["set_volume"] = "set_volume"
    volume: int = Field(..., ge=0, le=100)


class GetVolumeCmd(BaseModel):
    """Query the current output (speaker) volume."""

    type: Literal["get_volume"] = "get_volume"


class SetMicrophoneVolumeCmd(BaseModel):
    """Set the input (microphone) volume, 0-100."""

    type: Literal["set_microphone_volume"] = "set_microphone_volume"
    volume: int = Field(..., ge=0, le=100)


class GetMicrophoneVolumeCmd(BaseModel):
    """Query the current input (microphone) volume."""

    type: Literal["get_microphone_volume"] = "get_microphone_volume"


AnyCommand = Annotated[
    SetNeckCmd
    | SetArmCmd
    | SetNoseCmd
    | SetFullTargetCmd
    | GotoTargetCmd
    | WakeUpCmd
    | GotoSleepCmd
    | PlaySoundCmd
    | SetMotorModeCmd
    | SetTorqueCmd
    | GetMotorModeCmd
    | GetStateCmd
    | GetVersionCmd
    | StartRecordingCmd
    | StopRecordingCmd
    | AppendRecordCmd
    | SetVolumeCmd
    | GetVolumeCmd
    | SetMicrophoneVolumeCmd
    | GetMicrophoneVolumeCmd,
    Field(discriminator="type"),
]

command_adapter: TypeAdapter[AnyCommand] = TypeAdapter(AnyCommand)


# ------------------------------------------------------------------
# Server -> Client state messages (published by backend control loops)
# ------------------------------------------------------------------


class JointPositionsMsg(BaseModel):
    """Per-subsystem joint positions (published at 50 Hz).

    Channels are emitted unconditionally; subsystems whose hardware is
    absent or torqued off report their last-known position.
    """

    type: Literal["joint_positions"] = "joint_positions"
    neck: list[float]        # [yaw, pitch, roll]
    left_arm: list[float]    # [theta_a, theta_b]
    right_arm: list[float]   # [theta_a, theta_b]
    nose: list[float]        # [top, left, right]


class ImuDataMsg(BaseModel):
    """IMU sensor data (published at 50 Hz on wireless version)."""

    type: Literal["imu_data"] = "imu_data"
    accelerometer: list[float]
    gyroscope: list[float]
    quaternion: list[float]
    temperature: float


class RecordedDataMsg(BaseModel):
    """Recorded joint data (published once when recording stops)."""

    type: Literal["recorded_data"] = "recorded_data"
    data: list[dict[str, Any]]


# ------------------------------------------------------------------
# Task protocol
# ------------------------------------------------------------------


class GotoTaskRequest(BaseModel):
    """A goto target task (any subset of subsystems)."""

    neck: list[float] | None = None
    left_arm: list[float] | None = None
    right_arm: list[float] | None = None
    nose: list[float] | None = None
    duration: float
    method: InterpolationTechnique


class PlayMoveTaskRequest(BaseModel):
    """A play move task."""

    move_name: str


AnyTaskRequest = GotoTaskRequest | PlayMoveTaskRequest


class TaskRequest(BaseModel):
    """Any task request (sent by client with type="task")."""

    type: Literal["task"] = "task"
    uuid: UUID
    req: AnyTaskRequest
    timestamp: datetime


AnyMessage = Annotated[AnyCommand | TaskRequest, Field(discriminator="type")]
message_adapter: TypeAdapter[AnyMessage] = TypeAdapter(AnyMessage)


class TaskProgress(BaseModel):
    """Task progress (broadcast to all clients)."""

    type: Literal["task_progress"] = "task_progress"
    uuid: UUID
    finished: bool = False
    error: str | None = None
    timestamp: datetime


AnyServerMsg = Annotated[
    JointPositionsMsg
    | ImuDataMsg
    | RecordedDataMsg
    | DaemonStatus
    | TaskProgress,
    Field(discriminator="type"),
]
server_msg_adapter: TypeAdapter[AnyServerMsg] = TypeAdapter(AnyServerMsg)
