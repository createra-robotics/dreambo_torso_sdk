"""Named poses for the Dreambo torso, loaded from a YAML config file."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Literal, Optional

import numpy as np
import numpy.typing as npt
import yaml
from dreambo_torso_kinematics import DreamboArmKinematics

_SUBSYSTEM_DOFS: Dict[str, int] = {
    "neck": 3,
    "left_arm": 2,
    "right_arm": 2,
    "nose": 3,
}

_ARM_KINEMATICS: Dict[str, DreamboArmKinematics] = {}


def _arm_kinematics(side: Literal["left_arm", "right_arm"]) -> DreamboArmKinematics:
    """Cache and return the kinematics object for the named arm subsystem."""
    if side not in _ARM_KINEMATICS:
        _ARM_KINEMATICS[side] = (
            DreamboArmKinematics.default_left()
            if side == "left_arm"
            else DreamboArmKinematics.default_right()
        )
    return _ARM_KINEMATICS[side]


@dataclass
class NamedPose:
    """Joint-space pose for any subset of subsystems."""

    neck: Optional[npt.NDArray[np.float64]] = None
    left_arm: Optional[npt.NDArray[np.float64]] = None
    right_arm: Optional[npt.NDArray[np.float64]] = None
    nose: Optional[npt.NDArray[np.float64]] = None


@dataclass
class NamedPoses:
    """Mapping of pose names to :class:`NamedPose` entries loaded from YAML."""

    poses: Dict[str, NamedPose] = field(default_factory=dict)

    def __getitem__(self, name: str) -> NamedPose:
        """Return the named pose, raising KeyError when missing."""
        if name not in self.poses:
            raise KeyError(f"Unknown pose '{name}'. Known: {sorted(self.poses)}")
        return self.poses[name]

    def __contains__(self, name: str) -> bool:
        """Return True when *name* is one of the loaded pose names."""
        return name in self.poses

    @classmethod
    def load(cls, path: str | Path) -> "NamedPoses":
        """Load named poses from a YAML file at *path*.

        Arm entries (``left_arm`` / ``right_arm``) accept two forms:

        - Raw joints: ``left_arm: [theta_a, theta_b]``
        - Pointing direction: ``left_arm: {direction: [x, y, z]}``

        The direction form is resolved to joints via spherical 5-bar IK
        at load time; the smallest-norm branch is picked (no current
        state to bias toward).
        """
        with open(path, "r") as f:
            raw = yaml.safe_load(f) or {}
        poses: Dict[str, NamedPose] = {}
        for name, body in raw.items():
            if not isinstance(body, dict):
                raise ValueError(
                    f"Pose '{name}' must be a mapping of subsystem -> joint list."
                )
            pose = NamedPose()
            for sub, dof in _SUBSYSTEM_DOFS.items():
                if sub not in body:
                    continue
                arr = _parse_subsystem_entry(name, sub, body[sub], dof)
                setattr(pose, sub, arr)
            poses[name] = pose
        return cls(poses=poses)


def _parse_subsystem_entry(
    pose_name: str,
    sub: str,
    value: Any,
    dof: int,
) -> npt.NDArray[np.float64]:
    """Parse a single subsystem entry into a 1D joint-angle array.

    Arms additionally accept ``{direction: [x, y, z]}`` and resolve it
    to ``[theta_a, theta_b]`` via IK; everything else requires a
    plain list of ``dof`` floats.
    """
    if isinstance(value, dict):
        if sub not in ("left_arm", "right_arm"):
            raise ValueError(
                f"Pose '{pose_name}' subsystem '{sub}' does not support dict form; "
                f"only arm entries accept {{direction: [...]}}."
            )
        if set(value.keys()) != {"direction"}:
            raise ValueError(
                f"Pose '{pose_name}' arm entry '{sub}' must be a mapping with "
                f"exactly one key 'direction', got keys {sorted(value.keys())}."
            )
        direction = np.asarray(value["direction"], dtype=np.float64).reshape(-1)
        if direction.shape != (3,):
            raise ValueError(
                f"Pose '{pose_name}' arm entry '{sub}' direction must have 3 values, "
                f"got shape {direction.shape}."
            )
        side = "left_arm" if sub == "left_arm" else "right_arm"
        theta_a, theta_b = _arm_kinematics(side).ik_from_direction(  # type: ignore[arg-type]
            list(direction), near=None
        )
        return np.array([theta_a, theta_b], dtype=np.float64)

    arr = np.asarray(value, dtype=np.float64).reshape(-1)
    if arr.shape != (dof,):
        raise ValueError(
            f"Pose '{pose_name}' subsystem '{sub}' must have {dof} values, "
            f"got shape {arr.shape}."
        )
    return arr
