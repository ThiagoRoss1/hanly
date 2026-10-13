"""Internal frozen entry point for the Tauri-supervised Python service."""

from __future__ import annotations

import multiprocessing


def run() -> int:
    """Enter the bounded JSONL service after frozen child setup."""

    multiprocessing.freeze_support()
    from hanly_app.service.server import main

    return main()


if __name__ == "__main__":
    raise SystemExit(run())
