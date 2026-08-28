"""``python -m hanly_app`` — the same command as ``hanly``."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
