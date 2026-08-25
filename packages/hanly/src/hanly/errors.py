"""Generic errors shared by the Hanly engine contracts and providers."""


class HanlyError(Exception):
    """Base exception for expected Hanly engine failures."""


class ProviderError(HanlyError):
    """Failure raised by a provider implementation."""


class LookupCancelled(HanlyError):
    """A lookup superseded between provider stages."""
