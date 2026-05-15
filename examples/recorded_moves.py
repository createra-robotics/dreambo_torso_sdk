"""Play every move from a v2 recorded-moves dataset in a loop.

Run:

```bash
python recorded_moves.py --dataset path/or/modelscope-id
```

The legacy ``tonylabs/dreambo-dance-library`` /
``tonylabs/dreambo-emotions-library`` datasets are *not* compatible
with the new Dreambo torso. Re-record moves against the new joint
schema (``neck`` / ``left_arm`` / ``right_arm`` / ``nose``) and point
``--dataset`` at the result.
"""

# START doc_example

import argparse

from dreambo_torso import Dreambo
from dreambo_torso.motion.recorded_move import RecordedMove, RecordedMoves


def main(dataset_path: str) -> None:
    """Cycle through every move in *dataset_path* until interrupted."""
    recorded_moves = RecordedMoves(dataset_path)

    print("Connecting to Dreambo torso...")
    with Dreambo() as dreambo:
        print("Connected. Starting playback loop.\n")
        try:
            while True:
                for move_name in recorded_moves.list_moves():
                    move: RecordedMove = recorded_moves.get(move_name)
                    print(f"Playing move: {move_name}: {move.description}\n")
                    dreambo.play_move(move, initial_goto_duration=1.0)
        except KeyboardInterrupt:
            print("\n Sequence interrupted by user. Shutting down.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Play every move from a recorded-moves dataset on the Dreambo torso."
    )
    parser.add_argument(
        "--dataset",
        type=str,
        required=True,
        help="Local path or ModelScope dataset id of a v2 recorded-moves library.",
    )
    args = parser.parse_args()
    main(args.dataset)

# END doc_example
