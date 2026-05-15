"""Mockup-sim backend: target positions become present positions immediately.

No physics, no IK/FK — just an in-memory mirror of the joint state for
software-only testing without MuJoCo or real hardware.
"""

import time
from typing import Annotated

import numpy as np
import numpy.typing as npt

from dreambo_torso.io.protocol import (
    JointPositionsMsg,
    MockupSimBackendStatus,
    MotorControlMode,
)
from dreambo_torso.motion.named_poses import NamedPoses

from ..abstract import ARM_DOF, NECK_DOF, NOSE_DOF, Backend, _named_poses_path


def _initial_pose(poses: NamedPoses, name: str, sub: str, dof: int) -> npt.NDArray[np.float64]:
    """Pick the named pose's joints for *sub* if present, else zero."""
    if name in poses:
        pose = poses[name]
        arr = getattr(pose, sub, None)
        if arr is not None:
            return np.asarray(arr, dtype=np.float64).copy()
    return np.zeros(dof, dtype=np.float64)


class MockupSimBackend(Backend):
    """Lightweight in-memory simulation backend for the Dreambo torso."""

    def __init__(self, use_audio: bool = True) -> None:
        """Seed every subsystem at the bundled 'sleep' pose and start disabled."""
        super().__init__(use_audio=use_audio)

        poses = NamedPoses.load(_named_poses_path())
        self._neck = _initial_pose(poses, "sleep", "neck", NECK_DOF)
        self._left_arm = _initial_pose(poses, "sleep", "left_arm", ARM_DOF)
        self._right_arm = _initial_pose(poses, "sleep", "right_arm", ARM_DOF)
        self._nose = _initial_pose(poses, "sleep", "nose", NOSE_DOF)

        self.current_neck_joint_positions = self._neck.copy()
        self.current_left_arm_joint_positions = self._left_arm.copy()
        self.current_right_arm_joint_positions = self._right_arm.copy()
        self.current_nose_joint_positions = self._nose.copy()

        self._motor_control_mode = MotorControlMode.Enabled
        self.control_frequency = 50.0  # Hz

    def run(self) -> None:
        """Mirror targets to present positions at the control loop frequency."""
        control_period = 1.0 / self.control_frequency

        while not self.should_stop.is_set():
            start_t = time.time()

            if self.target_neck_joint_positions is not None:
                self._neck = self.target_neck_joint_positions.copy()
            if self.target_left_arm_joint_positions is not None:
                self._left_arm = self.target_left_arm_joint_positions.copy()
            if self.target_right_arm_joint_positions is not None:
                self._right_arm = self.target_right_arm_joint_positions.copy()
            if self.target_nose_joint_positions is not None:
                self._nose = self.target_nose_joint_positions.copy()

            self.current_neck_joint_positions = self._neck.copy()
            self.current_left_arm_joint_positions = self._left_arm.copy()
            self.current_right_arm_joint_positions = self._right_arm.copy()
            self.current_nose_joint_positions = self._nose.copy()

            if self.joint_positions_publisher is not None and not self.is_shutting_down:
                self.joint_positions_publisher.put(
                    JointPositionsMsg(
                        neck=self._neck.tolist(),
                        left_arm=self._left_arm.tolist(),
                        right_arm=self._right_arm.tolist(),
                        nose=self._nose.tolist(),
                    )
                )

            self.ready.set()

            elapsed = time.time() - start_t
            time.sleep(max(0.0, control_period - elapsed))

    def get_status(self) -> "MockupSimBackendStatus":
        """Return the cached :class:`MockupSimBackendStatus`."""
        return MockupSimBackendStatus(motor_control_mode=self._motor_control_mode)

    def get_present_neck_joint_positions(
        self,
    ) -> Annotated[npt.NDArray[np.float64], (NECK_DOF,)]:
        """Return the current neck joint positions."""
        return self._neck.copy()

    def get_present_left_arm_joint_positions(
        self,
    ) -> Annotated[npt.NDArray[np.float64], (ARM_DOF,)]:
        """Return the current left-arm joint positions."""
        return self._left_arm.copy()

    def get_present_right_arm_joint_positions(
        self,
    ) -> Annotated[npt.NDArray[np.float64], (ARM_DOF,)]:
        """Return the current right-arm joint positions."""
        return self._right_arm.copy()

    def get_present_nose_joint_positions(
        self,
    ) -> Annotated[npt.NDArray[np.float64], (NOSE_DOF,)]:
        """Return the current nose joint positions."""
        return self._nose.copy()

    def get_motor_control_mode(self) -> MotorControlMode:
        """Return the current motor control mode."""
        return self._motor_control_mode

    def set_motor_control_mode(self, mode: MotorControlMode) -> None:
        """Set the motor control mode (no-op physics; just records state)."""
        self._motor_control_mode = mode

    def set_motor_torque_ids(self, ids: list[str], on: bool) -> None:
        """No-op in mockup-sim mode."""
