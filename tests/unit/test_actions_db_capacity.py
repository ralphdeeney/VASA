"""Capacity probes expose numeric aggregates and never raw database errors."""

import json
from types import SimpleNamespace

import pytest

from deploy import actions_db_capacity as capacity


def test_capacity_reports_only_valid_numeric_aggregates(capsys):
    commands = []
    values = dict.fromkeys(capacity.KEYS, 1)
    values["role_connection_limit"] = -1
    values["database_connection_limit"] = -1

    def capture(*args, **kwargs):
        commands.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps(values), stderr="private password")

    assert capacity.diagnose({"container": lambda name: ("owned-postgres", {}), "capture": capture})
    output = capsys.readouterr().out
    assert "private" not in output
    assert "DB_CAPACITY_ROLE_CONNECTION_LIMIT=-1" in output
    args, kwargs = commands[0]
    assert args[:4] == ("docker", "exec", "owned-postgres", "sh")
    assert "$POSTGRES_USER" in args[5] and "$POSTGRES_DB" in args[5]
    assert args[-1] == capacity.QUERY
    assert kwargs == {"timeout": 20}
    assert "SELECT" in capacity.QUERY and "ALTER" not in capacity.QUERY


@pytest.mark.parametrize("output", ["secret raw body", '{"password":"secret"}', "[]", "null"])
def test_invalid_output_never_reaches_logs(capsys, output):
    assert not capacity.diagnose(
        {
            "container": lambda _: ("owned-postgres", {}),
            "capture": lambda *a, **k: SimpleNamespace(returncode=0, stdout=output),
        }
    )
    assert capsys.readouterr().out == "DB_CAPACITY_UNAVAILABLE\nDB_SOCKET_UNAVAILABLE\n"


def test_database_connection_failure_never_prints_stderr(capsys):
    assert not capacity.diagnose(
        {
            "container": lambda _: ("owned-postgres", {}),
            "capture": lambda *a, **k: SimpleNamespace(
                returncode=1, stdout="secret", stderr="53300 secret"
            ),
        }
    )
    assert capsys.readouterr().out == "DB_CAPACITY_UNAVAILABLE\nDB_SOCKET_UNAVAILABLE\n"


@pytest.mark.parametrize("value", [True, "1", -2, 10000001])
def test_non_numeric_or_out_of_bounds_values_rejected(capsys, value):
    values = dict.fromkeys(capacity.KEYS, 1)
    values["max_connections"] = value
    assert not capacity.diagnose(
        {
            "container": lambda _: ("owned-postgres", {}),
            "capture": lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps(values)),
        }
    )
    assert capsys.readouterr().out == "DB_CAPACITY_UNAVAILABLE\nDB_SOCKET_UNAVAILABLE\n"


def test_socket_fallback_counts_peers_without_printing_addresses(capsys):
    header = "sl local_address rem_address st tx_queue"
    tcp = (
        header
        + "\n"
        + "\n".join(
            [
                "0: 020012AC:1538 030012AC:C001 01 0000",
                "1: 020012AC:1538 030012AC:C002 01 0000",
                "2: 020012AC:1538 040012AC:C003 01 0000",
                "3: 020012AC:1538 050012AC:C004 01 0000",
                "4: 020012AC:1538 060012AC:C005 01 0000",
                "5: 020012AC:1538 060012AC:C006 06 0000",
            ]
        )
    )
    addresses = {"vasa": "172.18.0.3", "voice": "172.18.0.4", "evolution": "172.18.0.5"}
    calls = []

    def capture(*args, **kwargs):
        calls.append(args)
        if args[:2] == ("docker", "inspect"):
            output = json.dumps({"private-network": {"IPAddress": addresses[args[-1]]}})
        elif args[-1] == "/proc/net/tcp":
            output = tcp
        elif args[-1] == "/proc/net/tcp6":
            output = header
        else:
            output = "100\n"
        return SimpleNamespace(returncode=0, stdout=output, stderr="private")

    assert capacity.diagnose_sockets({"container": lambda name: (name, {}), "capture": capture})
    assert capsys.readouterr().out.splitlines() == [
        "DB_CONFIG_MAX_CONNECTIONS=100",
        "DB_SOCKET_VASA=2",
        "DB_SOCKET_VOICE=1",
        "DB_SOCKET_EVOLUTION=1",
        "DB_SOCKET_OTHER=1",
        "DB_SOCKET_TOTAL=5",
    ]
    assert all("kill" not in command and "pg_terminate_backend" not in command for command in calls)


def test_malicious_socket_output_is_discarded(capsys):
    assert not capacity.diagnose_sockets(
        {
            "container": lambda name: (name, {}),
            "capture": lambda *a, **k: SimpleNamespace(returncode=0, stdout="secret private-body"),
        }
    )
    assert capsys.readouterr().out == "DB_SOCKET_UNAVAILABLE\n"
