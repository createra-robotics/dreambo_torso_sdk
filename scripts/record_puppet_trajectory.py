r"""Record a hand-puppeteered trajectory in the Dreambo robot emotions/dances format.

Puts Dreambo robot into compliant (gravity-compensated) mode so you can physically
pose the head by hand, polls the live head pose + antenna joints + body yaw at a
fixed rate, and writes the captured trajectory to a JSON file.

The resulting JSON can be played back with::

    from dreambo_torso.motion.recorded_move import RecordedMove
    move = RecordedMove(json.load(open("my_move.json")))
    reachy.play_move(move, initial_goto_duration=1.0)

Usage::

    python scripts/record_puppet_trajectory.py \\
        --output my_moves/curious.json \\
        --description "curious head tilt" \\
        --rate 50

Press Ctrl+C to stop recording. The robot is stiffened automatically on exit.

Note: gravity compensation requires the daemon to be running with the Placo
kinematics engine::

    reachy-mini-daemon --kinematics-engine Placo
"""

import argparse
import json
import time
from pathlib import Path
from typing import Any

from dreambo_torso import Dreambo


def record(
    output: Path,
    description: str,
    rate_hz: float,
    duration: float | None,
    countdown: int,
) -> None:
    """Run the compliant-mode recording loop and save to JSON."""
    period = 1.0 / rate_hz
    timestamps: list[float] = []
    trajectory: list[dict[str, Any]] = []

    print(f"Connecting to Dreambo robot torso... (output: {output})")
    with Dreambo(media_backend="no_media") as mini:
        try:
            mini.enable_gravity_compensation()
            print("Gravity compensation enabled — torso is now compliant.")

            for i in range(countdown, 0, -1):
                print(f"Recording starts in {i}...")
                time.sleep(1.0)

            if duration is not None:
                print(f"Recording {duration:.1f}s at {rate_hz:.0f} Hz...")
            else:
                print(f"Recording at {rate_hz:.0f} Hz. Press Ctrl+C to stop.")

            t0 = time.monotonic()
            next_tick = t0
            while True:
                t = time.monotonic() - t0
                if duration is not None and t >= duration:
                    break

                head = mini.get_current_head_pose()
                head_joints, antennas = mini.get_current_joint_positions()
                # head_joints layout: [body_yaw, stewart_1, ..., stewart_6]
                body_yaw = float(head_joints[0])

                timestamps.append(t)
                trajectory.append(
                    {
                        "head": head.tolist(),
                        "antennas": list(antennas),
                        "body_yaw": body_yaw,
                        "check_collision": False,
                    }
                )

                next_tick += period
                sleep_for = next_tick - time.monotonic()
                if sleep_for > 0:
                    time.sleep(sleep_for)
                else:
                    # Fell behind schedule; reset cadence to avoid bursting.
                    next_tick = time.monotonic()
        except KeyboardInterrupt:
            print()
        finally:
            mini.disable_gravity_compensation()
            print("Reachy Mini is stiff again.")

    if not trajectory:
        print("No frames captured; nothing to save.")
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w") as f:
        json.dump(
            {
                "description": description,
                "time": timestamps,
                "set_target_data": trajectory,
            },
            f,
        )
    print(
        f"Saved {len(trajectory)} frames "
        f"({timestamps[-1]:.2f}s @ ~{len(trajectory) / max(timestamps[-1], 1e-6):.1f} Hz) "
        f"to {output}"
    )


def main() -> None:
    """Parse CLI arguments and start recording."""
    parser = argparse.ArgumentParser(
        description="Record a hand-puppeteered trajectory from a compliant Reachy Mini."
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write the trajectory JSON to (e.g. my_moves/curious.json).",
    )
    parser.add_argument(
        "--description",
        type=str,
        required=True,
        help="Human-readable description stored in the JSON (e.g. 'curious head tilt').",
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=50.0,
        help="Sampling rate in Hz (default: 50, matches the daemon control loop).",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Optional fixed recording duration in seconds. If omitted, record until Ctrl+C.",
    )
    parser.add_argument(
        "--countdown",
        type=int,
        default=3,
        help="Seconds to wait before recording starts (default: 3).",
    )
    args = parser.parse_args()
    record(args.output, args.description, args.rate, args.duration, args.countdown)


if __name__ == "__main__":
    main()
