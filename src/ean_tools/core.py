"""EAN-13 logic: check digit, code construction, validation and bar encoding.

Internal code layout (12 digits + check digit)::

    PPP  CC  NNN  VVVV  D
     |    |   |    |    +-- check digit (computed)
     |    |   |    +------- variant (size, colour...), 0000 = no variant
     |    |   +------------ product code within its category
     |    +---------------- category
     +--------------------- internal prefix (200-299, GS1 restricted circulation)

This module has no third-party dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_PREFIX = "200"
NO_VARIANT = "0000"

PREFIX_LEN = 3
CATEGORY_LEN = 2
PRODUCT_LEN = 3
VARIANT_LEN = 4


class EANError(ValueError):
    """Invalid input for building or validating an EAN-13."""


def _require_digits(value: str, length: int, field: str) -> str:
    if not isinstance(value, str) or len(value) != length or not value.isdigit():
        raise EANError(
            f"{field}: se esperaban {length} dígitos numéricos, recibido {value!r}"
        )
    return value


def check_digit(first_12: str) -> str:
    """Return the EAN-13 check digit for the first 12 digits.

    Weights 1, 3, 1, 3... are applied from the left (GS1 mod-10 algorithm).
    """
    _require_digits(first_12, 12, "Base EAN")
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(first_12))
    return str((10 - total % 10) % 10)


def validate_prefix(prefix: str) -> str:
    """Accept only 3-digit prefixes in the GS1 internal range 200-299."""
    _require_digits(prefix, PREFIX_LEN, "Prefijo")
    if not prefix.startswith("2"):
        raise EANError(
            f"Prefijo {prefix!r} fuera del rango interno GS1 (200-299)"
        )
    return prefix


def build_ean13(
    category: str,
    product: str,
    variant: str = NO_VARIANT,
    prefix: str = DEFAULT_PREFIX,
) -> str:
    """Build a full EAN-13 from its parts. Every part must have its exact length."""
    validate_prefix(prefix)
    _require_digits(category, CATEGORY_LEN, "Categoría")
    _require_digits(product, PRODUCT_LEN, "Producto")
    _require_digits(variant, VARIANT_LEN, "Variante")
    base = prefix + category + product + variant
    return base + check_digit(base)


@dataclass(frozen=True)
class ValidationResult:
    code: str
    valid: bool
    reason: str = ""
    internal: bool = False

    def __bool__(self) -> bool:
        return self.valid


def validate_ean13(code: str) -> ValidationResult:
    """Check length, digits and check digit. Also flags internal-range codes."""
    code = code.strip()
    if len(code) != 13:
        return ValidationResult(code, False, f"longitud {len(code)}, se esperaban 13")
    if not code.isdigit():
        return ValidationResult(code, False, "contiene caracteres no numéricos")
    expected = check_digit(code[:12])
    if code[12] != expected:
        return ValidationResult(
            code, False, f"dígito de control {code[12]}, debería ser {expected}"
        )
    return ValidationResult(code, True, internal=code[0] == "2")


@dataclass(frozen=True)
class ParsedCode:
    prefix: str
    category: str
    product: str
    variant: str
    check: str


def parse_ean13(code: str) -> ParsedCode:
    """Split a valid EAN-13 into the internal layout parts."""
    result = validate_ean13(code)
    if not result:
        raise EANError(f"EAN-13 no válido ({result.reason}): {code!r}")
    c = result.code
    return ParsedCode(c[0:3], c[3:5], c[5:8], c[8:12], c[12])


# --- Bar encoding -----------------------------------------------------------
# Standard EAN-13 symbology tables (ISO/IEC 15420).

_L = ["0001101", "0011001", "0010011", "0111101", "0100011",
      "0110001", "0101111", "0111011", "0110111", "0001011"]
_G = ["0100111", "0110011", "0011011", "0100001", "0011101",
      "0111001", "0000101", "0010001", "0001001", "0010111"]
_R = ["1110010", "1100110", "1101100", "1000010", "1011100",
      "1001110", "1010000", "1000100", "1001000", "1110100"]
# Parity of the left half, selected by the first digit.
_PARITY = ["LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG",
           "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL"]

START = END = "101"
MIDDLE = "01010"
MODULES = 95  # 3 + 6*7 + 5 + 6*7 + 3


def encode_modules(code: str) -> str:
    """Return the 95-module bar pattern ('1' = bar, '0' = space)."""
    result = validate_ean13(code)
    if not result:
        raise EANError(f"EAN-13 no válido ({result.reason}): {code!r}")
    digits = [int(d) for d in result.code]
    parity = _PARITY[digits[0]]
    left = "".join(
        (_L if p == "L" else _G)[d] for p, d in zip(parity, digits[1:7])
    )
    right = "".join(_R[d] for d in digits[7:])
    return START + left + MIDDLE + right + END


def guard_modules() -> set[int]:
    """Indices (0..94) of the guard bars, drawn longer than data bars."""
    start = range(0, 3)
    middle = range(3 + 42, 3 + 42 + 5)
    end = range(MODULES - 3, MODULES)
    return {*start, *middle, *end}
