"""Load and play back recorded moves on the new Dreambo torso.

The on-disk schema is a single JSON file with parallel arrays per
subsystem; each subsystem array is optional. A move JSON looks like::

    {
      "description": "Happy nod with small arm wave",
      "fps": 100,
      "time": [0.00, 0.01, 0.02, ...],
      "neck":      [[yaw, pitch, roll], ...],
      "left_arm":  [[theta_a, theta_b], ...],
      "right_arm": [[theta_a, theta_b], ...],
      "nose":      [[top, left, right], ...]
    }

Channels left out of the JSON are not driven during playback (their
subsystems hold their current position).

Old Stewart-platform datasets are no longer supported; this loader
expects the new shape and will raise on anything else.
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
from modelscope.hub.snapshot_download import dataset_snapshot_download

from dreambo_torso.motion.move import JointTargets, Move

logger = logging.getLogger(__name__)


class _ModelscopeRevisionFilter(logging.Filter):
    """Silence ModelScope's harmless 'cannot confirm cached file revision' warning."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "We can not confirm the cached file is for revision" not in record.getMessage()


logging.getLogger("modelscope").addFilter(_ModelscopeRevisionFilter())


_SUBSYSTEM_DOFS: Dict[str, int] = {
    "neck": 3,
    "left_arm": 2,
    "right_arm": 2,
    "nose": 3,
}


def _lerp(a: npt.NDArray[np.float64], b: npt.NDArray[np.float64], alpha: float) -> npt.NDArray[np.float64]:
    return a + (b - a) * alpha


class RecordedMove(Move):
    """A move loaded from the column-parallel JSON schema."""

    def __init__(self, move: Dict[str, Any], sound_path: Optional[Path] = None) -> None:
        """Validate the move dict and cache numpy views per channel."""
        if "time" not in move:
            raise ValueError("Recorded move is missing the required 'time' field.")

        self.description: str = str(move.get("description", ""))
        self.timestamps: List[float] = list(move["time"])
        if len(self.timestamps) < 2:
            raise ValueError("Recorded move needs at least two time samples.")

        n_frames = len(self.timestamps)
        self._channels: Dict[str, npt.NDArray[np.float64]] = {}
        for name, dof in _SUBSYSTEM_DOFS.items():
            if name not in move:
                continue
            arr = np.asarray(move[name], dtype=np.float64)
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
        """Linearly interpolate every recorded channel at time *t*."""
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
            setattr(targets, name, interp)
        return targets


class RecordedMoves:
    """Load a library of recorded moves from a ModelScope dataset.

    Uses the local cache first; falls back to a network download.
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
                f"Dataset {ms_dataset_name} not in cache, downloading from ModelScope. "
                "This may take a moment."
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
