"""Worker health entry point for workspace and container smoke checks."""

import json


def health() -> dict[str, str]:
    """Return bounded process metadata without contacting optional infrastructure."""
    return {"service": "worker", "status": "ok"}


def main() -> None:
    """Print the machine-readable worker health response."""
    print(json.dumps(health(), sort_keys=True))


if __name__ == "__main__":
    main()
