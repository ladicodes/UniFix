"""Operational commands.

uv run python -m app.cli seed

uv run python -m app.cli create-admin --email ops@example.com --name "UniFix Ops"
(the password is read from the UNIFIX_ADMIN_PASSWORD env var or prompted for; never a flag)

uv run python -m app.cli reconcile --once     # one reconciler pass (poll, scan, apply, keeper)
uv run python -m app.cli reconcile --full     # compare every open escrow with get_escrow (§10)
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
from app.seed import seed


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


async def _seed() -> int:
    services = build_services(get_settings())
    try:
        async with services.session_factory() as session:
            categories, campuses = await seed(session)
        print(f"Seed complete: {categories} categories and {campuses} campuses added")
        return 0
    finally:
        await services.engine.dispose()


async def _reconcile(full: bool) -> int:
    from app.modules.payments.reconciler import Reconciler
    from app.modules.stellar.context import build_stellar, startup_check

    settings = get_settings()
    services = build_services(settings)
    stellar = build_stellar(settings)
    try:
        if stellar.gateway is None:
            print("Escrow is not configured (ESCROW_CONTRACT_ID).", file=sys.stderr)
            return 1
        await startup_check(stellar)
        reconciler = Reconciler(services, stellar)
        if full:
            applied = await reconciler.full_sweep()
            print(f"Full sweep complete: {applied} state changes applied")
        else:
            await reconciler.tick()
            print("Reconciler pass complete")
        return 0
    finally:
        if stellar.gateway is not None:
            await stellar.gateway.close()
        await services.engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser("create-admin", help="Create an administrator account")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", required=True)
    commands.add_parser("seed", help="Insert reference categories and campuses (idempotent)")
    reconcile = commands.add_parser("reconcile", help="Run the chain reconciler once, or a full state sweep")
    mode = reconcile.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--full", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "reconcile":
        return asyncio.run(_reconcile(args.full))
    if args.command == "create-admin":
        return asyncio.run(_create_admin(args.email, args.name))
    if args.command == "seed":
        return asyncio.run(_seed())
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
