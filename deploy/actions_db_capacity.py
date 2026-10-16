"""Read-only PostgreSQL capacity diagnostics with numeric-only output."""

import ipaddress
import json
import re

KEYS = (
    "max_connections",
    "reserved_connections",
    "superuser_reserved_connections",
    "total_connections",
    "primary_db_connections",
    "current_role_connections",
    "primary_db_idle",
    "primary_db_active",
    "role_connection_limit",
    "database_connection_limit",
    "evolution_auth_connections",
    "evolution_users_connections",
)
QUERY = """
SELECT json_build_object(
 'max_connections', current_setting('max_connections')::integer,
 'reserved_connections', coalesce(current_setting('reserved_connections', true), '0')::integer,
 'superuser_reserved_connections', current_setting('superuser_reserved_connections')::integer,
 'total_connections', (SELECT count(*) FROM pg_stat_activity
   WHERE pid <> pg_backend_pid()),
 'primary_db_connections', (SELECT count(*) FROM pg_stat_activity
   WHERE datname=current_database() AND pid <> pg_backend_pid()),
 'current_role_connections', (SELECT count(*) FROM pg_stat_activity
   WHERE usename=current_user AND pid <> pg_backend_pid()),
 'primary_db_idle', (SELECT count(*) FROM pg_stat_activity
   WHERE datname=current_database() AND state='idle' AND pid <> pg_backend_pid()),
 'primary_db_active', (SELECT count(*) FROM pg_stat_activity
   WHERE datname=current_database() AND state='active' AND pid <> pg_backend_pid()),
 'role_connection_limit', (SELECT rolconnlimit FROM pg_roles WHERE rolname=current_user),
 'database_connection_limit', (SELECT datconnlimit FROM pg_database
   WHERE datname=current_database()),
 'evolution_auth_connections', (SELECT count(*) FROM pg_stat_activity
   WHERE datname='vasa_evolution_auth' AND pid <> pg_backend_pid()),
 'evolution_users_connections', (SELECT count(*) FROM pg_stat_activity
   WHERE datname='vasa_evolution_users' AND pid <> pg_backend_pid())
)
"""


def diagnose(namespace):
    """Use the deployment controller's validated container and captured executor."""
    try:
        postgres, _ = namespace["container"]("postgres")
        result = namespace["capture"](
            "docker",
            "exec",
            postgres,
            "sh",
            "-ec",
            'exec psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$1"',
            "sh",
            QUERY,
            timeout=20,
        )
        if result.returncode != 0 or len(result.stdout) > 4096:
            raise ValueError
        values = json.loads(result.stdout)
        if not isinstance(values, dict) or set(values) != set(KEYS):
            raise ValueError
        for key, value in values.items():
            minimum = -1 if key in {"role_connection_limit", "database_connection_limit"} else 0
            if type(value) is not int or not minimum <= value <= 10000000:
                raise ValueError
        for key in KEYS:
            print("DB_CAPACITY_" + key.upper() + "=" + str(values[key]), flush=True)
        return True
    except Exception:
        print("DB_CAPACITY_UNAVAILABLE", flush=True)
        diagnose_sockets(namespace)
        return False


def diagnose_sockets(namespace):
    """Attribute established PostgreSQL sockets without opening a database session."""
    try:
        capture = namespace["capture"]
        postgres, _ = namespace["container"]("postgres")
        configured = capture(
            "docker",
            "exec",
            postgres,
            "sh",
            "-ec",
            'exec postgres -D "$PGDATA" -C max_connections',
            timeout=10,
        )
        maximum = configured.stdout.strip()
        if configured.returncode != 0 or re.fullmatch(r"[0-9]{1,8}", maximum) is None:
            raise ValueError
        addresses = {}
        for service in ("vasa", "voice", "evolution"):
            cid, _ = namespace["container"](service)
            result = capture(
                "docker",
                "inspect",
                "--format",
                "{{json .NetworkSettings.Networks}}",
                cid,
                timeout=10,
            )
            if result.returncode != 0 or len(result.stdout) > 65536:
                raise ValueError
            networks = json.loads(result.stdout)
            if not isinstance(networks, dict):
                raise ValueError
            for network in networks.values():
                if not isinstance(network, dict):
                    raise ValueError
                for key in ("IPAddress", "GlobalIPv6Address"):
                    value = network.get(key)
                    if value:
                        addresses[ipaddress.ip_address(value)] = service
        counts = dict.fromkeys(("vasa", "voice", "evolution", "other", "total"), 0)
        for table in ("/proc/net/tcp", "/proc/net/tcp6"):
            result = capture("docker", "exec", postgres, "cat", table, timeout=10)
            if result.returncode != 0 or len(result.stdout) > 4194304:
                raise ValueError
            for line in result.stdout.splitlines()[1:]:
                columns = line.split()
                if len(columns) < 4:
                    raise ValueError
                local, remote, state = columns[1:4]
                if state != "01" or not local.endswith(":1538"):
                    continue
                encoded, separator, port = remote.partition(":")
                if not separator or re.fullmatch(r"[0-9A-Fa-f]{4}", port) is None:
                    raise ValueError
                raw = bytes.fromhex(encoded)
                if len(raw) == 4:
                    address = ipaddress.ip_address(raw[::-1])
                elif len(raw) == 16:
                    address = ipaddress.ip_address(
                        b"".join(raw[i : i + 4][::-1] for i in range(0, 16, 4))
                    )
                    address = address.ipv4_mapped or address
                else:
                    raise ValueError
                counts[addresses.get(address, "other")] += 1
                counts["total"] += 1
        print("DB_CONFIG_MAX_CONNECTIONS=" + maximum, flush=True)
        for key, value in counts.items():
            print("DB_SOCKET_" + key.upper() + "=" + str(value), flush=True)
        return True
    except Exception:
        print("DB_SOCKET_UNAVAILABLE", flush=True)
        return False
