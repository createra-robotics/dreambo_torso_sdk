"""MuJoCo backend for the Dreambo torso.

The legacy MJCF described the Reachy-Mini Stewart head; it does not
match the new arms-plus-neck-plus-nose topology. Until a new MJCF is
authored for the Dreambo torso, this backend refuses to initialize so
callers fall back to ``mockup_sim`` or the real-robot backend.
"""

from typing import Annotated

import numpy as np
import numpy.typing as npt

from dreambo_torso.io.protocol import MotorControlMode, MujocoBackendStatus

from ..abstract import ARM_DOF, NECK_DOF, NOSE_DOF, Backend


class MujocoBackend(Backend):
    """Placeholder MuJoCo backend pending a new Dreambo-torso MJCF."""

    def __init__(
        self,
        scene: str = "empty",
        headless: bool = False,
        use_audio: bool = False,
    ) -> None:
        """Refuse to initialize: the new-robot MJCF is not yet authored."""
        raise NotImplementedError(
            "The MuJoCo backend is disabled while the Dreambo-torso MJCF is rewritten. "
            "Use --mockup-sim for a headless software simulation, or the real-robot "
            "backend with hardware attached."
        )

    def run(self) -> None:
        """Not reachable; ``__init__`` raises."""
        raise NotImplementedError

    def get_status(self) -> "MujocoBackendStatus":
        """Return a benign status object; never actually reached."""
        return MujocoBackendStatus(motor_control_mode=MotorControlMode.Disabled)

    def get_present_neck_joint_positions(
        self,
    ) -> Annotated[npt.NDArray[np.float64], (NECK_DOF,)]:
        """Unused; backend never initializes."""
        return np.zeros(NECK_DOF, dtype=np.float64)

    def get_present_left_arm_joint_positions(
        self,
    ) -> Annotated[npt.NDArray[np.float64], (ARM_DOF,)]:
        """Unused; backend never initializes."""
        return np.zeros(ARM_DOF, dtype=np.float64)

    def get_present_right_arm_joint_positions(
        self,
    ) -> Annotated[npt.NDArray[np.float64], (ARM_DOF,)]:
        """Unused; backend never initializes."""
        return np.zeros(ARM_DOF, dtype=np.float64)

    def get_present_nose_joint_positions(
        self,
    ) -> Annotated[npt.NDArray[np.float64], (NOSE_DOF,)]:
        """Unused; backend never initializes."""
        return np.zeros(NOSE_DOF, dtype=np.float64)

    def get_motor_control_mode(self) -> MotorControlMode:
        """Unused; backend never initializes."""
        return MotorControlMode.Disabled

    def set_motor_control_mode(self, mode: MotorControlMode) -> None:
        """No-op."""

    def set_motor_torque_ids(self, ids: list[str], on: bool) -> None:
        """No-op."""
