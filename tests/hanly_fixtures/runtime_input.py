"""Invoke typed APIs with deliberately invalid values in runtime tests."""

from collections.abc import Callable


def invoke_with_runtime_values(
    callable_: Callable[..., object], *args: object, **kwargs: object
) -> object:
    """Cross a typed call boundary when a test checks runtime rejection."""

    return callable_(*args, **kwargs)
