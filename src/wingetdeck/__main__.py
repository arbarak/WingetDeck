"""Entry point for `python -m wingetdeck` and for the portable exe."""

from wingetdeck.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
