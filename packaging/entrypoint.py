"""Frozen executable entry point.

The packaged application runs the same command as an installed ``hanly``.
"""

from hanly_app.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
