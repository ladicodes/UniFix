"""Run the real-TESTNET end-to-end suite through the HTTP API and write a tx-hash report.

    uv run python -m scripts.testnet deploy          # once per testnet reset (var/testnet/deployment.json)
    uv run python -m scripts.e2e_testnet             # runs every @pytest.mark.testnet test
    uv run python -m scripts.e2e_testnet -k journey  # extra pytest arguments are passed through

Covered (tests/testnet): the PRD journey (sign-up -> verified professional -> request -> quote -> fund ->
chat -> complete -> release -> review -> rating -> admin view) with negative paths (unauthorized calls,
invalid transitions, duplicate funding, duplicate review, settled-release retry); fund -> refund;
keeper auto-release; the three arbiter outcomes; both concessions; on-chain refusals.

The report (var/testnet/E2E_REPORT.md) lists every recorded step with its stellar.expert link. RPC
outages surface as CHAIN_UNAVAILABLE test errors; re-run the affected tests (``-k name``).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
OUT = BACKEND / "var" / "testnet"
EXPLORER = "https://stellar.expert/explorer/testnet/tx/"


def _report(started: float, exit_code: int) -> Path:
    lines = [
        "# UniFix testnet E2E report",
        "",
        f"- Run at: {time.strftime('%Y-%m-%d %H:%M:%S %Z', time.localtime(started))}",
        f"- pytest exit code: {exit_code} ({'passed' if exit_code == 0 else 'see the pytest output'})",
        "",
    ]
    for record in sorted(OUT.glob("e2e-*.json")):
        if record.stat().st_mtime < started:
            continue
        lines += [f"## {record.stem}", "", "| Step | Transaction |", "|---|---|"]
        for step in json.loads(record.read_text()):
            tx = step.get("tx")
            link = f"[{tx[:12]}…]({EXPLORER}{tx})" if tx else step.get("refused", "")
            lines.append(f"| {step.get('step', '')} | {link} |")
        lines.append("")
    path = OUT / "E2E_REPORT.md"
    path.write_text("\n".join(lines))
    return path


def main(argv: list[str]) -> int:
    if not (OUT / "deployment.json").exists():
        print("var/testnet/deployment.json is missing: run `uv run python -m scripts.testnet deploy` first.")
        return 2
    started = time.time()
    env = {**os.environ, "UNIFIX_TESTNET": "1"}
    command = [sys.executable, "-m", "pytest", "-m", "testnet", "-v", "-s", *argv]
    exit_code = subprocess.call(command, cwd=BACKEND, env=env)  # noqa: S603  (fixed argv, no shell)
    print(f"\nReport: {_report(started, exit_code)}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
