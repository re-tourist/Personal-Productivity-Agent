"""Create private local test credentials, without printing tokens or overwriting files."""
import argparse
import hashlib
import json
import os
import secrets
from pathlib import Path

from productivity_agent.infrastructure.security.accounts import Accounts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=Path(".ppa-data/test-auth"))
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    auth = args.out_dir / "accounts.auth.json"
    clients = args.out_dir / "client-tokens.auth.json"
    if auth.exists() or clients.exists():
        parser.error("Refusing to overwrite existing credential files")
    tokens = {name: secrets.token_urlsafe(32) for name in ("alice", "bob")}
    config = {"users": {name: {"token_sha256": hashlib.sha256(token.encode()).hexdigest()}
                        for name, token in tokens.items()}}
    for path, data in ((auth, config), (clients, tokens)):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(data, output, indent=2)
    Accounts(auth)  # Validate before declaring setup complete.
    print("Created private accounts.auth.json and client-tokens.auth.json; tokens were not printed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
