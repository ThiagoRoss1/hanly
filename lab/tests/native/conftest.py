"""Native cases for Lab-authored pages, outside the product package."""

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        item.add_marker("native")
