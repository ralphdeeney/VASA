"""Operator-requested SMTP acceptance only; never marks mailbox delivery verified."""

import argparse
import asyncio
import json

from vasa.config import Settings
from vasa.saas.mailer import MailUnavailable, SMTPMailer


async def check(recipient: str) -> int:
    # Exact single mailbox only; never accept a recipient list or message material.
    if (
        recipient.count("@") != 1
        or not all(recipient.split("@"))
        or any(c.isspace() or ord(c) < 32 or c in ",;<>" for c in recipient)
        or len(recipient) > 254
    ):
        print(json.dumps({"status": "failed", "code": "invalid_recipient"}))
        return 2
    try:
        mailer = SMTPMailer(Settings())
        await mailer.acceptance_smoke(recipient)
    except MailUnavailable as error:
        print(json.dumps({"status": "failed", "code": error.code}))
        return 1
    except Exception:
        print(json.dumps({"status": "failed", "code": "configuration_invalid"}))
        return 1
    print(json.dumps({"status": "smtp_accepted", "mailbox_delivery_verified": False}))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipient", required=True, help="Operator-provided test mailbox")
    arguments = parser.parse_args()
    raise SystemExit(asyncio.run(check(arguments.recipient)))


if __name__ == "__main__":
    main()
