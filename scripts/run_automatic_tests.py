"""Run grouped automatic checks for the thesis prototype.

The default command runs fast Python tests only. Use flags for checks that
require Node/Hardhat or the frontend toolchain.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], cwd: Path = PROJECT_ROOT, env: dict[str, str] | None = None) -> int:
    print(f"\n$ {' '.join(command)}", flush=True)
    completed = subprocess.run(command, cwd=cwd, env=env, check=False)
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Run automatic test layers.")
    parser.add_argument(
        "--python",
        action="store_true",
        help="Run the default Python pytest suite.",
    )
    parser.add_argument(
        "--contract",
        action="store_true",
        help="Run Hardhat smart contract tests.",
    )
    parser.add_argument(
        "--frontend",
        action="store_true",
        help="Run the frontend TypeScript/Vite build check.",
    )
    parser.add_argument(
        "--integration",
        action="store_true",
        help="Run optional pytest integration tests; requires Hardhat RPC and deployment.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run Python, contract, and frontend checks. Integration remains opt-in.",
    )
    args = parser.parse_args()

    if not any([args.python, args.contract, args.frontend, args.integration, args.all]):
        args.python = True

    checks: list[tuple[list[str], Path, dict[str, str] | None]] = []
    if args.python or args.all:
        checks.append(([sys.executable, "-m", "pytest"], PROJECT_ROOT, None))
    if args.contract or args.all:
        checks.append((["npx", "hardhat", "test"], PROJECT_ROOT / "blockchain", None))
    if args.frontend or args.all:
        checks.append((["npm", "run", "build"], PROJECT_ROOT / "frontend", None))
    if args.integration:
        env = os.environ.copy()
        env["PHE_RUN_BLOCKCHAIN_INTEGRATION"] = "1"
        checks.append(
            (
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "tests/test_blockchain_integration_smoke.py",
                    "-m",
                    "integration",
                ],
                PROJECT_ROOT,
                env,
            )
        )

    for command, cwd, env in checks:
        status = run(command, cwd=cwd, env=env)
        if status != 0:
            return status
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
