"""Module entrypoint so `python -m recording_automation` works."""
from __future__ import annotations

from .cli import app


def main() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
