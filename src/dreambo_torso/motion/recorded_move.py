"""Load and play back recorded moves on the new Dreambo torso.

A move JSON has two accepted top-level shapes; the loader pivots both
into per-channel arrays internally.

**Per-frame** (dataset-card shape, used by the emotion library)::

    {
      "description": "Happy nod with small arm wave",
      "time": [0.00, 0.01, 0.02, ...],
      "set_target_data": [
        {"left_arm": [x, y, z], "right_arm": [x, y, z], "nose": [t, l, r]},
        {"left_arm": [x, y, z], "right_arm": [x, y, z], "nose": [t, l, r]},
        ...
      ]
    }

**Column-parallel** (legacy)::

    {
      "description": "...",
      "time": [0.00, 0.01, ...],
      "neck":      [[yaw, pitch, roll], ...],
      "left_arm":  [[x, y, z], ...],
      "right_arm": [[x, y, z], ...],
      "nose":      [[top, left, right], ...]
    }

Arm channels accept either form (in either shape):
  - ``3``-element direction vectors in the spherical 5-bar's internal
    frame. ``evaluate()`` resolves each frame to ``(theta_a, theta_b)``
    via ``DreamboArmKinematics.ik_from_direction``.
  - ``2``-element joint pairs ``(theta_a, theta_b)`` (legacy joint-space
    recordings; passed through unchanged).

Channels left out of the JSON are not driven during playback (their
subsystems hold their current position).

Old Stewart-platform datasets are no longer supported.
"""

import bisect
import json
import logging
import os
from glob import glob
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import numpy.typing as npt
from dreambo_torso_kinematics import DreamboArmKinematics
from modelscope.hub.snapshot_download import dataset_snapshot_download

from dreambo_torso.motion.move import JointTargets, Move

logger = logging.getLogger(__name__)


class _ModelscopeRevisionFilter(logging.Filter):
    """Silence ModelScope's harmless 'cannot confirm cached file revision' warning."""

    def filter(self, record: logging.LogRecord) -> bool:
        return (
            "We can not confirm the cached file is for revision"
            not in record.getMessage()
        )


logging.getLogger("modelscope").addFilter(_ModelscopeRevisionFilter())


# Joint-space DOFs for each subsystem. Arms can additionally arrive as
# 3-vector direction recordings, resolved through IK on playback — see
# ``_ARM_INPUT_DOFS``.
_SUBSYSTEM_DOFS: Dict[str, int] = {
    "neck": 3,
    "left_arm": 2,
    "right_arm": 2,
    "nose": 3,
}
_ARM_INPUT_DOFS = (2, 3)  # joint pair (legacy) | direction vector (recommended)

# Filenames that match the *.json glob but are dataset metadata, not moves.
# Filtering these out of ``RecordedMoves.process()`` keeps ``list_moves()``
# clean.
_RESERVED_JSON_NAMES = frozenset({"dataset_infos.json"})


def _lerp(
    a: npt.NDArray[np.float64], b: npt.NDArray[np.float64], alpha: float
) -> npt.NDArray[np.float64]:
    return a + (b - a) * alpha


def _extract_channels(move: Dict[str, Any], n_frames: int) -> Dict[str, Any]:
    """Pivot either shape into ``{channel_name: per-frame list}``.

    For the per-frame shape, ``set_target_data`` is a list of dicts and
    each subsystem must either appear in **every** frame or in **none**
    of them; partial channels raise so a half-recorded clip doesn't
    silently load with mismatched array lengths.
    """
    if "set_target_data" in move:
        frames: List[Dict[str, Any]] = list(move["set_target_data"])
        if len(frames) != n_frames:
            raise ValueError(
                f"Recorded move 'set_target_data' has {len(frames)} frames "
                f"but 'time' has {n_frames}."
            )
        out: Dict[str, Any] = {}
        for name in _SUBSYSTEM_DOFS:
            present = [name in f for f in frames]
            if not any(present):
                continue
            if not all(present):
                missing = [i for i, p in enumerate(present) if not p]
                raise ValueError(
                    f"Recorded move channel '{name}' is present in some frames "
                    f"but not others (first missing index: {missing[0]})."
                )
            out[name] = [f[name] for f in frames]
        return out

    # Legacy column-parallel layout.
    return {name: move[name] for name in _SUBSYSTEM_DOFS if name in move}


