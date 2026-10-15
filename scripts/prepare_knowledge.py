"""Install the pinned Apache-2.0 MiniLM artifacts into ignored local storage."""

import argparse
import os
import subprocess
import tempfile
from pathlib import Path

from vasa.knowledge.embedding import (
    DEFAULT_MODEL_DIR,
    MODEL_BASE,
    MODEL_COMMIT,
    MODEL_FILES,
    reject_symlinks,
    verify_artifact,
    verify_model,
)


def prepare(directory: Path) -> None:
    reject_symlinks(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=directory) as temporary:
        staging = Path(temporary)
        for name, (upstream, expected) in MODEL_FILES.items():
            destination = directory / name
            reject_symlinks(destination)
            if destination.exists():
                verify_artifact(destination, expected)
                continue
            path = staging / name
            # curl honors the managed environment proxy/CA and bounds transfer time/size.
            subprocess.run(
                [
                    "curl",
                    "--fail",
                    "--location",
                    "--silent",
                    "--show-error",
                    "--proto",
                    "=https",
                    "--proto-redir",
                    "=https",
                    "--max-time",
                    "180",
                    "--max-filesize",
                    "104857600",
                    f"{MODEL_BASE}/{upstream}",
                    "--output",
                    str(path),
                ],
                check=True,
            )
            verify_artifact(path, expected)
        for name in MODEL_FILES:
            staged = staging / name
            if staged.exists():
                reject_symlinks(directory / name)
                os.replace(staged, directory / name)
        verify_model(directory)
        notice = directory / "NOTICE.txt"
        reject_symlinks(notice)
        notice.write_text(
            "sentence-transformers/all-MiniLM-L6-v2\n"
            f"Pinned upstream revision: {MODEL_COMMIT}\n"
            "License: Apache-2.0\n"
            "Source: https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2\n"
            "License text: https://www.apache.org/licenses/LICENSE-2.0\n"
            "All artifact SHA256 values are recorded in vasa.knowledge.embedding.MODEL_FILES.\n"
        )
    print("Verified CPU knowledge model ready (Apache-2.0, sentence-transformers/all-MiniLM-L6-v2)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=DEFAULT_MODEL_DIR)
    args = parser.parse_args()
    try:
        prepare(args.directory)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        raise SystemExit(
            "Knowledge model setup failed; check HTTPS connectivity and rerun setup"
        ) from error
