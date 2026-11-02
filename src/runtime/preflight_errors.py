"""Distinguish a safe retry from an operation with uncertain cleanup."""

class PreflightUnsafe(RuntimeError):
    """Do not retry until the uncertain resource has been reconciled."""
