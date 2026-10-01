from importlib.metadata import PackageNotFoundError, version

__all__ = ["__version__"]

# Read from the installed distribution metadata so this cannot drift out of step
# with pyproject.toml the way a hardcoded literal did.
try:
    __version__ = version("codex-stats")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0.dev0"
