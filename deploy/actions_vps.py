"""Actions-streamed staging controller; stdlib only, no credentials in output.

Uses the existing deploy/compose.yaml and .local/vps.env. Check mode has no
filesystem writes. Docker/Git output is captured, never dumped to Actions logs.
"""

import fcntl
import hashlib
import json
import os
import pwd
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path("/opt/vasa")
BRANCH = "build/vasa-foundation"
PROJECT = "vasa-vps"
SERVICES = ("vasa", "voice")
DEPENDENCIES = ("postgres", "redis", "evolution")
ENV_FILES = (
    ".local/vps.env",
    ".local/llm.env",
    ".local/smtp.env",
    ".local/vasa.env",
    ".env",
    "deploy/.env",
)
ORIGINS = {
    "https://github.com/ralphdeeney/VASA",
    "https://github.com/ralphdeeney/VASA.git",
    "git@github.com:ralphdeeney/VASA.git",
    "git@github-vasa:ralphdeeney/VASA.git",
    "ssh://git@github.com/ralphdeeney/VASA.git",
}
READY_MARKER = "Voice worker ready for registered instances; caller audio is not recorded."
BAD_LOG = re.compile(r"Traceback \(most recent call last\)|\b(?:ERROR|CRITICAL|FATAL)\b")
VOICE_STAGES = frozenset(
    {
        "settings",
        "speech_verify",
        "database",
        "redis",
        "evolution_client",
        "resolve_instances",
        "instance_status",
        "persisted_config",
        "knowledge_init",
        "tools_config",
        "llm_provider",
        "stt_init",
        "tts_init",
        "runtime_init",
        "ready",
        "supervision",
    }
)
VOICE_ERRORS = frozenset(
    {
        "invalid_configuration",
        "invalid_assets",
        "missing_assets",
        "dependency_unavailable",
        "initialization_failed",
        "operation_failed",
        "internal_error",
    }
)
ACTIVE_STAGE = "VASA_STAGE=preflight"


