"""ean-tools: generate and manage internal-use EAN-13 codes."""

from .core import EANError, build_ean13, check_digit, parse_ean13, validate_ean13

__version__ = "0.1.0"

__all__ = [
    "EANError",
    "__version__",
    "build_ean13",
    "check_digit",
    "parse_ean13",
    "validate_ean13",
]
