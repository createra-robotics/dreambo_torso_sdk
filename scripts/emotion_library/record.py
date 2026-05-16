r"""Puppet-record an emotion clip by moving the arms and nose by hand.

Disables torque on the Feetech arm (SM40BL) and nose (STS3025BL) servos so
they go limp, sleeps a short countdown, then samples joint positions at
``--fps`` until the operator presses **'r'** to stop. The recording is
written as one new JSON entry in the dataset directory (overwriting an
existing skeleton if present). Press **'q'** or Ctrl-C to abort without
saving.

Arm joints are converted to upper-arm direction vectors via
``DreamboArmKinematics.direction()`` and stored in the new emotion-library
schema (see ``dreambo_torso/motion/recorded_move.py``)::

    {
      "description": "...",
      "fps": 100,
      "time": [...],
      "left_arm":  [[x, y, z], ...],     # direction vectors
      "right_arm": [[x, y, z], ...],
      "nose":      [[top, left, right], ...]
    }

The neck channel is **not** recorded — the Damiao MIT-mode neck would fight
a manual move. Add ``--neck`` later if the neck-recording question is
resolved (e.g. by writing kp=0 kd=0 to the neck for the duration of capture).

Usage::

    uv run python scripts/emotion_library/record.py \
        --emotion yes1 \
        --description "You nod to confirm what your interlocutor said." \
        --play-wav

Once recording stops via **'r'**, the saved JSON is also pushed to the
``tonylabs/dreambo-emotions-library`` dataset on ModelScope. Set
``$MODELSCOPE_API_TOKEN`` (or pass ``--modelscope-token``) for the upload
to succeed; pass ``--no-upload`` to keep the recording local only.

The output file is ``<dataset-dir>/<emotion>.json``. ``--dataset-dir``
defaults to ``scripts/emotion_library/dataset/`` (auto-created). ``.wav``
cues are looked up under the fixed sibling ``scripts/emotion_library/sound/``
directory. Both folders are gitignored by the SDK repo. When
``--play-wav`` is set, the matching wav plays once at recording start so
the operator can sync motion to the audio cue.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import select
import subprocess
import sys
import termios
import time
import tty
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

from dotenv import load_dotenv
from dreambo_motor_controller import DreamboMotorController
from dreambo_torso_kinematics import DreamboArmKinematics

# Load environment variables from a ``.env`` file (repo root, then script
# dir, then cwd) before any os.environ reads — most importantly
# ``MODELSCOPE_API_TOKEN`` for the post-record upload step. Missing files
# are silent no-ops; existing $env vars are not overwritten.
for _env_path in (
    Path(__file__).resolve().parents[2] / ".env",  # repo root
    Path(__file__).resolve().parent / ".env",  # scripts/emotion_library
    Path.cwd() / ".env",  # caller's cwd
):
    if _env_path.is_file():
        load_dotenv(_env_path, override=False)

# Fixed pre-record countdown (seconds) — long enough to drop your hands
# onto the arms after starting the script, short enough that nobody waits.
COUNTDOWN_SECONDS = 3.0

# Keys understood by the sample loop.
KEY_STOP_AND_SAVE = "r"
KEY_ABORT = "q"

# Default dataset directory: a sibling of this script. Auto-created when
# missing so the operator does not have to pre-mkdir on a fresh Pi.
DEFAULT_DATASET_DIR = Path(__file__).resolve().parent / "dataset"
# Audio cues (matching <emotion>.wav per recording) live here
DEFAULT_SOUND_DIR = Path(__file__).resolve().parent / "sound"

# ModelScope dataset that receives newly-recorded clips. Pressing 'r' saves
# locally and then pushes the JSON to this repo so the rest of the fleet
# can pull the same library.
DEFAULT_MODELSCOPE_REPO = "tonylabs/dreambo-emotions-library"
DEFAULT_MODELSCOPE_REVISION = "master"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--emotion",
        required=True,
        help="Emotion clip name, e.g. 'yes1'. Used for the output .json filename.",
    )
    p.add_argument(
        "--dataset-dir",
        type=Path,
        default=DEFAULT_DATASET_DIR,
        help="Directory the .json is written to. Auto-created when missing. Default: %(default)s.",
    )
    p.add_argument(
        "--serial-port",
        default="/dev/ttyACM0",
        help="Feetech serial port for arms + nose (default %(default)s).",
    )
    p.add_argument(
        "--can-bus",
        default="can0",
        help="SocketCAN bus for the neck Damiao motors (default %(default)s).",
    )
    p.add_argument(
        "--max-duration",
        type=float,
        default=60.0,
        help="Safety cap in seconds — recording stops automatically if the operator forgets to press 'r' (default %(default)s).",
    )
    p.add_argument(
        "--fps",
        type=int,
        default=100,
        help="Sampling frequency (default %(default)s Hz).",
    )
    p.add_argument(
        "--description", default="", help="Description text stored in the JSON."
    )
    p.add_argument(
        "--play-wav",
        action="store_true",
        help="Play the matching .wav at recording start as a timing cue.",
    )
    p.add_argument(
        "--keep-torque",
        action="store_true",
        help="Skip the torque-off step (useful for headless dry-runs against the sim).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write the output file; print the would-be summary instead.",
    )
    p.add_argument(
        "--no-upload",
        action="store_true",
        help="Skip the ModelScope upload after pressing 'r'. The JSON is still written locally.",
    )
    p.add_argument(
        "--modelscope-token",
        default=os.environ.get("MODELSCOPE_API_TOKEN"),
        help="ModelScope access token. Falls back to $MODELSCOPE_API_TOKEN.",
    )
    p.add_argument(
        "--modelscope-repo-id",
        default=DEFAULT_MODELSCOPE_REPO,
        help="Target ModelScope dataset id (default %(default)s).",
    )
    p.add_argument(
        "--modelscope-revision",
        default=DEFAULT_MODELSCOPE_REVISION,
        help="Target ModelScope dataset revision/branch (default %(default)s).",
    )
    return p.parse_args()


def _upload_to_modelscope(
    json_path: Path,
    repo_id: str,
    revision: str,
    token: Optional[str],
    emotion: str,
) -> bool:
    """Push ``json_path`` to a ModelScope dataset. Returns True on success.

    Failures are surfaced as warnings — the locally-saved JSON is the
    source of truth, so a flaky network shouldn't crash the recording
    flow. Missing token is also treated as a soft skip with a hint.
    """
    if not token:
        print(
            "[record] no ModelScope token — set $MODELSCOPE_API_TOKEN or pass "
            "--modelscope-token to enable upload (or --no-upload to silence this).",
            file=sys.stderr,
        )
        return False

    try:
        from modelscope.hub.api import HubApi
    except ImportError as exc:
        print(
            f"[record] modelscope not installed; skipping upload ({exc})",
            file=sys.stderr,
        )
        return False

    try:
        api = HubApi()
        api.login(token)
        print(
            f"[record] uploading {json_path.name} -> {repo_id}@{revision}", flush=True
        )
        api.upload_file(
            path_or_fileobj=str(json_path),
            path_in_repo=json_path.name,
            repo_id=repo_id,
            repo_type="dataset",
            commit_message=f"Re-record {emotion} via record.py",
            revision=revision,
        )
    except Exception as exc:  # noqa: BLE001 — upload errors must not lose the local recording
        print(f"[record] ModelScope upload failed: {exc}", file=sys.stderr)
        return False

    print("[record] upload complete.", flush=True)
    return True


def _play_wav_async(wav_path: Path) -> Optional[subprocess.Popen]:
    """Best-effort cue playback. Falls back gracefully if no player exists."""
    for cmd in (["aplay", "-q", str(wav_path)], ["paplay", str(wav_path)]):
        try:
            return subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except FileNotFoundError:
            continue
    print(f"[record] no aplay/paplay available; skipping --play-wav for {wav_path}")
    return None


def _countdown(seconds: float) -> None:
    """Print a per-second countdown so the operator can prep the start pose."""
    whole = int(seconds)
    for remaining in range(whole, 0, -1):
        print(f"  {remaining}...", flush=True)
        time.sleep(1.0)
    leftover = seconds - whole
    if leftover > 0:
        time.sleep(leftover)


@contextlib.contextmanager
def _cbreak_stdin() -> Iterator[None]:
    """Put stdin into cbreak mode so single keypresses arrive without Enter.

    Falls through cleanly when stdin isn't a TTY (CI runs, piped input):
    callers must check ``stdin.isatty()`` themselves before relying on
    interactive keys.
    """
    if not sys.stdin.isatty():
        yield
        return
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _poll_key() -> Optional[str]:
    """Return one waiting keystroke (or None if stdin has nothing to read)."""
    if not sys.stdin.isatty():
        return None
    if select.select([sys.stdin], [], [], 0.0)[0]:
        return sys.stdin.read(1)
    return None


def _sample_loop(
    controller: DreamboMotorController,
    left_kin: DreamboArmKinematics,
    right_kin: DreamboArmKinematics,
    max_duration: float,
    period: float,
) -> Tuple[List[float], List[List[float]], List[List[float]], List[List[float]], str]:
    """Sample at ``period`` seconds until 'r' is pressed (save), 'q' (abort), or ``max_duration``.

    Returns the parallel time/left/right/nose arrays plus a stop reason
    string in ``{"r", "q", "timeout"}``.
    """
    times: List[float] = []
    left_dirs: List[List[float]] = []
    right_dirs: List[List[float]] = []
    nose_joints: List[List[float]] = []

    stop_reason = "timeout"
    t0 = time.time()
    next_tick = t0
    end = t0 + max_duration

    with _cbreak_stdin():
        while True:
            now = time.time()
            if now >= end:
                stop_reason = "timeout"
                break

            key = _poll_key()
            if key in (KEY_STOP_AND_SAVE, KEY_STOP_AND_SAVE.upper()):
                stop_reason = "r"
                break
            if key in (KEY_ABORT, KEY_ABORT.upper()):
                stop_reason = "q"
                break

            # Order per the controller:
            #   [left_pitch, left_yaw, right_pitch, right_yaw,
            #    nose_top, nose_left, nose_right]
            # DreamboArmKinematics expects (theta_a, theta_b) = (yaw, pitch)
            # per the ground-axis convention in geometry.rs, so swap pitch/yaw
            # on each side before calling direction().
            positions = controller.read_all_positions()
            l_pitch, l_yaw, r_pitch, r_yaw, n_top, n_left, n_right = positions
            l_dir = left_kin.direction(l_yaw, l_pitch)
            r_dir = right_kin.direction(r_yaw, r_pitch)

            times.append(now - t0)
            left_dirs.append(list(l_dir))
            right_dirs.append(list(r_dir))
            nose_joints.append([float(n_top), float(n_left), float(n_right)])

            next_tick += period
            sleep_for = next_tick - time.time()
            if sleep_for > 0:
                time.sleep(sleep_for)

    return times, left_dirs, right_dirs, nose_joints, stop_reason


def main() -> int:
    """Drive the recording flow end-to-end."""
    args = _parse_args()

    if args.fps <= 0:
        print("--fps must be positive", file=sys.stderr)
        return 2
    if args.max_duration <= 0:
        print("--max-duration must be positive", file=sys.stderr)
        return 2

    dataset_dir: Path = args.dataset_dir.expanduser().resolve()
    if dataset_dir.exists() and not dataset_dir.is_dir():
        print(
            f"--dataset-dir {dataset_dir} exists but is not a directory",
            file=sys.stderr,
        )
        return 2
    dataset_dir.mkdir(parents=True, exist_ok=True)

    out_path = dataset_dir / f"{args.emotion}.json"
    wav_path = DEFAULT_SOUND_DIR / f"{args.emotion}.wav"

    if not wav_path.exists():
        print(
            f"[record] warning: no matching {wav_path.name} in {DEFAULT_SOUND_DIR}",
            file=sys.stderr,
        )

    # If the skeleton JSON already exists with a description, use it as the
    # default so the wizard does not have to retype --description on every
    # invocation. The CLI flag still wins when explicitly supplied.
    description = args.description
    if out_path.exists() and not description:
        try:
            existing = json.loads(out_path.read_text())
        except Exception:
            existing = {}
        description = str(existing.get("description", ""))

    print(
        f"[record] connecting to {args.serial_port} (can_bus={args.can_bus})",
        flush=True,
    )
    controller = DreamboMotorController(args.serial_port, args.can_bus)

    torque_was_toggled = False
    if not args.keep_torque:
        print("[record] disabling arm + nose torque (neck untouched)", flush=True)
        controller.enable_arms(False)
        controller.enable_nose(False)
        torque_was_toggled = True

    try:
        return _do_recording(
            controller, args, dataset_dir, out_path, wav_path, description
        )
    finally:
        # Restore servo torque so the daemon (which infers its motor-control
        # mode by reading the live torque flag) doesn't come up in Disabled
        # mode the next time it's started. Runs on success, abort, exception,
        # and Ctrl-C.
        if torque_was_toggled:
            try:
                controller.enable_arms(True)
                controller.enable_nose(True)
                print("[record] arm + nose torque re-enabled", flush=True)
            except Exception as e:
                print(
                    f"[record] WARNING: failed to re-enable torque on exit: {e}",
                    file=sys.stderr,
                )


def _do_recording(
    controller: DreamboMotorController,
    args: argparse.Namespace,
    dataset_dir: Path,
    out_path: Path,
    wav_path: Path,
    description: str,
) -> int:
    """Inner body of main(): pre-record prep + sample loop + save.

    Lives in its own function so ``main()`` can wrap the call in a
    ``try/finally`` that always restores servo torque on exit.
    """
    del dataset_dir  # not used here; kept for future hooks
    left_kin = DreamboArmKinematics.default_left()
    right_kin = DreamboArmKinematics.default_right()
    period = 1.0 / args.fps

    print(
        f"[record] move the arms / nose into the START pose for '{args.emotion}'.",
        flush=True,
    )
    print("[record] recording begins in:", flush=True)
    _countdown(COUNTDOWN_SECONDS)

    wav_proc: Optional[subprocess.Popen] = None
    if args.play_wav and wav_path.exists():
        wav_proc = _play_wav_async(wav_path)

    if sys.stdin.isatty():
        print(
            f"[record] RECORDING at {args.fps} Hz. "
            f"Press '{KEY_STOP_AND_SAVE}' to stop+save, "
            f"'{KEY_ABORT}' to abort. "
            f"(safety cap {args.max_duration:.0f}s)",
            flush=True,
        )
    else:
        print(
            f"[record] stdin is not a TTY — keypress capture disabled. "
            f"Recording until safety cap {args.max_duration:.0f}s.",
            flush=True,
        )
    times, left, right, nose, stop_reason = _sample_loop(
        controller,
        left_kin,
        right_kin,
        args.max_duration,
        period,
    )

    if wav_proc is not None:
        try:
            wav_proc.terminate()
        except Exception:
            pass

    if not times:
        print("[record] no frames captured; nothing to save.", file=sys.stderr)
        return 1

    print(
        f"[record] stopped via {stop_reason!r}: "
        f"captured {len(times)} frames over {times[-1]:.3f}s",
        flush=True,
    )

    if stop_reason == "q":
        print("[record] aborted; nothing written.", flush=True)
        return 0

    # Per the dataset schema: one row per emotion with `set_target_data`
    # as a list of per-frame dicts. The viewer renders these as one
    # collapsible column. `fps` is dropped — `time[]` already gives the
    # exact per-frame timing, so storing the nominal rate would diverge
    # from the actual cadence on slow ticks.
    set_target_data = [
        {"left_arm": left[i], "right_arm": right[i], "nose": nose[i]}
        for i in range(len(times))
    ]
    payload = {
        "description": description,
        "time": times,
        "set_target_data": set_target_data,
    }

    if args.dry_run:
        print(f"[record] dry-run: would write {out_path}")
        print(f"  frames={len(times)} duration={times[-1]:.3f}s")
        print(f"  first frame: {set_target_data[0]}")
        return 0

    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"[record] wrote {out_path}", flush=True)

    # Upload only when the operator deliberately stopped via 'r'. A timeout
    # save is left local so the operator can inspect/redo before publishing.
    if stop_reason == "r" and not args.no_upload:
        _upload_to_modelscope(
            json_path=out_path,
            repo_id=args.modelscope_repo_id,
            revision=args.modelscope_revision,
            token=args.modelscope_token,
            emotion=args.emotion,
        )
    elif stop_reason != "r":
        print(
            "[record] stopped via timeout — skipping ModelScope upload. "
            "Re-run and press 'r' once the clip looks right.",
            flush=True,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