class Refusal(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise Refusal(message)


def stage(mode, name):
    global ACTIVE_STAGE
    require(mode in ("BOOTSTRAP", "DEPLOY"), "Invalid deployment stage mode.")
    require(
        name
        in (
            "preflight",
            "git_fetch",
            "rollback_image",
            "checkout",
            "target_build",
            "vasa_update",
            "voice_create",
            "health",
            "provider_smoke",
            "post_validation",
            "rollback",
            "rollback_health",
        ),
        "Invalid deployment stage identifier.",
    )
    ACTIVE_STAGE = mode + "_STAGE=" + name
    print(ACTIVE_STAGE, flush=True)


def capture(*args, timeout=60, input_text=None):
    """Never include command output/arguments in exceptions (may contain secrets)."""
    try:
        result = subprocess.run(
            args,
            **({"stdin": subprocess.DEVNULL} if input_text is None else {"input": input_text}),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Refusal(ACTIVE_STAGE + " failed or timed out; raw output withheld.") from exc
    return result


def run(*args, timeout=60, input_text=None):
    result = capture(*args, timeout=timeout, input_text=input_text)
    require(result.returncode == 0, ACTIVE_STAGE + " failed; raw output withheld.")
    return result.stdout.strip()


def git(*args):
    return run("git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", *args)


def compose(*args, timeout=180, image_override=None, capture_smoke=False, capture_validation=False):
    if capture_smoke:
        require(
            args == ("exec", "-T", "vasa", "python", "scripts/live_provider_smoke.py")
            and image_override is None,
            "Unchecked capture is restricted to provider smoke.",
        )
    if capture_validation:
        require(
            args == ("exec", "-T", "vasa", "python", "-m", "vasa.staging_validation")
            and image_override is None
            and not capture_smoke,
            "Unchecked capture is restricted to staging validation.",
        )
    extra = ()
    override = None
    if image_override is not None:
        require(args == ("build", "vasa"), "Image override is restricted to rollback builds.")
        require(
            re.fullmatch(r"vasa-app:(?:bootstrap-)?rollback-[0-9a-f]{40}", image_override)
            is not None,
            "Invalid rollback image tag.",
        )
        extra = ("-f", "-")
        # Only override the output image tag, never context, Dockerfile, build
        # arguments, secrets, or runtime environment. Nothing is written to disk.
        override = json.dumps({"services": {"vasa": {"image": image_override}}})
    execute = capture if capture_smoke or capture_validation else run
    return execute(
        "docker",
        "compose",
        "--project-name",
        PROJECT,
        "--env-file",
        ".local/vps.env",
        "-f",
        "deploy/compose.yaml",
        *extra,
        "--profile",
        "voice",
        *args,
        timeout=timeout,
        input_text=override,
    )


def acquire_rollback_image(running_image, previous, backup_tag):
    """Verify a rollback image before checkout or any app/container mutation."""
    require(
        re.fullmatch(r"[0-9a-f]{40}", previous) is not None
        and backup_tag
        in (
            "vasa-app:rollback-" + previous,
            "vasa-app:bootstrap-rollback-" + previous,
        ),
        "Invalid VASA rollback image target.",
    )
    require(git("rev-parse", "HEAD") == previous, "Previous source revision changed unexpectedly.")
    require(
        not git("status", "--porcelain", "--untracked-files=all"),
        "Rollback image acquisition requires a clean previous-source checkout.",
    )
    hashes = private_hashes()
    expected = None
    try:
        require(
            run("docker", "image", "inspect", "--format", "{{.Id}}", running_image)
            == running_image,
            "Running image is not locally inspectable.",
        )
        run("docker", "image", "tag", running_image, backup_tag)
        expected = running_image
    except Refusal:
        print(
            "Running image unavailable; building rollback from clean previous source.", flush=True
        )
        # Compose reads the existing build definition and dependency inputs. The
        # output goes straight to the rollback tag, leaving vasa-app:pinned alone.
        compose("build", "vasa", timeout=900, image_override=backup_tag)
    rollback_image = run("docker", "image", "inspect", "--format", "{{.Id}}", backup_tag)
    require(
        bool(rollback_image) and (expected is None or rollback_image == expected),
        "Rollback image verification failed.",
    )
    require(
        git("rev-parse", "HEAD") == previous
        and not git("status", "--porcelain", "--untracked-files=all"),
        "Previous-source checkout changed during rollback image acquisition.",
    )
    require(
        private_hashes() == hashes, "Private environment changed during rollback image acquisition."
    )
    return rollback_image


def rootless():
    uid = os.getuid()
    require(uid != 0, "Root is forbidden.")
    endpoint = os.environ.get("DOCKER_HOST")
    if not endpoint:
        endpoint = run("docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}")
    # Prefer the user's explicitly selected existing socket. Only fall back to
    # this user's runtime socket when the default rootful socket was selected.
    if endpoint == "unix:///var/run/docker.sock":
        runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{uid}"))
        require(
            runtime.is_dir() and runtime.stat().st_uid == uid,
            "No owned rootless runtime directory.",
        )
        endpoint = "unix://" + str(runtime / "docker.sock")
        os.environ.pop("DOCKER_CONTEXT", None)
        os.environ["DOCKER_HOST"] = endpoint
    require(endpoint.startswith("unix:///"), "An owned local Unix Docker socket is required.")
    socket = Path(endpoint.removeprefix("unix://"))
    require(socket.is_socket() and socket.stat().st_uid == uid, "Rootless socket is unavailable.")
    options = json.loads(run("docker", "info", "--format", "{{json .SecurityOptions}}"))
    require("name=rootless" in options, "Selected Docker daemon is not rootless.")
    run("docker", "compose", "version")


def preflight():
    require(pwd.getpwuid(os.getuid()).pw_name == "vasa-builder", "Unexpected remote user.")
    require(
        ROOT.is_dir() and ROOT.resolve() == ROOT and ROOT.stat().st_uid == os.getuid(),
        "Project directory is missing, redirected, or not owned by vasa-builder.",
    )
    os.chdir(ROOT)
    os.environ["GIT_OPTIONAL_LOCKS"] = "0"
    os.environ["GIT_TERMINAL_PROMPT"] = "0"
    require(git("rev-parse", "--show-toplevel") == str(ROOT), "Unexpected Git working tree.")
    require(git("remote", "get-url", "origin") in ORIGINS, "Unexpected repository identity.")
    branch = git("branch", "--show-current")
    sha = git("rev-parse", "HEAD")
    require(re.fullmatch(r"[0-9a-f]{40}", sha) is not None, "Invalid current commit.")
    rootless()
    print(
        "Remote user: vasa-builder; owned project/repository: verified; branch: "
        + (branch if re.fullmatch(r"[\w/.-]+", branch) else "(detached)")
        + "; commit: "
        + sha,
        flush=True,
    )
    print("Rootless Docker info, Compose, and owned Unix socket: OK", flush=True)
    return branch, sha


def investigate():
    """Read-only recovery evidence. Arbitrary output is never forwarded."""
    print("VASA_INVESTIGATION_BEGIN", flush=True)
    known = set(git("ls-tree", "-r", "--name-only", "HEAD").splitlines())
    status_result = capture(
        "git",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    )
    require(status_result.returncode == 0, "Cannot inspect working tree status.")
    entries = status_result.stdout.split("\0")
    changes = []
    for entry in entries:
        if len(entry) < 4:
            continue
        status, name = entry[:2], entry[3:]
        public = name in known and not (
            name.startswith(".local/") or name in ENV_FILES or name.endswith((".pem", ".key"))
        )
        record = {"status": status if re.fullmatch(r"[ MADRCU?!]{2}", status) else "??"}
        if public:
            record["path"] = name
            path = ROOT / name
            if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(ROOT):
                record["working_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            # Inspect the actual diff, but report only structural metadata.
            diff = git("diff", "--no-ext-diff", "--no-textconv", "HEAD", "--", name)
            record["added_lines"] = sum(
                s.startswith("+") and not s.startswith("+++") for s in diff.splitlines()
            )
            record["removed_lines"] = sum(
                s.startswith("-") and not s.startswith("---") for s in diff.splitlines()
            )
            history = git("log", "-3", "--format=%H", "--", name).splitlines()
            record["history"] = [sha for sha in history if re.fullmatch(r"[0-9a-f]{40}", sha)]
            if name == "deploy/compose.yaml":
                record["added_public_origin_setting"] = any(
                    s.startswith("+") and "VASA_PUBLIC_ORIGIN:" in s for s in diff.splitlines()
                )
                record["added_smtp_bindings"] = any(
                    s.startswith("+") and "VASA_SMTP_" in s for s in diff.splitlines()
                )
        else:
            if (
                re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_./-]{0,159}", name)
                and not re.search(
                    r"(?:secret|credential|token|password|\.env|\.key|\.pem)", name, re.I
                )
                and not re.search(r"[0-9a-fA-F]{16,}|[A-Za-z0-9_-]{40,}", name)
                and ".." not in Path(name).parts
            ):
                record["path"] = name
            record["path_sha256"] = hashlib.sha256(name.encode()).hexdigest()
            record["classification"] = "private_or_untracked_preserved"
        changes.append(record)
    print("VPS_WORKTREE=" + json.dumps(changes, sort_keys=True), flush=True)
    print("VPS_WORKTREE_PRESERVED=yes", flush=True)
    print(
        "VPS_WORKTREES=" + str(git("worktree", "list", "--porcelain").count("worktree ")),
        flush=True,
    )
    print(
        "VPS_RELEASE_BASE_AVAILABLE=" + ("yes" if (ROOT / ".local").is_dir() else "no"), flush=True
    )
    print(
        "VPS_DISK_AVAILABLE_MIB="
        + str(os.statvfs(ROOT).f_bavail * os.statvfs(ROOT).f_frsize // 1048576),
        flush=True,
    )
    names = (
        "VASA_SMTP_HOST",
        "VASA_SMTP_PORT",
        "VASA_SMTP_USERNAME",
        "VASA_SMTP_PASSWORD",
        "VASA_SMTP_SENDER",
        "VASA_SMTP_STARTTLS",
        "VASA_SMTP_DELIVERY_VERIFIED",
        "VASA_CONTACT_RECIPIENT",
        "VASA_PUBLIC_ORIGIN",
        "VASA_SAAS_ENABLED",
        "SMTP_HOST",
        "SMTP_USER",
        "SMTP_PASSWORD",
        "SMTP_FROM",
    )
    for filename in ENV_FILES:
        path = ROOT / filename
        present = []
        if path.is_file() and not path.is_symlink() and path.stat().st_size <= 1048576:
            for line in path.read_text().splitlines():
                key, sep, value = line.strip().removeprefix("export ").partition("=")
                if sep and key.strip() in names and value.strip().strip("\"'"):
                    present.append(key.strip())
        print(
            "VPS_CONFIG_BINDINGS="
            + json.dumps({"source": filename, "present": sorted(set(present))}),
            flush=True,
        )
    backups = ROOT / ".local" / "backups"
    count = len(list(backups.iterdir())) if backups.is_dir() and not backups.is_symlink() else 0
    print("VPS_BACKUP_FILE_COUNT=" + str(count), flush=True)
    print("VPS_BACKUP_RESTORE_VERIFIED=no", flush=True)
    try:
        data = config()
        ports = []
        for item in data["services"]["vasa"].get("ports", []):
            host = item.get("host_ip", "")
            ports.append(
                {
                    "host_ip": host
                    if host in {"127.0.0.1", "172.16.2.1", "0.0.0.0", "::"}
                    else "other",
                    "published": str(item.get("published"))
                    if str(item.get("published")).isdigit()
                    else "other",
                    "target": item.get("target") if isinstance(item.get("target"), int) else 0,
                }
            )
        print("VPS_VASA_PORTS=" + json.dumps(ports), flush=True)
        for service in DEPENDENCIES + SERVICES:
            _, value = container(service)
            print(
                "VPS_SERVICE="
                + json.dumps(
                    {"service": service, "healthy": state_ok(value), "restarts": value["restarts"]}
                ),
                flush=True,
            )
    except Refusal:
        print("VPS_TOPOLOGY=inspection_failed", flush=True)
    probe = r"""
import asyncio,json,os,uuid
from sqlalchemy import text
from vasa.config import Settings
from vasa.storage.database import Database
import httpx
async def main():
 d=Database(Settings().database_url.get_secret_value(),timeout_seconds=3)
 try:
  async with d.session() as s:
   revision=await s.scalar(text("SELECT version_num FROM alembic_version"))
   valid=revision in {"0001","0002","0003","0004","0005","0006","0007"}
   print("VPS_DB_REVISION="+(revision if valid else "other"))
   for table in ("users","tenants","agents","whatsapp_instances"):
    n=await s.scalar(text("SELECT count(*) FROM "+table))
    print("VPS_DB_COUNT_"+table.upper()+"="+str(n))
 except Exception: print("VPS_DB=unavailable")
 finally: await d.aclose()
 names=("VASA_SMTP_HOST","VASA_SMTP_USERNAME","VASA_SMTP_PASSWORD","VASA_SMTP_SENDER","VASA_PUBLIC_ORIGIN","VASA_SAAS_ENABLED")
 for name in names:
  present="present" if os.getenv(name) else "absent"
  print("VPS_RUNTIME_BINDING_"+name+"="+present)
 try:
  async with httpx.AsyncClient(base_url="http://127.0.0.1:8080",trust_env=False,timeout=5) as c:
   h={"Host":"vasa.litatech.xyz","Origin":"https://vasa.litatech.xyz"}
   r=await c.get("/login",headers=h); print("VPS_LOGIN_PAGE_STATUS="+str(r.status_code))
   payload={"email":"diagnostic-"+uuid.uuid4().hex+"@example.invalid",
            "password":"synthetic-non-account-password"}
   r=await c.post("/api/auth/login",headers=h,json=payload)
   print("VPS_LOGIN_PROBE_STATUS="+str(r.status_code))
   try: reason=r.json().get("detail")
   except Exception: reason=None
   approved={"invalid_origin","invalid_credentials","unavailable","too_many_attempts","account_inactive","email_verification_required"}
   safe=reason if isinstance(reason,str) and reason in approved else "unclassified"
   print("VPS_LOGIN_PROBE_REASON="+safe)
 except Exception: print("VPS_HTTP=unavailable")
asyncio.run(main())
"""
    # The synthetic login is an explicit bounded auth probe; it creates no account/session.
    try:
        output = compose("exec", "-T", "vasa", "python", "-c", probe, timeout=45)
        pattern = (
            r"VPS_(?:DB_REVISION=000[1-7]|DB_COUNT_(?:USERS|TENANTS|AGENTS|WHATSAPP_INSTANCES)=\d+"
            r"|DB=unavailable|RUNTIME_BINDING_VASA_(?:SMTP_HOST|SMTP_USERNAME|SMTP_PASSWORD"
            r"|SMTP_SENDER|PUBLIC_ORIGIN|SAAS_ENABLED)=(?:present|absent)"
            r"|LOGIN_PAGE_STATUS=\d{3}|LOGIN_PROBE_STATUS=\d{3}|LOGIN_PROBE_REASON="
            r"(?:invalid_origin|invalid_credentials|unavailable|too_many_attempts|account_inactive"
            r"|email_verification_required|unclassified)|HTTP=unavailable)"
        )
        for line in output.splitlines():
            if re.fullmatch(pattern, line, flags=re.ASCII):
                print(line, flush=True)
    except Refusal:
        print("VPS_RUNTIME_PROBE=unavailable", flush=True)
    print("VASA_INVESTIGATION_OK", flush=True)


def prepare_recovery(target, *, exact_tip=True):
    """Prepare isolated source/images and a restore-tested backup; never activate."""
    import shutil
    import uuid

    require(re.fullmatch(r"[0-9a-f]{40}", target) is not None, "Invalid preparation target.")
    preflight()
    local = ROOT / ".local"
    require(local.is_dir() and not local.is_symlink(), "Private directory unavailable.")
    lock_path = local / "actions-deploy.lock"
    require(not lock_path.is_symlink(), "Unsafe deployment lock.")
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        baseline = git("status", "--porcelain=v1", "--untracked-files=all")

        def dirty_file_hashes():
            names = set(git("diff", "--name-only", "-z", "HEAD").split("\0"))
            names.update(git("ls-files", "--others", "--exclude-standard", "-z").split("\0"))
            result = {}
            for name in names - {""}:
                require(
                    not Path(name).is_absolute() and ".." not in Path(name).parts,
                    "Unsafe dirty path.",
                )
                path = ROOT / name
                if path.is_symlink():
                    result[name] = (
                        "symlink",
                        hashlib.sha256(os.readlink(path).encode()).hexdigest(),
                    )
                elif path.is_file() and path.resolve().is_relative_to(ROOT):
                    with path.open("rb") as source:
                        result[name] = ("file", hashlib.file_digest(source, "sha256").hexdigest())
                else:
                    result[name] = ("missing_or_external", None)
            return result

        dirty_hashes = dirty_file_hashes()
        hashes = private_hashes()
        topology = snapshot_services(DEPENDENCIES + SERVICES)
        require(
            len({topology[name]["image"] for name in SERVICES}) == 1, "App rollback images differ."
        )
        canonical = git("rev-parse", "HEAD")
        previous = canonical
        release_journal = local / "actions-release.json"
        if release_journal.exists():
            require(not release_journal.is_symlink(), "Unsafe release journal.")
            prior = json.loads(release_journal.read_text())
            require(
                re.fullmatch(r"[0-9a-f]{40}", prior.get("active_sha", "")) is not None
                and prior.get("active_image") == topology["vasa"]["image"],
                "Active release journal differs from running applications.",
            )
            previous = prior["active_sha"]
        require(re.fullmatch(r"[0-9a-f]{40}", previous) is not None, "Invalid previous revision.")
        require(
            shutil.disk_usage(ROOT).free >= 2 * 1024**3, "Preparation requires 2 GiB free disk."
        )

        def unchanged():
            require(git("rev-parse", "HEAD") == canonical, "Live checkout changed.")
            require(
                git("status", "--porcelain=v1", "--untracked-files=all") == baseline,
                "Live working tree changed.",
            )
            require(private_hashes() == hashes, "Private environment changed.")
            require(dirty_file_hashes() == dirty_hashes, "Preserved local file contents changed.")
            assert_unchanged(topology)

        def owned_directory(path):
            require(not path.is_symlink(), "Unsafe preparation directory.")
            path.mkdir(mode=0o700, exist_ok=True)
            require(path.is_dir() and path.stat().st_uid == os.getuid(), "Unowned directory.")
            require(path.stat().st_mode & 0o077 == 0, "Preparation directory must be private.")

        def source_tree(sha):
            releases = local / "releases"
            owned_directory(releases)
            path = releases / sha
            require(not path.is_symlink(), "Unsafe release path.")
            if path.exists():
                require(path.is_dir() and path.stat().st_uid == os.getuid(), "Unowned release.")
                require(
                    git("-C", str(path), "rev-parse", "HEAD") == sha, "Release revision differs."
                )
                require(
                    git("-C", str(path), "rev-parse", "--git-common-dir") == str(ROOT / ".git"),
                    "Release repository differs.",
                )
                require(not git("-C", str(path), "status", "--porcelain"), "Release is dirty.")
            else:
                git("worktree", "add", "--detach", str(path), sha)
            ca = ROOT / ".local/evolution-source/vasa-host-trust.pem"
            require(ca.is_file() and not ca.is_symlink(), "Public build trust file unavailable.")
            require(ca.stat().st_size <= 2 * 1024**2, "Invalid public trust file.")
            payload = ca.read_bytes()
            require(
                b"-----BEGIN CERTIFICATE-----" in payload and b"PRIVATE KEY" not in payload,
                "Invalid public trust file.",
            )
            run("openssl", "x509", "-in", str(ca), "-noout", timeout=15)
            destination = path / ".local/evolution-source"
            require(not (path / ".local").is_symlink(), "Unsafe release trust directory.")
            require(not destination.is_symlink(), "Unsafe release trust directory.")
            destination.mkdir(parents=True, exist_ok=True, mode=0o700)
            trust = destination / "vasa-host-trust.pem"
            require(not trust.is_symlink(), "Unsafe release trust file.")
            trust.write_bytes(payload)
            trust.chmod(0o644)
            return path

        def build(sha, tag):
            path = source_tree(sha)
            unchanged()
            run(
                "docker",
                "build",
                "--tag",
                tag,
                "--file",
                str(path / "docker/vasa.Dockerfile"),
                str(path),
                timeout=1200,
            )
            require(
                re.fullmatch(
                    r"sha256:[0-9a-f]{64}",
                    run("docker", "image", "inspect", "--format", "{{.Id}}", tag),
                )
                is not None,
                "Prepared image verification failed.",
            )

        def recovery_stage(name):
            global ACTIVE_STAGE
            ACTIVE_STAGE = "RECOVERY_PREPARE_STAGE=" + name
            print("RECOVERY_PREPARE_STAGE=" + name, flush=True)

        try:
            recovery_stage("git_fetch")
            git("fetch", "origin", BRANCH)
            if exact_tip:
                require(
                    git("rev-parse", "origin/" + BRANCH) == target,
                    "Target is not remote branch tip.",
                )
            else:
                git("merge-base", "--is-ancestor", target, "origin/" + BRANCH)
            git("merge-base", "--is-ancestor", previous, target)
            target_source = source_tree(target)
            recovery_stage("backup")
            backups = local / "backups"
            owned_directory(backups)
            token = uuid.uuid4().hex
            archive = backups / ("vasa-" + token + ".dump")
            postgres, _ = container("postgres")
            descriptor = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                try:
                    dumped = subprocess.run(
                        [
                            "docker",
                            "exec",
                            postgres,
                            "sh",
                            "-ec",
                            'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom',
                        ],
                        stdin=subprocess.DEVNULL,
                        stdout=output,
                        stderr=subprocess.PIPE,
                        timeout=300,
                        check=False,
                    )
                except (OSError, subprocess.TimeoutExpired) as exc:
                    raise Refusal("Backup creation failed; raw output withheld.") from exc
                require(dumped.returncode == 0, "Backup creation failed; raw output withheld.")
                output.flush()
                os.fsync(output.fileno())
            require(archive.stat().st_size > 0, "Empty database backup.")
            temporary = "vasa_verify_" + token
            created = False
            try:
                run(
                    "docker",
                    "exec",
                    postgres,
                    "sh",
                    "-ec",
                    'exec createdb -U "$POSTGRES_USER" -- "$1"',
                    "sh",
                    temporary,
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
                        try:
                            result = subprocess.run(
                                [
                                    "docker",
                                    "exec",
                                    "-i",
                                    postgres,
                                    "sh",
                                    "-ec",
                                    command,
                                    "sh",
                                    temporary,
                                ],
                                stdin=source,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE,
                                timeout=300,
                                check=False,
                            )
                        except (OSError, subprocess.TimeoutExpired) as exc:
                            raise Refusal(
                                "Backup verification failed; raw output withheld."
                            ) from exc
                    require(
                        result.returncode == 0, "Backup verification failed; raw output withheld."
                    )

                def clone_query(sql):
                    return run(
                        "docker",
                        "exec",
                        postgres,
                        "sh",
                        "-ec",
                        'exec psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -Atc "$2"',
                        "sh",
                        temporary,
                        sql,
                    )

                revision = clone_query("SELECT version_num FROM alembic_version")
                require(revision in ("0006", "0007"), "Unsupported clone migration revision.")
                if revision == "0006":
                    sql_path = target_source / "docs/migrations/0007_saas_identity.sql"
                    require(
                        sql_path.is_file()
                        and not sql_path.is_symlink()
                        and sql_path.stat().st_uid == os.getuid()
                        and sql_path.stat().st_size <= 1048576,
                        "Reviewed migration artifact unavailable.",
                    )
                    reviewed_sql = sql_path.read_text()
                    # Compare only digests inside the isolated clone; no user rows escape.
                    invariant_sql = (
                        "SELECT md5(COALESCE(string_agg(id::text || ':' || tenant_id::text "
                        "|| ':' || password_hash, ',' ORDER BY id), '')) FROM users"
                    )
                    before = clone_query(invariant_sql)
                    run(
                        "docker",
                        "exec",
                        "-i",
                        postgres,
                        "sh",
                        "-ec",
                        'exec psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1"',
                        "sh",
                        temporary,
                        input_text=reviewed_sql,
                        timeout=120,
                    )
                    require(
                        clone_query("SELECT version_num FROM alembic_version") == "0007"
                        and clone_query(invariant_sql) == before,
                        "Disposable migration compatibility failed.",
                    )
                    print(
                        "RECOVERY_MIGRATION_SQL_SHA256="
                        + hashlib.sha256(reviewed_sql.encode()).hexdigest(),
                        flush=True,
                    )
                    print("RECOVERY_MIGRATION_CLONE_OK", flush=True)
                else:
                    print("RECOVERY_MIGRATION_CLONE_ALREADY_CURRENT", flush=True)
            finally:
                if created:
                    run(
                        "docker",
                        "exec",
                        postgres,
                        "sh",
                        "-ec",
                        'exec dropdb -U "$POSTGRES_USER" -- "$1"',
                        "sh",
                        temporary,
                    )
            print("RECOVERY_BACKUP_RESTORE_OK", flush=True)
            print("RECOVERY_BACKUP_BYTES=" + str(archive.stat().st_size), flush=True)
            with archive.open("rb") as backup_input:
                digest = hashlib.file_digest(backup_input, "sha256").hexdigest()
            print("RECOVERY_BACKUP_SHA256=" + digest, flush=True)
            recovery_stage("rollback_image")
            rollback = "vasa-app:rollback-" + previous
            image = topology["vasa"]["image"]
            available = capture("docker", "image", "inspect", "--format", "{{.Id}}", image)
            if available.returncode == 0 and available.stdout.strip() == image:
                run("docker", "image", "tag", image, rollback)
            else:
                build(previous, rollback)
            require(
                re.fullmatch(
                    r"sha256:[0-9a-f]{64}",
                    run("docker", "image", "inspect", "--format", "{{.Id}}", rollback),
                )
                is not None,
                "Rollback image unavailable.",
            )
            recovery_stage("candidate_build")
            build(target, "vasa-app:release-" + target)
            print("RECOVERY_PREVIOUS_SHA=" + previous, flush=True)
            print("RECOVERY_TARGET_SHA=" + target, flush=True)

        finally:
            unchanged()
        receipt_directory = local / "recovery-preparations"
        owned_directory(receipt_directory)
        receipt = receipt_directory / (target + "-" + token + ".json")
        receipt_data = {
            "target_sha": target,
            "previous_sha": previous,
            "canonical_sha": canonical,
            "backup": str(archive.relative_to(ROOT)),
            "backup_sha256": digest,
            "restore_verified": True,
            "migration_clone_verified": True,
            "candidate_image": "vasa-app:release-" + target,
            "rollback_image": rollback,
            "live_checkout_unchanged": True,
            "live_migration_applied": False,
        }
        with os.fdopen(
            os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
        ) as record:
            record.write(json.dumps(receipt_data, sort_keys=True) + "\n")
        print("RECOVERY_RECEIPT=prepared", flush=True)
        print("VASA_RECOVERY_PREPARE_OK", flush=True)


def release_compose(source, image, saas, *args, unchecked=False):
    """Use canonical project paths with verified immutable release configuration."""
    require(
        re.fullmatch(r"vasa-app:(?:release|rollback)-[0-9a-f]{40}", image) is not None,
        "Invalid release image reference.",
    )
    require(source == ROOT or source.parent == ROOT / ".local/releases", "Unsafe release source.")
    require(not source.is_symlink() and source.is_dir(), "Release source unavailable.")
    patch = {"services": {name: {"image": image} for name in SERVICES}}
    if saas is not None:
        for name in SERVICES:
            patch["services"][name]["environment"] = {
                "VASA_SAAS_ENABLED": "true" if saas else "false"
            }
    command = (
        "docker",
        "compose",
        "--project-name",
        PROJECT,
        "--project-directory",
        str(ROOT / "deploy"),
        "--env-file",
        str(ROOT / ".local/vps.env"),
        "-f",
        str(source / "deploy/compose.yaml"),
        "-f",
        "-",
        "--profile",
        "voice",
        *args,
    )
    result = capture(*command, input_text=json.dumps(patch), timeout=240)
    if unchecked:
        return result
    require(result.returncode == 0, ACTIVE_STAGE + " failed; raw output withheld.")
    return result.stdout.strip()


def smtp_acceptance(target, recipient):
    """One explicit email from a prepared web image; never replace a running service."""
    require(re.fullmatch(r"[0-9a-f]{40}", target) is not None, "Invalid SMTP release SHA.")
    require(
        len(recipient) <= 254
        and re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._%+-]{0,63}@[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,63}",
            recipient,
        )
        is not None,
        "Invalid SMTP test mailbox.",
    )
    source = ROOT / ".local/releases" / target
    require(source.is_dir() and not source.is_symlink(), "Prepared SMTP release required.")
    require(
        git("-C", str(source), "rev-parse", "HEAD") == target
        and not git("-C", str(source), "status", "--porcelain")
        and git("-C", str(source), "remote", "get-url", "origin") in ORIGINS,
        "Prepared SMTP source differs.",
    )
    private = ROOT / ".local/smtp.env"
    require(
        private.is_file()
        and not private.is_symlink()
        and private.stat().st_uid == os.getuid()
        and private.stat().st_mode & 0o777 == 0o600,
        "SMTP_PRIVATE_CONFIGURATION_REQUIRED",
    )
    lock_path = ROOT / ".local/actions-deploy.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = snapshot_services(DEPENDENCIES + SERVICES)
        hashes = private_hashes()
        baseline = git("status", "--porcelain=v1", "--untracked-files=all")
        image = "vasa-app:release-" + target
        run("docker", "image", "inspect", "--format", "{{.Id}}", image)
        try:
            result = release_compose(
                source,
                image,
                None,
                "run",
                "--rm",
                "--no-deps",
                "-T",
                "--entrypoint",
                "python",
                "vasa",
                "scripts/check_smtp.py",
                "--recipient",
                recipient,
                unchecked=True,
            )
        finally:
            assert_unchanged(before)
            require(private_hashes() == hashes, "Private SMTP configuration changed during test.")
            require(
                git("status", "--porcelain=v1", "--untracked-files=all") == baseline,
                "Canonical operator files changed during SMTP test.",
            )
        # Discard arbitrary output, provider replies, stderr and exception text.
        reports = []
        failures = {
            "missing_configuration",
            "delivery_unverified",
            "authentication_failed",
            "tls_failed",
            "connection_failed",
            "timeout",
            "recipient_refused",
            "delivery_failed",
            "busy",
            "invalid_recipient",
            "configuration_invalid",
        }
        for line in result.stdout.splitlines():
            try:
                value = json.loads(line)
            except (ValueError, TypeError):
                continue
            if value == {"status": "smtp_accepted", "mailbox_delivery_verified": False}:
                reports.append("accepted")
            elif (
                isinstance(value, dict)
                and set(value) == {"status", "code"}
                and value.get("status") == "failed"
                and isinstance(value.get("code"), str)
                and value["code"] in failures
            ):
                reports.append(value["code"])
        if len(reports) != 1:
            print("SMTP_ACCEPTANCE_FAILED=invalid_response", flush=True)
            raise Refusal("SMTP acceptance response unavailable; raw output withheld.")
        if reports[0] != "accepted" or result.returncode != 0:
            code = reports[0] if reports[0] != "accepted" else "delivery_failed"
            print("SMTP_ACCEPTANCE_FAILED=" + code, flush=True)
            raise Refusal("SMTP acceptance failed; raw output withheld.")
        print("VASA_SMTP_ACCEPTANCE_OK", flush=True)
        print("SMTP_MAILBOX_VERIFIED=false", flush=True)


def activate_recovery(target, sql_hash):
    """Explicitly approved additive migration and targeted immutable-image rollout."""
    require(re.fullmatch(r"[0-9a-f]{40}", target) is not None, "Invalid activation target.")
    require(re.fullmatch(r"[0-9a-f]{64}", sql_hash) is not None, "Invalid approved SQL hash.")
    source = ROOT / ".local/releases" / target
    require(source.is_dir() and not source.is_symlink(), "Prepared release is unavailable.")
    require(git("-C", str(source), "rev-parse", "HEAD") == target, "Prepared source differs.")
    require(not git("-C", str(source), "status", "--porcelain"), "Prepared release is dirty.")
    sql_path = source / "docs/migrations/0007_saas_identity.sql"
    require(sql_path.is_file() and not sql_path.is_symlink(), "Approved SQL artifact missing.")
    sql = sql_path.read_text()
    require(
        hashlib.sha256(sql.encode()).hexdigest() == sql_hash, "Approved migration hash differs."
    )
    local = ROOT / ".local"
    lock_fd = os.open(local / "actions-deploy.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        canonical = git("rev-parse", "HEAD")
        require(not git("diff", "--name-only", "HEAD"), "Tracked canonical changes require review.")
        baseline = git("status", "--porcelain=v1", "--untracked-files=all")
        # Preserve operator infrastructure files, including their exact contents.
        names = git("ls-files", "--others", "--exclude-standard", "-z").split("\0")

        def local_fingerprints():
            output = {}
            for name in set(names) - {""}:
                require(
                    not Path(name).is_absolute() and ".." not in Path(name).parts,
                    "Unsafe local path.",
                )
                path = ROOT / name
                if path.is_symlink():
                    output[name] = ("link", os.readlink(path))
                elif path.is_file() and path.resolve().is_relative_to(ROOT):
                    with path.open("rb") as stream:
                        output[name] = ("file", hashlib.file_digest(stream, "sha256").hexdigest())
                else:
                    output[name] = ("missing", None)
            return output

        fingerprints = local_fingerprints()
        hashes = private_hashes()
        before = snapshot_services(DEPENDENCIES + SERVICES)
        require(len({before[s]["image"] for s in SERVICES}) == 1, "Running app images differ.")
        receipts = local / "recovery-preparations"
        require(
            receipts.is_dir() and not receipts.is_symlink(), "Preparation receipts unavailable."
        )
        candidates = [p for p in receipts.glob(target + "-*.json") if not p.is_symlink()]
        require(bool(candidates), "Verified preparation receipt required.")
        record_path = max(candidates, key=lambda p: p.stat().st_mtime_ns)
        require(
            record_path.stat().st_uid == os.getuid() and record_path.stat().st_mode & 0o077 == 0,
            "Preparation receipt is not private and owned.",
        )
        prepared = json.loads(record_path.read_text())
        previous = prepared.get("previous_sha", "")
        require(
            re.fullmatch(r"[0-9a-f]{40}", previous) is not None
            and prepared.get("target_sha") == target
            and prepared.get("restore_verified") is True
            and prepared.get("migration_clone_verified") is True,
            "Verified preparation does not match activation.",
        )
        backup = ROOT / prepared.get("backup", "")
        require(
            backup.parent == local / "backups" and backup.is_file() and not backup.is_symlink(),
            "Verified backup is unavailable.",
        )
        with backup.open("rb") as stream:
            require(
                hashlib.file_digest(stream, "sha256").hexdigest() == prepared.get("backup_sha256"),
                "Verified backup changed.",
            )
        candidate = "vasa-app:release-" + target
        rollback = "vasa-app:rollback-" + previous
        previous_source = ROOT if previous == canonical else ROOT / ".local/releases" / previous
        require(
            git("-C", str(previous_source), "rev-parse", "HEAD") == previous,
            "Previous release source is unavailable.",
        )
        candidate_id = run("docker", "image", "inspect", "--format", "{{.Id}}", candidate)
        require(
            re.fullmatch(r"sha256:[0-9a-f]{64}", candidate_id) is not None,
            "Candidate image unavailable.",
        )
        require(
            run("docker", "image", "inspect", "--format", "{{.Id}}", rollback)
            == before["vasa"]["image"],
            "Verified rollback differs from running application.",
        )
        prior_saas = True if previous != canonical else None
        old_config = json.loads(
            release_compose(previous_source, rollback, prior_saas, "config", "--format", "json")
        )
        new_config = json.loads(
            release_compose(source, candidate, True, "config", "--format", "json")
        )
        validate_web_bind(new_config)
        require(
            {k: v for k, v in old_config.items() if k != "services"}
            == {k: v for k, v in new_config.items() if k != "services"},
            "Release project topology differs.",
        )
        require(
            set(new_config["services"]) == set(DEPENDENCIES + SERVICES), "Release services differ."
        )
        for service in DEPENDENCIES:
            require(
                old_config["services"][service] == new_config["services"][service],
                "Dependency configuration differs.",
            )
        for service in SERVICES:
            old, new = old_config["services"][service], new_config["services"][service]
            require(
                {k: v for k, v in old.items() if k not in {"image", "environment"}}
                == {k: v for k, v in new.items() if k not in {"image", "environment"}},
                "App topology or command differs.",
            )
            excluded = {"VASA_PUBLIC_ORIGIN", "VASA_SAAS_ENABLED"}
            require(
                {k: v for k, v in old.get("environment", {}).items() if k not in excluded}
                == {k: v for k, v in new.get("environment", {}).items() if k not in excluded},
                "Provider or private configuration differs.",
            )
            require(
                new["environment"].get("VASA_PUBLIC_ORIGIN") == "https://vasa.litatech.xyz"
                and new["environment"].get("VASA_SAAS_ENABLED") == "true",
                "Trusted public origin or SaaS setting differs.",
            )

        def preserved():
            require(
                git("rev-parse", "HEAD") == canonical
                and git("status", "--porcelain=v1", "--untracked-files=all") == baseline
                and local_fingerprints() == fingerprints,
                "Canonical operator work changed.",
            )
            require(private_hashes() == hashes, "Private runtime configuration changed.")
            assert_unchanged({name: before[name] for name in DEPENDENCIES})

        def release_stage(name):
            global ACTIVE_STAGE
            ACTIVE_STAGE = "RELEASE_STAGE=" + name
            print("RELEASE_STAGE=" + name, flush=True)

        postgres, _ = container("postgres")

        def live_query(query):
            return run(
                "docker",
                "exec",
                postgres,
                "sh",
                "-ec",
                'exec psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$1"',
                "sh",
                query,
            )

        journal = local / "actions-release.json"
        require(not journal.is_symlink(), "Unsafe release journal.")

        def receipt(status, active_sha, active_image):
            value = {
                "status": status,
                "target_sha": target,
                "previous_sha": previous,
                "canonical_sha": canonical,
                "active_sha": active_sha,
                "active_image": active_image,
                "migration_sql_sha256": sql_hash,
                "backup_receipt": str(record_path.relative_to(ROOT)),
                "database_revision": live_query("SELECT version_num FROM alembic_version"),
            }
            fd = os.open(journal, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "w") as output:
                output.write(json.dumps(value, sort_keys=True) + "\n")

        attempted = False
        for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, signal_failure)
        try:
            release_stage("migration")
            revision = live_query("SELECT version_num FROM alembic_version")
            require(revision in {"0006", "0007"}, "Live schema revision requires separate review.")
            invariant = (
                "SELECT md5(COALESCE(string_agg(id::text || ':' || tenant_id::text "
                "|| ':' || password_hash, ',' ORDER BY id), '')) FROM users"
            )
            old_identity = live_query(invariant)
            if revision == "0006":
                run(
                    "docker",
                    "exec",
                    "-i",
                    postgres,
                    "sh",
                    "-ec",
                    'exec psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"',
                    input_text=sql,
                    timeout=120,
                )
            require(
                live_query("SELECT version_num FROM alembic_version") == "0007"
                and live_query(invariant) == old_identity,
                "Migration identity/schema invariant failed.",
            )
            print("VASA_MIGRATION_0007_OK", flush=True)
            preserved()
            release_stage("app_update")
            attempted = True
            release_compose(
                source,
                candidate,
                True,
                "up",
                "-d",
                "--no-deps",
                "--no-build",
                "--wait",
                "--wait-timeout",
                "150",
                *SERVICES,
            )
            release_stage("health")
            health()
            require(
                all(container(s)[1]["image"] == candidate_id for s in SERVICES),
                "Running release image differs.",
            )
            post_validation(target, source=source)
            preserved()
            receipt("active", target, candidate_id)
        except BaseException:
            for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
                signal.signal(sig, signal.SIG_IGN)
            diagnostics()
            release_stage("rollback")
            try:
                if attempted:
                    release_compose(
                        previous_source,
                        rollback,
                        prior_saas,
                        "up",
                        "-d",
                        "--no-deps",
                        "--no-build",
                        "--wait",
                        "--wait-timeout",
                        "150",
                        *SERVICES,
                    )
                health()
                preserved()
                require(
                    all(container(s)[1]["image"] == before[s]["image"] for s in SERVICES),
                    "Rollback image restoration failed.",
                )
                receipt("rolled_back", previous, before["vasa"]["image"])
                print("VASA_RELEASE_ROLLBACK_OK", flush=True)
            except BaseException:
                print("VASA_RELEASE_ROLLBACK_FAILED", flush=True)
            raise Refusal("Approved release failed; only sanitized diagnostics reported.") from None
        print("VASA_RELEASE_ACTIVATION_OK", flush=True)
        print("VASA_DEPLOYMENT_OK", flush=True)


def config():
    compose("config", "--quiet")
    data = json.loads(compose("config", "--format", "json"))
    require(data["name"] == PROJECT, "Unexpected Compose project.")
    require(set(data["services"]) == set(SERVICES + DEPENDENCIES), "Unexpected Compose services.")
    require(
        data["services"]["vasa"]["image"] == "vasa-app:pinned"
        and data["services"]["voice"]["image"] == "vasa-app:pinned",
        "Unexpected app image.",
    )
    return data


def validate_web_bind(data):
    for service, address, published, target in (
        ("vasa", "172.16.2.1", "18081", 8080),
        ("evolution", "127.0.0.1", "18080", 4000),
    ):
        value = data["services"][service]
        ports = value.get("ports", [])
        require(
            isinstance(ports, list)
            and len(ports) == 1
            and isinstance(ports[0], dict)
            and ports[0].get("host_ip") == address
            and str(ports[0].get("published")) == published
            and ports[0].get("target") == target
            and ports[0].get("protocol", "tcp") == "tcp"
            and value.get("network_mode") != "host",
            "Staging web bind must match the exact private address/port.",
        )


def verify_running_web_bind():
    for service, address, published, target in (
        ("vasa", "172.16.2.1", "18081", "8080/tcp"),
        ("evolution", "127.0.0.1", "18080", "4000/tcp"),
    ):
        cid, _ = container(service)
        ports = json.loads(
            run("docker", "inspect", "--format", "{{json .NetworkSettings.Ports}}", cid)
        )
        require(
            isinstance(ports, dict)
            and ports.get(target) == [{"HostIp": address, "HostPort": published}]
            and all(not binding for key, binding in ports.items() if key != target),
            "Running staging web bind differs from the required private address/port.",
        )
    print("STAGING_PRIVATE_BIND_OK", flush=True)


def container(service):
    ids = compose("ps", "--all", "--quiet", service).splitlines()
    require(
        len(ids) == 1 and re.fullmatch(r"[a-f0-9]{12,64}", ids[0]) is not None,
        "Expected exactly one existing VASA container for " + service,
    )
    # Inspect only selected metadata: never inspect/dump container environment.
    value = json.loads(
        run(
            "docker",
            "inspect",
            "--format",
            '{"labels":{{json .Config.Labels}},"state":{{json .State}},'
            '"image":{{json .Image}},"restarts":{{.RestartCount}}}',
            ids[0],
        )
    )
    labels = value["labels"]
    require(
        labels.get("com.docker.compose.project") == PROJECT
        and labels.get("com.docker.compose.service") == service
        and labels.get("com.docker.compose.project.working_dir") == str(ROOT / "deploy"),
        "Container ownership labels do not match the existing deployment.",
    )
    return ids[0], value


def state_ok(value):
    state = value["state"]
    return (
        state["Status"] == "running"
        and not state.get("OOMKilled", False)
        and state.get("Health", {}).get("Status", "healthy") == "healthy"
    )


def voice_marker_lines(logs):
    markers = []
    for line in logs.split("\n"):
        if len(line) > 96:
            continue
        match = re.fullmatch(
            r"VOICE_(STARTUP|RUNTIME)_(STAGE|FAILED|ERROR)=([a-z_]+)", line, flags=re.ASCII
        )
        if match is None:
            continue
        phase, kind, value = match.groups()
        allowed = VOICE_ERRORS if kind == "ERROR" else VOICE_STAGES
        if value in allowed:
            markers.append(f"VOICE_{phase}_{kind}={value}")
    return markers[-64:]


def read_container_logs(cid, *, since=None):
    # Docker writes stderr logs to stderr even on success: capture both streams.
    # No raw log line reaches Actions.
    args = ["docker", "logs", "--tail", "200"]
    if since is not None:
        args.extend(["--since", since])
    args.append(cid)
    result = subprocess.run(
        args,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    require(result.returncode == 0, "Cannot inspect VASA startup logs.")
    return result.stdout + "\n" + result.stderr


def log_health(cid, started, worker=False):
    logs = read_container_logs(cid, since=started)
    markers = voice_marker_lines(logs) if worker else []
    require(
        not any("_FAILED=" in line or "_ERROR=" in line for line in markers),
        "Voice lifecycle failure markers found; raw logs withheld.",
    )
    failures = len(BAD_LOG.findall(logs))
    require(failures == 0, "VASA startup failure markers found; raw logs withheld.")
    return not worker or READY_MARKER in logs


def health(timeout=150, *, include_voice=True):
    apps = SERVICES if include_voice else ("vasa",)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready = True
        for service in DEPENDENCIES + apps:
            cid, value = container(service)
            if not state_ok(value):
                ready = False
                continue
            if service in SERVICES:
                ready &= log_health(cid, value["state"]["StartedAt"], service == "voice")
        if ready:
            break
        time.sleep(3)
    else:
        raise Refusal("Timed out waiting for VASA containers/worker startup.")
    compose(
        "exec",
        "-T",
        "vasa",
        "python",
        "-c",
        "import json,urllib.request; "
        "assert json.load(urllib.request.urlopen('http://127.0.0.1:8080/health/live',"
        "timeout=5))['status']=='alive'; "
        "assert json.load(urllib.request.urlopen('http://127.0.0.1:8080/health/ready',"
        "timeout=5))['status']=='ready'",
    )
    baseline = {service: container(service) for service in DEPENDENCIES + apps}
    time.sleep(8)
    for service, (cid, before) in baseline.items():
        after_id, after = container(service)
        require(
            cid == after_id
            and state_ok(after)
            and after["restarts"] == before["restarts"]
            and after["state"]["StartedAt"] == before["state"]["StartedAt"],
            "VASA process restarted or became unhealthy during stabilization.",
        )
        if service in SERVICES:
            require(
                log_health(cid, after["state"]["StartedAt"], service == "voice"),
                "Voice worker readiness marker is missing.",
            )
    print("VASA API live/ready, container health and process stability: OK", flush=True)
    if include_voice:
        print("Voice worker readiness: OK", flush=True)


def snapshot_services(services):
    result = {}
    for service in services:
        cid, value = container(service)
        require(state_ok(value), "Expected a healthy existing VASA service: " + service)
        result[service] = {
            "id": cid,
            "image": value["image"],
            "restarts": value["restarts"],
            "started": value["state"]["StartedAt"],
        }
    return result


def assert_unchanged(snapshot):
    require(
        snapshot_services(tuple(snapshot)) == snapshot,
        "Existing VASA service identity/image/restarts changed unexpectedly.",
    )


def bootstrap_topology():
    expected = snapshot_services(DEPENDENCIES + ("vasa",))
    require(
        not compose("ps", "--all", "--quiet", "voice"),
        "Bootstrap requires exactly zero existing voice containers.",
    )
    project_ids = run(
        "docker",
        "ps",
        "--all",
        "--no-trunc",
        "--filter",
        "label=com.docker.compose.project=" + PROJECT,
        "--format",
        "{{.ID}}",
    ).splitlines()
    require(
        len(project_ids) == len(expected)
        and set(project_ids) == {item["id"] for item in expected.values()},
        "Unexpected VASA project topology; bootstrap refused.",
    )
    return expected


def require_deepgram_key(data):
    # Compose resolves the existing private env_file. Do not read a cloud key,
    # accept a command-line key, or render the environment in logs/receipts.
    key = data["services"]["voice"].get("environment", {}).get("DEEPGRAM_API_KEY")
    require(isinstance(key, str) and bool(key.strip()), "DEEPGRAM_VPS_KEY_REQUIRED")


def compatible_config(before, after):
    require(
        {k: v for k, v in before.items() if k != "services"}
        == {k: v for k, v in after.items() if k != "services"},
        "Compose project/network/volume changes require manual review.",
    )
    for service in DEPENDENCIES:
        require(
            before["services"][service] == after["services"][service],
            "Dependency service configuration changed; automatic deployment refused.",
        )


def up_services(*services):
    require(bool(services) and set(services) <= set(SERVICES), "Invalid app service selection.")
    compose("up", "-d", "--no-deps", "--wait", "--wait-timeout", "150", *services, timeout=210)


def remove_bootstrapped_voice():
    if not compose("ps", "--all", "--quiet", "voice"):
        return
    # container() requires exactly one container and validates project, service,
    # and working-directory labels before this single-ID removal. No volumes.
    cid, _ = container("voice")
    run("docker", "container", "rm", "--force", cid)
    require(
        not compose("ps", "--all", "--quiet", "voice"), "New voice container could not be removed."
    )


def write_bootstrap_receipt(path, previous, target, status):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(
            {"previous_sha": previous, "target_sha": target, "mode": "bootstrap", "status": status},
            stream,
        )
        stream.write("\n")


def bootstrap(target, branch, previous):
    stage("BOOTSTRAP", "preflight")
    require(branch == BRANCH, "Staging checkout must already be on build/vasa-foundation.")
    require(re.fullmatch(r"[0-9a-f]{40}", target) is not None, "Invalid target commit.")
    local = ROOT / ".local"
    require(
        local.is_dir() and not local.is_symlink() and local.stat().st_uid == os.getuid(),
        "Missing owned .local directory.",
    )
    fd = os.open(local / "actions-deploy.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Refusal("Another staging deployment holds the project lock.") from exc
        require(
            not git("status", "--porcelain", "--untracked-files=all"),
            "Working tree has local modifications; nothing was overwritten.",
        )
        require(
            not git("ls-files", "--", *ENV_FILES),
            "Private runtime environment files must remain untracked.",
        )
        hashes = private_hashes()
        before_config = config()
        baseline = bootstrap_topology()
        require_deepgram_key(before_config)
        health(include_voice=False)
        assert_unchanged(baseline)
        print(
            "Bootstrap preflight: healthy four-service topology; private key configured.",
            flush=True,
        )
        print("PREVIOUS_SHA=" + previous + "\nTARGET_SHA=" + target, flush=True)
        stage("BOOTSTRAP", "git_fetch")
        git("fetch", "origin")
        require(
            git("rev-parse", "origin/" + BRANCH) == target,
            "Branch moved after dispatch; rerun against its current commit.",
        )
        git("merge-base", "--is-ancestor", previous, target)
        changed = git("diff", "--name-only", previous, target).splitlines()
        require(
            not any(p.startswith("migrations/") or p == "alembic.ini" for p in changed),
            "Schema changes require a separate operator-reviewed migration/backup plan.",
        )
        require(
            not git("ls-tree", "-r", "--name-only", target, "--", *ENV_FILES),
            "Target attempts to track private runtime environment files.",
        )
        old_image = baseline["vasa"]["image"]
        backup_tag = "vasa-app:bootstrap-rollback-" + previous
        stage("BOOTSTRAP", "rollback_image")
        rollback_image = acquire_rollback_image(old_image, previous, backup_tag)
        assert_unchanged(baseline)
        require(private_hashes() == hashes, "Private environment files changed unexpectedly.")
        receipt = local / "actions-bootstrap.json"
        write_bootstrap_receipt(receipt, previous, target, "in_progress")
        changed_checkout = app_attempted = voice_attempted = False
        for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, signal_failure)
        try:
            stage("BOOTSTRAP", "checkout")
            changed_checkout = True
            git("checkout", BRANCH)
            git("pull", "--ff-only", "origin", BRANCH)
            require(git("rev-parse", "HEAD") == target, "Target commit changed during pull.")
            after_config = config()
            compatible_config(before_config, after_config)
            require_deepgram_key(after_config)
            require(private_hashes() == hashes, "Private environment files changed unexpectedly.")
            assert_unchanged(baseline)
            require(
                not compose("ps", "--all", "--quiet", "voice"),
                "Voice appeared concurrently; bootstrap refused.",
            )
            print("Building the shared VASA app image for bootstrap.", flush=True)
            stage("BOOTSTRAP", "target_build")
            compose("build", "vasa", timeout=900)
            new_image = run("docker", "image", "inspect", "--format", "{{.Id}}", "vasa-app:pinned")
            if new_image != old_image or (
                before_config["services"]["vasa"] != after_config["services"]["vasa"]
            ):
                app_attempted = True
                stage("BOOTSTRAP", "vasa_update")
                up_services("vasa")
            # Recheck immediately before creation; rollback is allowed to remove
            # voice only once this invocation has attempted its creation.
            require(
                not compose("ps", "--all", "--quiet", "voice"),
                "Voice appeared concurrently; bootstrap refused.",
            )
            voice_attempted = True
            stage("BOOTSTRAP", "voice_create")
            up_services("voice")
            require(
                container("voice")[1]["image"] == new_image,
                "Voice is not using the newly built shared app image.",
            )
            require(
                container("vasa")[1]["image"] == new_image,
                "API and voice do not share the built app image.",
            )
            stage("BOOTSTRAP", "health")
            health()
            assert_unchanged({s: baseline[s] for s in DEPENDENCIES})
            if not app_attempted:
                assert_unchanged({"vasa": baseline["vasa"]})
            require(private_hashes() == hashes, "Private environment files changed unexpectedly.")
            write_bootstrap_receipt(receipt, previous, target, "healthy")
            print("VASA_BOOTSTRAP_OK", flush=True)
        except BaseException:
            for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
                signal.signal(sig, signal.SIG_IGN)
            print("VASA bootstrap failed; inspecting only VASA app/worker.", flush=True)
            diagnostics()
            try:
                stage("BOOTSTRAP", "rollback")
                if voice_attempted:
                    remove_bootstrapped_voice()
                if changed_checkout:
                    require(
                        not git("status", "--porcelain", "--untracked-files=all"),
                        "Concurrent local edits detected; controlled reset refused.",
                    )
                    git("reset", "--hard", previous)
                    require(private_hashes() == hashes, "Runtime configuration was not preserved.")
                    require(
                        config() == before_config, "Previous Compose configuration not restored."
                    )
                    # Restore the verified image: exact original when available,
                    # otherwise the clean PREVIOUS_SHA source build.
                    run("docker", "image", "tag", backup_tag, "vasa-app:pinned")
                    if app_attempted:
                        up_services("vasa")
                    stage("BOOTSTRAP", "rollback_health")
                    health(include_voice=False)
                    restored = bootstrap_topology()
                    require(
                        restored["vasa"]["image"]
                        == (rollback_image if app_attempted else old_image),
                        "Previous API image was not restored.",
                    )
                    assert_unchanged({s: baseline[s] for s in DEPENDENCIES})
                    if not app_attempted:
                        assert_unchanged({"vasa": baseline["vasa"]})
                    require(private_hashes() == hashes, "Runtime configuration was not preserved.")
                    write_bootstrap_receipt(receipt, previous, target, "rolled_back")
                    print("VASA_BOOTSTRAP_ROLLBACK_OK; bootstrap remains failed.", flush=True)
            except BaseException:
                print("VASA_BOOTSTRAP_ROLLBACK_FAILED; operator intervention required.", flush=True)
                diagnostics(report_voice_markers=False)
            raise Refusal("Bootstrap failed; see sanitized VASA status above.") from None


def private_hashes():
    result = {}
    for name in ENV_FILES:
        path = ROOT / name
        require(not path.is_symlink(), "Runtime environment symlinks are not supported.")
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    return result


def diagnostics(*, report_voice_markers=True):
    for service in SERVICES:
        try:
            cid, value = container(service)
            state = value["state"]
            print(
                f"{service}: running={state['Status'] == 'running'}, "
                f"oom={bool(state.get('OOMKilled'))}, restarts={value['restarts']}",
                flush=True,
            )
            if service == "voice" and report_voice_markers:
                # Capture the target container BEFORE rollback/removal, across
                # restarts rather than only the most recent StartedAt window.
                for marker in voice_marker_lines(read_container_logs(cid)):
                    print(marker, flush=True)
            try:
                log_health(cid, state["StartedAt"], service == "voice")
                print(
                    service + ": current-attempt log scan complete (content withheld)", flush=True
                )
            except Refusal:
                print(
                    service + ": startup log failure markers detected (content withheld)",
                    flush=True,
                )
        except (Refusal, ValueError, KeyError, OSError, subprocess.TimeoutExpired):
            print(service + ": container diagnostic unavailable", flush=True)


def signal_failure(_signum, _frame):
    raise Refusal("Deployment interrupted; attempting controlled rollback.")


def provider_smoke():
    # Capture stdout/stderr even on failure; never forward arbitrary container logs.
    result = compose(
        "exec",
        "-T",
        "vasa",
        "python",
        "scripts/live_provider_smoke.py",
        timeout=105,
        capture_smoke=True,
    )
    approved = []
    fields = set()
    for line in result.stdout.splitlines():
        if (
            re.fullmatch(r"(?:LLM|DEEPGRAM)_SMOKE_OK", line)
            or re.fullmatch(
                r"(?:LLM|DEEPGRAM)_SMOKE_FAILED=(?:missing_configuration|invalid_configuration|invalid_response|timeout|provider_error|internal_error)",
                line,
            )
            or re.fullmatch(
                r"(?:LLM_FIRST_TOKEN|LLM_TOTAL|DEEPGRAM_FIRST_AUDIO|DEEPGRAM_TOTAL|DEEPGRAM_AUDIO)_MS=[0-9]{1,8}\.[0-9]{2}",
                line,
            )
        ):
            field = line.split("=", 1)[0]
            if field not in fields:
                approved.append(line)
                fields.add(field)
    for line in approved:
        print(line, flush=True)
    require(
        result.returncode == 0
        and "LLM_SMOKE_OK" in approved
        and "DEEPGRAM_SMOKE_OK" in approved
        and not any("_SMOKE_FAILED=" in line for line in approved),
        "Live provider smoke failed; raw output withheld.",
    )


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def host_web_checks():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    for url, status in (
        ("http://172.16.2.1:18081/login", 200),
        ("http://172.16.2.1:18081/dashboard", 401),
        ("http://172.16.2.1:18081/dashboard/assets/styles.css", 200),
        ("http://172.16.2.1:18081/dashboard/assets/login.js", 200),
        ("http://127.0.0.1:18080/server/ok", 200),
    ):
        try:
            response = opener.open(url, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            require(response.code == status, "Staging loopback HTTP validation failed.")
            require(len(response.read(65537)) <= 65536, "Staging HTTP response limit exceeded.")
    print("STAGING_HOST_BINDINGS_OK", flush=True)


def post_validation(target, *, source=None):
    release = ROOT if source is None else source
    require(
        git("-C", str(release), "rev-parse", "HEAD") == target,
        "Post-deploy checkout SHA mismatch.",
    )
    verify_running_web_bind()
    sanitizer = release / "scripts/sanitize_call_diagnostics.py"
    require(sanitizer.is_file() and not sanitizer.is_symlink(), "Call sanitizer is missing.")
    output = run(
        "python3", str(sanitizer), input_text="private-fixture\nCALL_MEDIA=receive_recovered\n"
    )
    require(output == "CALL_MEDIA=receive_recovered", "Call sanitizer validation failed.")
    print("STAGING_SANITIZER_OK", flush=True)
    host_web_checks()
    expected = {
        "STAGING_LOGIN_OK",
        "STAGING_DASHBOARD_AUTH_OK",
        "STAGING_STATIC_OK",
        "STAGING_EVOLUTION_HTTP_OK",
        "STAGING_EVOLUTION_LICENSE_OK",
        "STAGING_INSTANCES_OK",
    }
    result = compose(
        "exec",
        "-T",
        "vasa",
        "python",
        "-m",
        "vasa.staging_validation",
        timeout=90,
        capture_validation=True,
    )
    approved = set(result.stdout.splitlines()) & expected
    for marker in sorted(approved):
        print(marker, flush=True)
    failed = False
    for marker in sorted(set(result.stdout.splitlines())):
        if re.fullmatch(
            r"STAGING_VALIDATION_FAILED=(?:settings|login|dashboard_auth|static|evolution_http|license|instances)",
            marker,
        ):
            failed = True
            print(marker, flush=True)
    require(
        result.returncode == 0 and approved == expected and not failed,
        "Staging web/Evolution validation incomplete; raw output withheld.",
    )
    print("DEPLOYED_SHA=" + target, flush=True)


def deploy(target, branch, previous, *, smoke=False):
    stage("DEPLOY", "preflight")
    require(branch == BRANCH, "Staging checkout must already be on build/vasa-foundation.")
    require(re.fullmatch(r"[0-9a-f]{40}", target) is not None, "Invalid target commit.")
    local = ROOT / ".local"
    require(
        local.is_dir() and not local.is_symlink() and local.stat().st_uid == os.getuid(),
        "Missing owned .local directory.",
    )
    lock_path = local / "actions-deploy.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Refusal("Another staging deployment holds the project lock.") from exc
        require(
            not git("status", "--porcelain", "--untracked-files=all"),
            "Working tree has local modifications; nothing was overwritten.",
        )
        hashes = private_hashes()
        require(
            not git("ls-files", "--", *ENV_FILES), "Private runtime files must remain untracked."
        )
        before_config = config()
        # This is an update path, not a bootstrap: all existing dependencies and
        # both app services must be healthy before any code/image mutation.
        health()
        dependencies = snapshot_services(DEPENDENCIES)
        previous_apps = snapshot_services(SERVICES)
        old_images = {container(s)[1]["image"] for s in SERVICES}
        require(len(old_images) == 1, "App/worker do not share the expected existing image.")
        print("Preflight healthy; fetching the staging branch.", flush=True)
        stage("DEPLOY", "git_fetch")
        git("fetch", "origin")
        require(
            git("rev-parse", "origin/" + BRANCH) == target,
            "Branch moved after dispatch; rerun against its current commit.",
        )
        git("merge-base", "--is-ancestor", previous, target)
        changed = git("diff", "--name-only", previous, target).splitlines()
        require(
            not any(p.startswith("migrations/") or p == "alembic.ini" for p in changed),
            "Schema changes require a separate operator-reviewed migration/backup plan.",
        )
        require(
            not git("ls-tree", "-r", "--name-only", target, "--", *ENV_FILES),
            "Target attempts to track private runtime environment files.",
        )
        backup_tag = "vasa-app:rollback-" + previous
        stage("DEPLOY", "rollback_image")
        rollback_image = acquire_rollback_image(next(iter(old_images)), previous, backup_tag)
        require(private_hashes() == hashes, "Private environment files changed unexpectedly.")
        print("PREVIOUS_SHA=" + previous + "\nTARGET_SHA=" + target, flush=True)
        receipt = local / "actions-deployment.json"
        receipt.write_text(
            json.dumps({"previous_sha": previous, "target_sha": target, "status": "in_progress"})
            + "\n"
        )
        receipt.chmod(0o600)
        needs_build = any(
            p.startswith(("src/", "docker/"))
            or p
            in (
                "pyproject.toml",
                "uv.lock",
                ".dockerignore",
                "scripts/evolution_status.py",
                "scripts/prepare_speech.py",
                "scripts/prepare_knowledge.py",
                "scripts/live_provider_smoke.py",
                "scripts/diagnose_llm_sse.py",
            )
            for p in changed
        )
        changed_checkout = False
        app_update_attempted = False
        touched = []
        for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, signal_failure)
        try:
            stage("DEPLOY", "checkout")
            changed_checkout = True
            git("checkout", BRANCH)
            git("pull", "--ff-only", "origin", BRANCH)
            require(git("rev-parse", "HEAD") == target, "Target commit changed during pull.")
            after_config = config()
            require(private_hashes() == hashes, "Private environment files changed unexpectedly.")
            # Never alter dependency topology, networks, volumes or other services.
            validate_web_bind(after_config)
            require(
                {k: v for k, v in before_config.items() if k != "services"}
                == {k: v for k, v in after_config.items() if k != "services"},
                "Compose project/network/volume changes require manual review.",
            )
            for name in DEPENDENCIES:
                require(
                    before_config["services"][name] == after_config["services"][name],
                    "Dependency service configuration changed; automatic deployment refused.",
                )
            touched = [
                s
                for s in SERVICES
                if needs_build or before_config["services"][s] != after_config["services"][s]
            ]
            if needs_build:
                # Only vasa has a build definition; voice uses that same image.
                print("Building the VASA app image (shared by API and worker).", flush=True)
                stage("DEPLOY", "target_build")
                compose("build", "vasa", timeout=900)
            if touched:
                print("Updating only VASA app services: " + ", ".join(touched), flush=True)
                stage("DEPLOY", "vasa_update")
                app_update_attempted = True
                compose(
                    "up",
                    "-d",
                    "--no-deps",
                    "--wait",
                    "--wait-timeout",
                    "150",
                    *touched,
                    timeout=210,
                )
            require(private_hashes() == hashes, "Private environment files changed unexpectedly.")
            print("Validating VASA health and worker startup.", flush=True)
            stage("DEPLOY", "health")
            health()
            stage("DEPLOY", "post_validation")
            post_validation(target)
            if smoke:
                stage("DEPLOY", "provider_smoke")
                provider_smoke()
                stage("DEPLOY", "health")
                health()
            require(private_hashes() == hashes, "Runtime configuration was not preserved.")
            assert_unchanged(dependencies)
            current_apps = snapshot_services(SERVICES)
            for service, previous_app in previous_apps.items():
                current_app = current_apps[service]
                require(
                    current_app["restarts"] == previous_app["restarts"]
                    if current_app["id"] == previous_app["id"]
                    else service in touched and current_app["restarts"] == 0,
                    "Unexpected VASA app restart count or recreation.",
                )
            receipt.write_text(
                json.dumps(
                    {
                        "previous_sha": previous,
                        "target_sha": target,
                        "status": "healthy",
                        "services": touched,
                    }
                )
                + "\n"
            )
            print("VASA_DEPLOYMENT_OK", flush=True)
        except BaseException:
            # Do not recursively interrupt rollback when SSH disconnects.
            for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
                signal.signal(sig, signal.SIG_IGN)
            print("VASA deployment failed; inspecting only VASA app/worker.", flush=True)
            diagnostics()
            try:
                stage("DEPLOY", "rollback")
                if changed_checkout:
                    require(
                        not git("status", "--porcelain", "--untracked-files=all"),
                        "Concurrent local edits detected; controlled reset refused.",
                    )
                    # Sole permitted destructive Git operation: known prior commit,
                    # under the deployment lock, after a clean-tree recheck.
                    git("reset", "--hard", previous)
                    require(private_hashes() == hashes, "Runtime configuration was not preserved.")
                    config()
                    run("docker", "image", "tag", backup_tag, "vasa-app:pinned")
                    if app_update_attempted:
                        compose(
                            "up",
                            "-d",
                            "--no-deps",
                            "--wait",
                            "--wait-timeout",
                            "150",
                            *touched,
                            timeout=210,
                        )
                    stage("DEPLOY", "rollback_health")
                    health()
                    assert_unchanged(dependencies)
                    require(
                        all(container(s)[1]["image"] == rollback_image for s in touched)
                        if app_update_attempted
                        else all(container(s)[1]["image"] in old_images for s in SERVICES),
                        "Verified rollback app image was not restored.",
                    )
                    receipt.write_text(
                        json.dumps(
                            {
                                "previous_sha": previous,
                                "target_sha": target,
                                "status": "rolled_back",
                            }
                        )
                        + "\n"
                    )
                    print("VASA_ROLLBACK_OK; deployment remains failed.", flush=True)
            except BaseException:
                print("VASA_ROLLBACK_FAILED; operator intervention required.", flush=True)
                diagnostics(report_voice_markers=False)
            raise Refusal("Deployment failed; see sanitized VASA status above.") from None


def main():
    try:
        require(
            len(sys.argv) in (3, 4, 5, 7, 8) and sys.argv[1] in ("check", "bootstrap", "deploy"),
            "Invalid invocation.",
        )
        smoke = sys.argv[3] if len(sys.argv) >= 4 else "false"
        recovery = sys.argv[4] if len(sys.argv) >= 5 else "none"
        release = sys.argv[5] if len(sys.argv) >= 7 else ""
        approved_sql = sys.argv[6] if len(sys.argv) >= 7 else ""
        recipient = sys.argv[7] if len(sys.argv) == 8 else ""
        require(
            recovery in ("none", "investigate", "prepare", "activate", "smtp_check"),
            "Invalid recovery option.",
        )
        require(
            recovery == "none" or (sys.argv[1] == "check" and smoke == "false"),
            "Recovery inspection requires check mode.",
        )
        require(smoke in ("true", "false"), "Invalid provider smoke option.")
        require(smoke == "false" or sys.argv[1] == "deploy", "Smoke requires deploy mode.")
        if recovery == "activate":
            require(
                re.fullmatch(r"[0-9a-f]{40}", release) is not None
                and re.fullmatch(r"[0-9a-f]{64}", approved_sql) is not None,
                "Explicit release SHA and approved migration SQL hash are required.",
            )
        elif recovery == "smtp_check":
            require(
                re.fullmatch(r"[0-9a-f]{40}", release) is not None
                and not approved_sql
                and bool(recipient),
                "Explicit SMTP release and test mailbox required.",
            )
        else:
            require(
                not release and not approved_sql, "Release approval applies only to activation."
            )
        require(
            not recipient or recovery == "smtp_check", "SMTP mailbox applies only to SMTP test."
        )
        branch, previous = preflight()
        if sys.argv[1] == "check":
            if recovery == "investigate":
                investigate()
            elif recovery == "prepare":
                investigate()
                prepare_recovery(sys.argv[2])
            elif recovery == "activate":
                prepare_recovery(release, exact_tip=False)
                activate_recovery(release, approved_sql)
            elif recovery == "smtp_check":
                smtp_acceptance(release, recipient)
            if recovery == "none":
                print(
                    "Read-only check: no fetch, checkout, writes, builds or restarts.", flush=True
                )
            elif recovery == "investigate":
                print(
                    "Investigation preserves files/services; one bounded auth rate-limit probe.",
                    flush=True,
                )
            elif recovery == "prepare":
                print("Preparation only: no live migration or application activation.", flush=True)
            elif recovery == "smtp_check":
                print("SMTP acceptance only; inbox confirmation remains required.", flush=True)
            else:
                print("Approved immutable staging activation completed.", flush=True)
            print("VASA_VPS_CONNECTIVITY_OK", flush=True)
        elif sys.argv[1] == "bootstrap":
            bootstrap(sys.argv[2], branch, previous)
        else:
            if smoke == "true":
                deploy(sys.argv[2], branch, previous, smoke=True)
            else:
                deploy(sys.argv[2], branch, previous)
    except (Refusal, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        # Only our fixed messages are safe; exception values from dependencies are not.
        print(
            str(exc)
            if isinstance(exc, Refusal)
            else "VASA preflight/deployment failed; raw exception withheld.",
            file=sys.stderr,
            flush=True,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