class RecordedMove(Move):
    """A move loaded from either the per-frame or column-parallel schema."""

    def __init__(self, move: Dict[str, Any], sound_path: Optional[Path] = None) -> None:
        """Validate the move dict and cache numpy views per channel."""
        if "time" not in move:
            raise ValueError("Recorded move is missing the required 'time' field.")

        self.description: str = str(move.get("description", ""))
        self.timestamps: List[float] = list(move["time"])
        if len(self.timestamps) < 2:
            raise ValueError("Recorded move needs at least two time samples.")

        n_frames = len(self.timestamps)
        per_channel = _extract_channels(move, n_frames)

        self._channels: Dict[str, npt.NDArray[np.float64]] = {}
        # Whether each arm channel is a direction vector (True) or a raw
        # joint pair (False). Resolved per-frame in ``evaluate()``.
        self._arm_is_direction: Dict[str, bool] = {}
        # Last successful (theta_a, theta_b) per arm — used as the `near`
        # hint for IK to keep solutions continuous across frames.
        self._last_arm_joints: Dict[str, Optional[tuple]] = {
            "left_arm": None,
            "right_arm": None,
        }
        self._arm_kinematics: Dict[str, DreamboArmKinematics] = {}

        for name, dof in _SUBSYSTEM_DOFS.items():
            if name not in per_channel:
                continue
            arr = np.asarray(per_channel[name], dtype=np.float64)
            if name in ("left_arm", "right_arm"):
                if (
                    arr.ndim != 2
                    or arr.shape[0] != n_frames
                    or arr.shape[1] not in _ARM_INPUT_DOFS
                ):
                    raise ValueError(
                        f"Recorded move channel '{name}' must have shape "
                        f"({n_frames}, 2) for joints or ({n_frames}, 3) for "
                        f"direction vectors, got {arr.shape}."
                    )
                self._arm_is_direction[name] = arr.shape[1] == 3
                if self._arm_is_direction[name]:
                    self._arm_kinematics[name] = (
                        DreamboArmKinematics.default_left()
                        if name == "left_arm"
                        else DreamboArmKinematics.default_right()
                    )
            else:
                if arr.shape != (n_frames, dof):
                    raise ValueError(
                        f"Recorded move channel '{name}' must have shape "
                        f"({n_frames}, {dof}), got {arr.shape}."
                    )
            self._channels[name] = arr

        self._sound_path = sound_path

    @property
    def duration(self) -> float:
        """Move duration in seconds (last timestamp minus first)."""
        return self.timestamps[-1] - self.timestamps[0]

    @property
    def sound_path(self) -> Optional[Path]:
        """Optional sound played alongside the move."""
        return self._sound_path

    def evaluate(self, t: float) -> JointTargets:
        """Linearly interpolate every recorded channel at time *t*.

        Arm channels stored as 3-vectors are interpolated in direction
        space, then resolved to ``(theta_a, theta_b)`` via the spherical
        5-bar IK using the last frame's joints as the ``near`` hint so the
        branch stays continuous.
        """
        if t >= self.timestamps[-1]:
            raise ValueError("Tried to evaluate recorded move beyond its duration.")

        index = bisect.bisect_right(self.timestamps, t)
        idx_prev = max(index - 1, 0)
        idx_next = min(index, len(self.timestamps) - 1)
        t_prev = self.timestamps[idx_prev]
        t_next = self.timestamps[idx_next]
        alpha = 0.0 if t_next == t_prev else (t - t_prev) / (t_next - t_prev)

        targets = JointTargets()
        for name, arr in self._channels.items():
            interp = _lerp(arr[idx_prev], arr[idx_next], alpha)
            if name in ("left_arm", "right_arm") and self._arm_is_direction.get(
                name, False
            ):
                near = self._last_arm_joints[name]
                theta_a, theta_b = self._arm_kinematics[name].ik_from_direction(
                    list(interp), near=near
                )
                joints = np.array([theta_a, theta_b], dtype=np.float64)
                self._last_arm_joints[name] = (theta_a, theta_b)
                setattr(targets, name, joints)
            else:
                setattr(targets, name, interp)
        return targets


