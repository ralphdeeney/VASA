"""Operator terminal only: create private web SMTP configuration without echoing a key."""

import getpass
import os
import pwd
import re
import stat
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

ROOT = Path("/opt/vasa")
FAILURE_CODES = frozenset(
    {
        "wrong_user",
        "unsafe_project",
        "unsafe_private_directory",
        "existing_configuration_preserved",
        "private_path_not_ignored",
        "private_terminal_required",
        "invalid_key_format",
        "unsafe_file_mode",
        "existing_configuration_required",
    }
)


class ConfigurationRefused(Exception):
    """Only fixed, secret-free failure codes may cross the CLI boundary."""


def smtp_content(key: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:+-]{16,4096}", key) is None:
        raise ConfigurationRefused("invalid_key_format")
    return (
        "VASA_SMTP_HOST=smtp.reloop.sh\n"
        "VASA_SMTP_PORT=587\n"
        f"VASA_SMTP_USERNAME='{key}'\n"
        f"VASA_SMTP_PASSWORD='{key}'\n"
        "VASA_SMTP_SENDER='VASA <noreply@send.litatech.xyz>'\n"
        "VASA_SMTP_STARTTLS=true\n"
        "VASA_SMTP_DELIVERY_VERIFIED=false\n"
    )


def configure(root: Path, *, secret: str | None = None, delivery_verified: bool = False) -> bool:
    uid = os.getuid()
    if uid == 0 or pwd.getpwuid(uid).pw_name != "vasa-builder":
        raise ConfigurationRefused("wrong_user")
    if root.resolve() != root or not root.is_dir() or root.stat().st_uid != uid:
        raise ConfigurationRefused("unsafe_project")
    private = root / ".local"
    if (
        private.is_symlink()
        or not private.is_dir()
        or private.stat().st_uid != uid
        or private.stat().st_mode & 0o022
    ):
        raise ConfigurationRefused("unsafe_private_directory")
    for command, expected in (
        (["git", "check-ignore", "--quiet", "--", ".local/smtp.env"], 0),
        (["git", "ls-files", "--error-unmatch", "--", ".local/smtp.env"], 1),
    ):
        result = subprocess.run(command, cwd=root, capture_output=True, timeout=10, check=False)
        if result.returncode != expected:
            raise ConfigurationRefused("private_path_not_ignored")
    path = private / "smtp.env"
    if path.exists() or path.is_symlink():
        if (
            secret is not None
            and path.is_file()
            and not path.is_symlink()
            and path.stat().st_uid == uid
            and stat.S_IMODE(path.stat().st_mode) == 0o600
            and path.stat().st_size <= 16384
        ):
            previous = smtp_content(secret)
            desired = (
                previous.replace("VERIFIED=false", "VERIFIED=true")
                if delivery_verified
                else previous
            )
            current = path.read_text()
            if current == desired:
                return False
            if delivery_verified and current == previous:
                original = path.stat()
                fd, name = tempfile.mkstemp(prefix=".smtp-attest-", dir=private)
                temporary = Path(name)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as stream:
                        stream.write(desired)
                        stream.flush()
                        os.fsync(stream.fileno())
                    if (
                        path.is_symlink()
                        or path.stat().st_ino != original.st_ino
                        or path.read_text() != previous
                    ):
                        raise ConfigurationRefused("existing_configuration_preserved")
                    os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)
                return True
        # Never overwrite an existing credential, operator option or attestation.
        raise ConfigurationRefused("existing_configuration_preserved")
    if delivery_verified:
        raise ConfigurationRefused("existing_configuration_required")
    if secret is None:
        if not sys.stdin.isatty() or not sys.stderr.isatty():
            raise ConfigurationRefused("private_terminal_required")
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            key = getpass.getpass("Reloop API key (hidden; never paste into chat): ")
    else:
        # Only the reviewed Actions stdin payload calls this internal API. The
        # standalone command exposes no argument/environment option for a key.
        key = secret
    content = smtp_content(key)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            if stat.S_IMODE(os.fstat(stream.fileno()).st_mode) != 0o600:
                raise ConfigurationRefused("unsafe_file_mode")
    except BaseException:
        # Remove only the newly created file; never an existing operator file.
        path.unlink(missing_ok=True)
        raise
    return True


def main() -> int:
    try:
        configure(ROOT)
    except ConfigurationRefused as error:
        code = str(error)
        print(
            "SMTP_PRIVATE_CONFIG_FAILED="
            + (code if code in FAILURE_CODES else "configuration_unavailable")
        )
        return 1
    except Exception:
        print("SMTP_PRIVATE_CONFIG_FAILED=configuration_unavailable")
        return 1
    print("VASA_SMTP_PRIVATE_CONFIG_WRITTEN")
    print("SMTP_MAILBOX_VERIFIED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
