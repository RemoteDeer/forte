"""Create local configuration without printing or committing the API key."""

import argparse
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--demo", action="store_true", help="Explicitly enable fake integration data"
    )
    args = parser.parse_args()
    target = ROOT / ".env"
    if target.exists():
        print(".env already exists; left unchanged. Edit FORTE_ANALYZER_MODE there if needed.")
        return
    content = (ROOT / ".env.example").read_text(encoding="utf-8")
    content = content.replace(
        "replace-with-a-random-key-at-least-16-characters", secrets.token_urlsafe(32)
    )
    if args.demo:
        content = content.replace("FORTE_ANALYZER_MODE=plugin", "FORTE_ANALYZER_MODE=demo")
    with target.open("x", encoding="utf-8") as output:
        target.chmod(0o600)
        output.write(content)
    print("Created .env with a random API key. Open it locally to copy the key.")
    if args.demo:
        print("DEMO enabled: artificial results only; do not submit this mode to the jury.")


if __name__ == "__main__":
    main()