# Default emotion-library dataset name used by both the daemon's
# startup prefetch and the dashboard play endpoints.
DEFAULT_EMOTION_LIBRARY = "tonylabs/dreambo-emotions-library"


def prefetch_dataset(ms_dataset_name: str) -> Optional[Path]:
    """Best-effort cloud refresh into the local ModelScope cache.

    Called by the daemon at startup so the cache reflects the latest
    revision before any ``/list`` or ``/play`` request arrives. The
    SDK's content-addressed cache means unchanged files aren't
    re-downloaded; only new or modified blobs cross the network.

    Returns the cache path on success, ``None`` when the fetch fails so
    callers can log without crashing. Subsequent :class:`RecordedMoves`
    constructions read from whatever the cache currently holds — they
    do not retry the network.
    """
    try:
        path = dataset_snapshot_download(ms_dataset_name)
        return Path(path)
    except Exception as exc:  # noqa: BLE001 — surface any backend failure as a warning
        logger.warning(
            "prefetch_dataset(%s) failed: %s; daemon will serve whatever "
            "the existing local cache contains.",
            ms_dataset_name,
            exc,
        )
        return None


class RecordedMoves:
    """Load a library of recorded moves from a ModelScope dataset.

    Resolves the local cache path **without** hitting the network on
    every construction — that keeps ``/list`` and ``/play`` responses
    fast. The daemon's startup hook (see
    :func:`prefetch_dataset`) is responsible for refreshing the cache
    against ModelScope; once started, this class only reads what is on
    disk.

    The only network access happens as a one-time bootstrap when no
    cache exists at all (first run, or daemon started offline before
    any prefetch succeeded).
    """

    def __init__(self, ms_dataset_name: str) -> None:
        """Resolve the dataset's local path and index every move it contains."""
        self.ms_dataset_name = ms_dataset_name
        try:
            self.local_path = dataset_snapshot_download(
                self.ms_dataset_name,
                local_files_only=True,
            )
        except Exception:
            logger.warning(
                "No local cache for %s yet; doing a one-time network fetch. "
                "The daemon's startup prefetch handles refreshes on subsequent "
                "launches.",
                ms_dataset_name,
            )
            self.local_path = dataset_snapshot_download(self.ms_dataset_name)
        self.moves: Dict[str, Any] = {}
        self.sounds: Dict[str, Optional[Path]] = {}
        self.process()

    def process(self) -> None:
        """Index every ``.json`` move (and any sibling ``.wav``) in the dataset."""
        move_paths_tmp = glob(f"{self.local_path}/*.json")
        data_dir = os.path.join(self.local_path, "data")
        if os.path.isdir(data_dir):
            move_paths_tmp.extend(glob(f"{data_dir}/*.json"))
        for move_path in (Path(p) for p in move_paths_tmp):
            # Skip metadata files that share the .json suffix but aren't moves.
            if move_path.name in _RESERVED_JSON_NAMES:
                continue
            move_name = move_path.stem
            with open(move_path, "r") as f:
                self.moves[move_name] = json.load(f)
            sound_path = move_path.with_suffix(".wav")
            self.sounds[move_name] = sound_path if sound_path.exists() else None

    def get(self, move_name: str) -> RecordedMove:
        """Return the named move as a playable :class:`RecordedMove`."""
        if move_name not in self.moves:
            raise ValueError(
                f"Move {move_name} not found in recorded moves library {self.ms_dataset_name}"
            )
        return RecordedMove(self.moves[move_name], self.sounds[move_name])

    def list_moves(self) -> List[str]:
        """List every move name available in the loaded library."""
        return list(self.moves.keys())
