"""Migrate a Hugging Face dataset to a ModelScope dataset.

Downloads every file from the source HF dataset into a local cache and
re-uploads the snapshot to the destination ModelScope dataset, preserving
the on-disk layout (top-level files, ``data/``, etc.).

Defaults migrate the Reachy Mini emotions library to the Dreambo Torso
emotions library. Override with ``--source`` / ``--dest`` to reuse for
other libraries (dances, etc.).

Auth:
  - HF: ``HF_TOKEN`` env var (only needed for private/gated sources).
  - ModelScope: ``MODELSCOPE_API_TOKEN`` env var, or pass ``--ms-token``.
    Get one at https://modelscope.cn/my/myaccesstoken

Usage:
  python scripts/migrate_hf_to_modelscope.py \\
      --source pollen-robotics/reachy-mini-emotions-library \\
      --dest   tonylabs/dreambo-emotions-library
"""

from __future__ import annotations

import argparse
import os
import sys

from huggingface_hub import snapshot_download
from modelscope.hub.api import HubApi


def migrate(
    source: str,
    dest: str,
    ms_token: str | None,
    commit_message: str,
    ignore: list[str] | None,
) -> None:
    print(f"[1/2] Downloading HF dataset: {source}")
    local_path = snapshot_download(repo_id=source, repo_type="dataset")
    print(f"      cached at: {local_path}")

    print(f"[2/2] Uploading to ModelScope dataset: {dest}")
    api = HubApi()
    result = api.upload_folder(
        repo_id=dest,
        folder_path=local_path,
        repo_type="dataset",
        token=ms_token,
        commit_message=commit_message,
        ignore_patterns=ignore,
    )
    if result is None:
        print("      nothing to upload — destination already up to date.")
    else:
        print("      upload complete.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        default="pollen-robotics/reachy-mini-emotions-library",
        help="HF dataset repo id (default: %(default)s)",
    )
    parser.add_argument(
        "--dest",
        default="tonylabs/dreambo-emotions-library",
        help="ModelScope dataset repo id (default: %(default)s)",
    )
    parser.add_argument(
        "--ms-token",
        default=os.environ.get("MODELSCOPE_API_TOKEN"),
        help="ModelScope access token (or set MODELSCOPE_API_TOKEN).",
    )
    parser.add_argument(
        "--commit-message",
        default=None,
        help="Commit message for the upload. Defaults to a 'Migrate from <source>' message.",
    )
    parser.add_argument(
        "--ignore",
        action="append",
        default=None,
        help="Glob to skip during upload (repeatable). Common: '.git*', '.cache*'.",
    )
    args = parser.parse_args()

    if args.commit_message is None:
        args.commit_message = f"Migrate from huggingface.co/datasets/{args.source}"

    # `.git*` and HF metadata cruft don't belong in the destination.
    ignore = list(args.ignore) if args.ignore else []
    for default in (".git*", ".cache*", ".huggingface*"):
        if default not in ignore:
            ignore.append(default)

    if not args.ms_token:
        print(
            "warning: no ModelScope token provided. If the destination is private, "
            "upload will fail. Pass --ms-token or set MODELSCOPE_API_TOKEN.",
            file=sys.stderr,
        )

    migrate(
        source=args.source,
        dest=args.dest,
        ms_token=args.ms_token,
        commit_message=args.commit_message,
        ignore=ignore,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())