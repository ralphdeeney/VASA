"""Private, restore-verified backups before an explicitly approved Evolution update."""

import hashlib
import json
import os
import re
import subprocess
import uuid

DATABASES = {"app": "", "auth": "vasa_evolution_auth", "users": "vasa_evolution_users"}
SCHEMA_SQL = """SELECT md5(COALESCE(string_agg(table_name || ':' || column_name || ':' ||
 data_type || ':' || is_nullable, ',' ORDER BY table_name, ordinal_position), ''))
 FROM information_schema.columns WHERE table_schema='public'"""


def _query(ns, postgres, database, sql):
    return ns["run"](
        "docker",
        "exec",
        postgres,
        "sh",
        "-ec",
        'exec psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "${1:-$POSTGRES_DB}" -Atc "$2"',
        "sh",
        database,
        sql,
        timeout=30,
    )


def snapshot(ns):
    """Return only opaque identity/schema digests; callers must keep receipts private."""
    postgres, _ = ns["container"]("postgres")
    result = {"schemas": {}}
    for name, database in DATABASES.items():
        value = _query(ns, postgres, database, SCHEMA_SQL)
        if re.fullmatch(r"[0-9a-f]{32}", value) is None:
            raise ns["Refusal"]("Database schema verification failed.")
        result["schemas"][name] = value
    revision = _query(ns, postgres, "", "SELECT version_num FROM alembic_version")
    if revision != "0007":
        raise ns["Refusal"]("Application database revision requires review.")
    result["app_revision"] = revision
    queries = {
        "paired_devices": (
            "auth",
            "SELECT md5(COALESCE(string_agg(jid::text, ',' ORDER BY jid), '')) "
            "FROM whatsmeow_device",
        ),
        "auth_version": (
            "auth",
            "SELECT md5(COALESCE(string_agg(row_to_json(t)::text, ',' ORDER BY "
            "row_to_json(t)::text), '')) FROM whatsmeow_version t",
        ),
        "instance_credentials": (
            "users",
            "SELECT md5(COALESCE(string_agg(id::text || ':' || COALESCE(token,'') "
            "|| ':' || COALESCE(jid,''), ',' ORDER BY id), '')) FROM instances",
        ),
    }
    for name, (database, sql) in queries.items():
        value = _query(ns, postgres, DATABASES[database], sql)
        if re.fullmatch(r"[0-9a-f]{32}", value) is None:
            raise ns["Refusal"]("Database identity verification failed.")
        result[name] = value
    return result


def backup(ns):
    """Dump three existing databases and verify restoration only in disposable clones."""
    directory = ns["ROOT"] / ".local/backups"
    if directory.is_symlink():
        raise ns["Refusal"]("Unsafe backup directory.")
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.stat().st_uid != os.getuid() or directory.stat().st_mode & 0o077:
        raise ns["Refusal"]("Backup directory must be private and owned.")
    destination = directory / ("evolution-" + uuid.uuid4().hex)
    destination.mkdir(mode=0o700)
    before = snapshot(ns)
    postgres, _ = ns["container"]("postgres")
    receipt = {"identity": before, "archives": {}}
    try:
        for name, database in DATABASES.items():
            archive = destination / (name + ".dump")
            fd = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as output:
                result = subprocess.run(
                    [
                        "docker",
                        "exec",
                        postgres,
                        "sh",
                        "-ec",
                        'exec pg_dump -U "$POSTGRES_USER" -d "${1:-$POSTGRES_DB}" --format=custom',
                        "sh",
                        database,
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.PIPE,
                    timeout=300,
                    check=False,
                )
                if result.returncode != 0:
                    raise ValueError
                output.flush()
                os.fsync(output.fileno())
            if archive.stat().st_size == 0:
                raise ValueError
            clone = "vasa_evo_verify_" + uuid.uuid4().hex
            created = False
            try:
                ns["run"](
                    "docker",
                    "exec",
                    postgres,
                    "sh",
                    "-ec",
                    'exec createdb -U "$POSTGRES_USER" -- "$1"',
                    "sh",
                    clone,
                )
                created = True
                for operation in ("list", "restore"):
                    command = (
                        "exec pg_restore --list"
                        if operation == "list"
                        else 'exec pg_restore -U "$POSTGRES_USER" --exit-on-error --no-owner '
                        '--no-privileges -d "$1"'
                    )
                    with archive.open("rb") as source:
                        result = subprocess.run(
                            ["docker", "exec", "-i", postgres, "sh", "-ec", command, "sh", clone],
                            stdin=source,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE,
                            timeout=300,
                            check=False,
                        )
                    if result.returncode != 0:
                        raise ValueError
                if _query(ns, postgres, clone, SCHEMA_SQL) != before["schemas"][name]:
                    raise ValueError
                if (
                    name == "app"
                    and _query(ns, postgres, clone, "SELECT version_num FROM alembic_version")
                    != "0007"
                ):
                    raise ValueError
            finally:
                if created:
                    ns["run"](
                        "docker",
                        "exec",
                        postgres,
                        "sh",
                        "-ec",
                        'exec dropdb -U "$POSTGRES_USER" -- "$1"',
                        "sh",
                        clone,
                    )
            with archive.open("rb") as source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
            receipt["archives"][name] = {
                "path": str(archive.relative_to(ns["ROOT"])),
                "sha256": digest,
                "bytes": archive.stat().st_size,
                "restore_verified": True,
            }
        if snapshot(ns) != before:
            raise ValueError
        record = destination / "receipt.json"
        fd = os.open(record, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            output.write(json.dumps(receipt, sort_keys=True) + "\n")
    except Exception:
        raise ns["Refusal"]("Evolution backup verification failed; raw output withheld.") from None
    print("EVOLUTION_BACKUP_RESTORE_OK", flush=True)
    return receipt
