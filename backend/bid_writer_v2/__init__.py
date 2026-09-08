"""Bid Writer v2: modular knowledge engineering and bid production."""

def create_app(*args, **kwargs):
    """Create the server explicitly; importing library modules must not open a database."""
    from .app import create_app as factory

    return factory(*args, **kwargs)

__all__ = ["create_app"]
