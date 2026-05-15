"""Base classes for motion moves on the Dreambo torso."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import numpy.typing as npt


@dataclass
class JointTargets:
    """Per-subsystem joint targets evaluated at a moment in time.

    Each field is either an ndarray of joint positions in radians or None
    (meaning "leave this subsystem alone at this instant"). The shapes are:

    - neck:      (3,) — [yaw, pitch, roll]
    - left_arm:  (2,) — [theta_a, theta_b]
    - right_arm: (2,) — [theta_a, theta_b]
    - nose:      (3,) — [top, left, right]
    """

    neck: Optional[npt.NDArray[np.float64]] = None
    left_arm: Optional[npt.NDArray[np.float64]] = None
    right_arm: Optional[npt.NDArray[np.float64]] = None
    nose: Optional[npt.NDArray[np.float64]] = None


class Move(ABC):
    """Abstract base class for a move on the Dreambo torso."""

    @property
    def sound_path(self) -> Optional[Path]:
        """Optional sound file played alongside the move."""
        return None

    @property
    @abstractmethod
    def duration(self) -> float:
        """Duration of the move in seconds."""
        pass

    @abstractmethod
    def evaluate(self, t: float) -> JointTargets:
        """Evaluate the move at time *t* (seconds, ``0 <= t <= duration``).

        Subclasses return a :class:`JointTargets` with the desired
        joint positions for each subsystem at this instant; subsystems
        left as ``None`` are not driven by this move.
        """
        pass
