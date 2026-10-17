"""Prepare pinned Calls source with reviewed patches and immutable isolated caches."""

import argparse
import hashlib
import io
import json
import secrets
import ssl
import subprocess
import tarfile
import tempfile
from pathlib import Path

COMMIT = "e21ce0dd7634f3047410c893b5e4d1c082034b84"
REPOSITORY = "https://github.com/luis-kovi/evolution-go-calls.git"
ROOT = Path(__file__).resolve().parents[1]
LOG_PATCH_SHA256 = "f73b15b2dce8572e91ee923faa27e9a30d3624eab244517fd412459a1cb5b91f"
POOL_PATCH_SHA256 = "daba5ba8222345396ce5934e8a7ef07c353a4ed73fedcbeb785c75a6fb0b5361"


def fingerprints(directory: Path) -> dict[str, str]:
    return {
        str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def prepare(
    source: Path | None, *, destination: Path | None = None, isolated: bool = False
) -> None:
    local = ROOT / ".local"
    local.mkdir(mode=0o700, exist_ok=True)
    expected = local / ("evolution-pool-source" if isolated else "evolution-source")
    if destination is not None and (not isolated or destination.absolute() != expected.absolute()):
        raise SystemExit("Explicit destination must be the isolated pool source directory.")
    if isolated and destination is None:
        raise SystemExit("Isolated preparation requires an explicit destination.")
    destination = expected
    manifest_path = local / (destination.name + "-manifest.json")
    if destination.is_symlink() or manifest_path.is_symlink():
        raise SystemExit("Source or manifest symlinks are forbidden.")
    patch_path = ROOT / "docker/evolution-log-redaction.patch"
    patch_sha = hashlib.sha256(patch_path.read_bytes()).hexdigest()
    if patch_sha != LOG_PATCH_SHA256:
        raise SystemExit("Logging patch checksum differs from the reviewed artifact.")
    patches = [(patch_path, patch_sha)]
    if isolated:
        pool_patch = ROOT / "docker/evolution-db-pool.patch"
        pool_sha = hashlib.sha256(pool_patch.read_bytes()).hexdigest()
        if pool_sha != POOL_PATCH_SHA256:
            raise SystemExit("Pool patch checksum differs from the reviewed artifact.")
        patches.append((pool_patch, pool_sha))
    patch_records = {path.name: digest for path, digest in patches}
    if destination.exists():
        if not manifest_path.exists():
            raise SystemExit("Existing source has no manifest; preserve it before rebuilding.")
        manifest = json.loads(manifest_path.read_text())
        if (
            manifest["commit"] != COMMIT
            or manifest["patch_sha256"] != patch_sha
            or manifest["files"] != fingerprints(destination)
            or (isolated and manifest.get("patches") != patch_records)
        ):
            raise SystemExit(
                "Existing source differs from its verified manifest; preserve it first."
            )
        if isolated:
            print("Prepared verified isolated Calls source; no secrets accessed.")
            return
    else:
        with tempfile.TemporaryDirectory(prefix="vasa-calls-source-") as temporary:
            checkout = source or Path(temporary) / "checkout"
            if source is None:
                subprocess.run(["git", "init", "-q", str(checkout)], check=True)
                subprocess.run(
                    ["git", "-C", str(checkout), "fetch", "--depth", "1", REPOSITORY, COMMIT],
                    check=True,
                )
                subprocess.run(
                    ["git", "-C", str(checkout), "checkout", "-q", "--detach", "FETCH_HEAD"],
                    check=True,
                )
            head = subprocess.check_output(
                ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True
            ).strip()
            if head != COMMIT:
                raise SystemExit("Source HEAD is not the reviewed Calls commit.")
            archive = subprocess.check_output(
                ["git", "-C", str(checkout), "archive", COMMIT, "--", ".", ":!evolution-go"]
            )
            staging = Path(temporary) / "staging"
            staging.mkdir()
            with tarfile.open(fileobj=io.BytesIO(archive)) as source_tar:
                source_tar.extractall(staging, filter="data")
            for reviewed_patch, _ in patches:
                subprocess.run(
                    ["patch", "--batch", "--forward", "-p1", "-i", str(reviewed_patch)],
                    cwd=staging,
                    check=True,
                    stdout=subprocess.DEVNULL,
                )
            # Upstream ignores Go tests in Docker; retain them for actual source verification.
            (staging / ".dockerignore").write_text(".git\nevolution-go\n.env\n.env.*\n")
            import shutil

            shutil.copytree(staging, destination)
            manifest_path.write_text(
                json.dumps(
                    {
                        "commit": COMMIT,
                        "patch_sha256": patch_sha,
                        **({"patches": patch_records} if isolated else {}),
                        "files": fingerprints(destination),
                    },
                    indent=2,
                )
                + "\n"
            )
    # Preserve the cloud host's authoritative CA trust inside the build/runtime.
    # Go module checksums and HTTPS verification remain enabled.
    ca_path = ssl.get_default_verify_paths().cafile
    if ca_path is None:
        raise SystemExit("No trusted host CA bundle is available for verified downloads.")
    ca_bundle = Path(ca_path).read_bytes()
    if b"PRIVATE KEY" in ca_bundle or b"BEGIN CERTIFICATE" not in ca_bundle:
        raise SystemExit("Host CA bundle is not a certificate-only trust source.")
    (destination / "vasa-host-trust.pem").write_bytes(ca_bundle)
    manifest_path.write_text(
        json.dumps(
            {
                "commit": COMMIT,
                "patch_sha256": patch_sha,
                **({"patches": patch_records} if isolated else {}),
                "files": fingerprints(destination),
            },
            indent=2,
        )
        + "\n"
    )
    if isolated:
        print("Prepared verified isolated Calls source; no secrets accessed.")
        return
    from dotenv import dotenv_values

    vasa_file = local / "vasa.env"
    evolution_file = local / "evolution.env"
    if vasa_file.exists() != evolution_file.exists():
        raise SystemExit(
            "Only one service secret file exists; preserve and reconcile both securely."
        )
    if not vasa_file.exists():
        admin, stream, instance = (secrets.token_hex(32) for _ in range(3))
        for path, content in (
            (
                vasa_file,
                f"VASA_EVOLUTION_ADMIN_KEY={admin}\nVASA_EVOLUTION_STREAM_KEY={stream}\n"
                f"VASA_EVOLUTION_INSTANCE_KEY={instance}\n",
            ),
            (evolution_file, f"GLOBAL_API_KEY={admin}\nCALL_STREAM_SIGNING_KEY={stream}\n"),
        ):
            with path.open("x") as handle:
                path.chmod(0o600)
                handle.write(content)
    else:
        vasa, evolution = dotenv_values(vasa_file), dotenv_values(evolution_file)
        if vasa.get("VASA_EVOLUTION_ADMIN_KEY") != evolution.get("GLOBAL_API_KEY") or vasa.get(
            "VASA_EVOLUTION_STREAM_KEY"
        ) != evolution.get("CALL_STREAM_SIGNING_KEY"):
            raise SystemExit(
                "Service key bindings disagree; reconcile them without printing values."
            )
    print(f"Prepared verified Calls source {COMMIT}; secret files kept outside Git.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source", type=Path, help="Already verified checkout (otherwise fetch it)"
    )
    parser.add_argument(
        "--isolated", action="store_true", help="Prepare build source only; never access secrets"
    )
    parser.add_argument(
        "--destination", type=Path, help="Explicit .local/evolution-pool-source destination"
    )
    args = parser.parse_args()
    prepare(args.source, destination=args.destination, isolated=args.isolated)
