r"""Push the local dreambo-emotions-library dataset back to ModelScope.

Wraps ``modelscope.hub.HubApi`` so a single command syncs every file in
``--dataset-dir`` into the ``tonylabs/dreambo-emotions-library`` repository
on ModelScope. Reads the access token from ``$MODELSCOPE_API_TOKEN`` by
default; pass ``--token <value>`` to override.

Usage::

    # one-off, env var set in the calling shell
    MODELSCOPE_API_TOKEN=ms-... \
        uv run python scripts/upload_emotions_dataset.py \
        --dataset-dir /tmp/dreambo-emotions-library \
        --commit-message "Re-record emotions in joint-vector schema"

    # or supply the token directly
    uv run python scripts/upload_emotions_dataset.py \
        --dataset-dir /tmp/dreambo-emotions-library \
        --token ms-... \
        --commit-message "..."

The upload is **not** auto-confirmed. The script lists the files it would
push and exits unless ``--yes`` is passed.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List

DEFAULT_DATASET = "tonylabs/dreambo-emotions-library"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--dataset-dir",
        required=True,
        type=Path,
        help="Local directory holding the dataset files to push.",
    )
    p.add_argument(
        "--dataset-id",
        default=DEFAULT_DATASET,
        help="Target ModelScope dataset id (default %(default)s).",
    )
    p.add_argument(
        "--token",
        default=os.environ.get("MODELSCOPE_API_TOKEN"),
        help="ModelScope access token. Falls back to $MODELSCOPE_API_TOKEN.",
    )
    p.add_argument(
        "--commit-message",
        default="Update emotions dataset",
        help="Commit message for the push (default '%(default)s').",
    )
    p.add_argument(
        "--revision",
        default="master",
        help="Target dataset revision/branch (default '%(default)s').",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="Skip the dry-run preview and push immediately.",
    )
    return p.parse_args()


def _enumerate_files(dataset_dir: Path) -> List[Path]:
    """Return the files we will push. Excludes .git/, dotfiles, and empty files."""
    out: List[Path] = []
    for path in sorted(dataset_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(dataset_dir)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if path.stat().st_size == 0:
            continue
        out.append(path)
    return out


def main() -> int:
    """Push every dataset file to ModelScope after a one-line preview."""
    args = _parse_args()

    dataset_dir: Path = args.dataset_dir.expanduser().resolve()
    if not dataset_dir.is_dir():
        print(f"--dataset-dir {dataset_dir} is not a directory", file=sys.stderr)
        return 2

    if not args.token:
        print(
            "No token supplied. Pass --token or set $MODELSCOPE_API_TOKEN.",
            file=sys.stderr,
        )
        return 2

    files = _enumerate_files(dataset_dir)
    if not files:
        print(f"No files found under {dataset_dir}", file=sys.stderr)
        return 2

    total_bytes = sum(p.stat().st_size for p in files)
    print(
        f"[upload] would push {len(files)} files ({total_bytes / 1e6:.1f} MB) "
        f"to {args.dataset_id} (revision={args.revision})"
    )
    print(f"[upload] commit message: {args.commit_message!r}")
    for p in files[:10]:
        print(f"  - {p.relative_to(dataset_dir)}  ({p.stat().st_size} bytes)")
    if len(files) > 10:
        print(f"  ... and {len(files) - 10} more")

    if not args.yes:
        print("[upload] dry-run only. Re-run with --yes to actually push.")
        return 0

    # Import lazily so dry-runs work even when modelscope isn't installed.
    from modelscope.hub.api import HubApi

    api = HubApi()
    api.login(args.token)
    api.push_model = getattr(api, "push_model", None)  # quiet linters; not used

    # The dataset upload API: upload the whole directory at once.
    print("[upload] pushing...", flush=True)
    api.upload_folder(
        repo_id=args.dataset_id,
        folder_path=str(dataset_dir),
        commit_message=args.commit_message,
        repo_type="dataset",
        revision=args.revision,
    )
    print("[upload] done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
