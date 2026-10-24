"""Create a private .env with fresh, distinct agent seeds.

Never prints seed values. Refuses to overwrite an existing .env unless
--rotate is given, in which case only the seed lines are replaced.
Run from the repository root:  python scripts/new_local_env.py [--rotate]
"""

import os
import secrets
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
EXAMPLE = ROOT / ".env.example"
SEED_KEYS = (
    "ORCHESTRATOR_SEED",
    "RESEARCH_AGENT_SEED",
    "ANALYSIS_AGENT_SEED",
    "TEST_CLIENT_SEED",
)


def main() -> int:
    rotate = "--rotate" in sys.argv
    if ENV.exists() and not rotate:
        print(".env already exists. Use --rotate to replace only the seed values.")
        return 1
    source = ENV if ENV.exists() else EXAMPLE
    lines = source.read_text().splitlines()
    seeds = {key: secrets.token_hex(32) for key in SEED_KEYS}
    assert len(set(seeds.values())) == len(seeds)

    written = set()
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in seeds:
            out.append(f"{key}={seeds[key]}")
            written.add(key)
        else:
            out.append(line)
    out += [f"{key}={seeds[key]}" for key in SEED_KEYS if key not in written]

    ENV.write_text("\n".join(out) + "\n")
    os.chmod(ENV, stat.S_IRUSR | stat.S_IWUSR)
    print(f"Wrote {len(seeds)} new distinct seeds to .env (values not shown; file mode 600).")
    print("Agent addresses derive from these seeds, so they change after rotation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
