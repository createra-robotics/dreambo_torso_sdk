"""Named poses for the Dreambo torso, loaded from a YAML config file."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import numpy.typing as npt
import yaml

_SUBSYSTEM_DOFS: Dict[str, int] = {
    "neck": 3,
    "left_arm": 2,
    "right_arm": 2,
    "nose": 3,
}


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
            raise KeyError(
                f"Unknown pose '{name}'. Known: {sorted(self.poses)}"
            )
        return self.poses[name]

    def __contains__(self, name: str) -> bool:
        return name in self.poses

    @classmethod
    def load(cls, path: str | Path) -> "NamedPoses":
        """Load named poses from a YAML file at *path*."""
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
                arr = np.asarray(body[sub], dtype=np.float64).reshape(-1)
                if arr.shape != (dof,):
                    raise ValueError(
                        f"Pose '{name}' subsystem '{sub}' must have {dof} values, "
                        f"got shape {arr.shape}."
                    )
                setattr(pose, sub, arr)
            poses[name] = pose
        return cls(poses=poses)
