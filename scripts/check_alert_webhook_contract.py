#!/usr/bin/env python3
"""Validate the packaged, default-disabled fixed alert transport manifest."""

from trading212_reference_data.alert_webhook import load_webhook_contract


def main() -> int:
    origins = load_webhook_contract()
    print(f"Alert webhook contract validated: {len(origins)} trusted origins.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
