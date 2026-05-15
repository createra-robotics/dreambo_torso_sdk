"""A goto move that linearly interpolates per-subsystem joint targets."""

from typing import Optional

import numpy as np
import numpy.typing as npt

from dreambo_torso.utils.interpolation import (
    InterpolationTechnique,
    time_trajectory,
)

from .move import JointTargets, Move


class GotoMove(Move):
    """Interpolate every requested subsystem from its start to its target.

    Each subsystem (neck / left_arm / right_arm / nose) is independent:
    pass a ``target_*`` to drive it, or leave it ``None`` to hold its
    starting position throughout the move.
    """

    def __init__(
        self,
        start_neck: npt.NDArray[np.float64],
        target_neck: Optional[npt.NDArray[np.float64]],
        start_left_arm: npt.NDArray[np.float64],
        target_left_arm: Optional[npt.NDArray[np.float64]],
        start_right_arm: npt.NDArray[np.float64],
        target_right_arm: Optional[npt.NDArray[np.float64]],
        start_nose: npt.NDArray[np.float64],
        target_nose: Optional[npt.NDArray[np.float64]],
        duration: float,
        method: InterpolationTechnique,
    ) -> None:
        """Capture start/target pairs per subsystem and the interpolation method."""
        self.start_neck = start_neck
        self.target_neck = target_neck if target_neck is not None else start_neck
        self.start_left_arm = start_left_arm
        self.target_left_arm = (
            target_left_arm if target_left_arm is not None else start_left_arm
        )
        self.start_right_arm = start_right_arm
        self.target_right_arm = (
            target_right_arm if target_right_arm is not None else start_right_arm
        )
        self.start_nose = start_nose
        self.target_nose = target_nose if target_nose is not None else start_nose

        # Track which channels the caller actually requested so we can
        # leave the rest unset in the JointTargets we return.
        self._drive_neck = target_neck is not None
        self._drive_left_arm = target_left_arm is not None
        self._drive_right_arm = target_right_arm is not None
        self._drive_nose = target_nose is not None

        self._duration = duration
        self.method = method

    @property
    def duration(self) -> float:
        """Duration of the goto in seconds."""
        return self._duration

    def evaluate(self, t: float) -> JointTargets:
        """Evaluate every requested channel at the given time."""
        alpha = time_trajectory(min(max(t / self._duration, 0.0), 1.0), method=self.method)

        targets = JointTargets()
        if self._drive_neck:
            targets.neck = self.start_neck + (self.target_neck - self.start_neck) * alpha
        if self._drive_left_arm:
            targets.left_arm = (
                self.start_left_arm
                + (self.target_left_arm - self.start_left_arm) * alpha
            )
        if self._drive_right_arm:
            targets.right_arm = (
                self.start_right_arm
                + (self.target_right_arm - self.start_right_arm) * alpha
            )
        if self._drive_nose:
            targets.nose = self.start_nose + (self.target_nose - self.start_nose) * alpha
        return targets


def _as_array(value: Optional[npt.NDArray[np.float64] | list[float]], expected_len: int) -> Optional[npt.NDArray[np.float64]]:
    """Coerce a list or array to a 1-D float64 array of the given length, or None."""
    if value is None:
        return None
    arr = np.asarray(value, dtype=np.float64).reshape(-1)
    if arr.shape != (expected_len,):
        raise ValueError(
            f"Expected length-{expected_len} array, got shape {arr.shape}."
        )
    return arr
