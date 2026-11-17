"""Operational commands.

uv run python -m app.cli create-admin --email ops@example.com --name "UniFix Ops"
(the password is read from the UNIFIX_ADMIN_PASSWORD env var or prompted for; never a flag)
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

from app.core.config import get_settings
from app.core.container import build_services
from app.core.errors import AppError
from app.modules.users import service as users_service


async def _create_admin(email: str, name: str) -> int:
    password = os.environ.get("UNIFIX_ADMIN_PASSWORD") or getpass.getpass("Admin password (10-128 chars): ")
    services = build_services(get_settings())
    try:
        async with services.session_factory() as session:
            user = await users_service.create_admin(
                session, services, email=email, name=name, password=password
            )
        print(f"Created admin {user.email} ({user.id})")
        return 0
    except AppError as exc:
        print(f"Error: {exc.detail}", file=sys.stderr)
        return 1
    finally:
        await services.engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser("create-admin", help="Create an administrator account")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", required=True)
    args = parser.parse_args(argv)
    if args.command == "create-admin":
        return asyncio.run(_create_admin(args.email, args.name))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
