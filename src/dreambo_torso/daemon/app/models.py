"""Common pydantic models for the daemon HTTP API."""

from datetime import datetime

from pydantic import BaseModel

from dreambo_torso.io.protocol import MotorControlMode


class FullBodyTarget(BaseModel):
    """Joint-space targets for any subset of subsystems."""

    target_neck: list[float] | None = None         # [yaw, pitch, roll]
    target_left_arm: list[float] | None = None     # [theta_a, theta_b]
    target_right_arm: list[float] | None = None    # [theta_a, theta_b]
    target_nose: list[float] | None = None         # [top, left, right]
    timestamp: datetime | None = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "target_neck": [0.0, 0.2, 0.0],
                    "target_left_arm": [0.0, 0.0],
                    "target_right_arm": [0.0, 0.0],
                    "target_nose": [0.0, 0.0, 0.0],
                }
            ]
        }
    }


class DoAInfo(BaseModel):
    """Direction of Arrival info from the microphone array."""

    angle: float  # Angle in radians (0=left, π/2=front, π=right)
    speech_detected: bool


class FullState(BaseModel):
    """Per-subsystem present + target state, plus auxiliary data."""

    control_mode: MotorControlMode | None = None
    neck: list[float] | None = None
    left_arm: list[float] | None = None
    right_arm: list[float] | None = None
    nose: list[float] | None = None
    target_neck: list[float] | None = None
    target_left_arm: list[float] | None = None
    target_right_arm: list[float] | None = None
    target_nose: list[float] | None = None
    timestamp: datetime | None = None
    doa: DoAInfo | None = None
