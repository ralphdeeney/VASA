"""Prepare pinned official Kokoro files only for the isolated streaming evaluation."""

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(".local/kokoro-streaming-official")
FILES = {
    "v10": {
        "repo": "hexgrad/Kokoro-82M",
        "revision": "f3ff3571791e39611d31c381e3a41a3af07b4987",
        "files": {
            "config.json": (
                "config.json",
                "5abb01e2403b072bf03d04fde160443e209d7a0dad49a423be15196b9b43c17f",
            ),
            "model.pth": (
                "kokoro-v1_0.pth",
                "496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4",
            ),
            "voice.pt": (
                "voices/af_heart.pt",
                "0ab5709b8ffab19bfd849cd11d98f75b60af7733253ad0d67b12382a102cb4ff",
            ),
        },
    },
    "v11": {
        "repo": "hexgrad/Kokoro-82M-v1.1-zh",
        "revision": "01e7505bd6a7a2ac4975463114c3a7650a9f7218",
        "files": {
            "config.json": (
                "config.json",
                "bc333efa5ce4ceff433c8c8e5d027a1eca0166001e4e4a62bea2d26ff7a46890",
            ),
            "model.pth": (
                "kokoro-v1_1-zh.pth",
                "b1d8410fa44dfb5c15471fd6c4225ea6b4e9ac7fa03c98e8bea47a9928476e2b",
            ),
            "voice.pt": (
                "voices/af_maple.pt",
                "f1211a6b94795d843cb7957568ccf2208e6ce76d2fbb36c7279b24e1be9b862f",
            ),
        },
    },
}


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def prepare() -> list[dict[str, str]]:
    records = []
    for version, spec in FILES.items():
        for local, (remote, expected) in spec["files"].items():
            target = ROOT / version / local
            if any(p.is_symlink() for p in (target.absolute(), *target.absolute().parents)):
                raise ValueError("symlink evaluation cache rejected")
            url = f"https://huggingface.co/{spec['repo']}/resolve/{spec['revision']}/{remote}"
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                staged = target.with_suffix(target.suffix + ".partial")
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
                        "600",
                        url,
                        "--output",
                        str(staged),
                    ],
                    check=True,
                )
                if digest(staged) != expected:
                    raise RuntimeError(f"checksum mismatch: {version}/{local}")
                staged.rename(target)
            if digest(target) != expected:
                raise RuntimeError(f"checksum mismatch: {version}/{local}")
            records.append({"file": str(target), "url": url, "sha256": expected})
    return records


if __name__ == "__main__":
    print(json.dumps(prepare(), indent=2))
