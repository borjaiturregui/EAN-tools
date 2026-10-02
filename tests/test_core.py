import random

import pytest

from ean_tools.core import (
    MODULES,
    EANError,
    build_ean13,
    check_digit,
    encode_modules,
    guard_modules,
    parse_ean13,
    validate_ean13,
)

# Real codes produced by the original internal script (legacy regression).
LEGACY = [
    ("01", "001", "0000", "2000100100004"),
    ("01", "004", "0023", "2000100400234"),
    ("01", "004", "0024", "2000100400241"),
    ("07", "001", "0000", "2000700100008"),
    ("07", "002", "0004", "2000700200043"),
    ("08", "001", "0005", "2000800100052"),
]


@pytest.mark.parametrize(
    "first_12, expected",
    [
        ("400638133393", "1"),  # well-known retail EAN 4006381333931
        ("590123412345", "7"),  # GS1 example 5901234123457
        ("978020137962", "4"),  # ISBN 9780201379624
        ("000000000000", "0"),
    ],
)
def test_check_digit_known_values(first_12, expected):
    assert check_digit(first_12) == expected


@pytest.mark.parametrize("bad", ["", "12345678901", "1234567890123", "12345678901a", " 12345678901"])
def test_check_digit_rejects_bad_input(bad):
    with pytest.raises(EANError):
        check_digit(bad)


@pytest.mark.parametrize("cat, prod, var, expected", LEGACY)
def test_build_matches_legacy_script(cat, prod, var, expected):
    assert build_ean13(cat, prod, var) == expected


def test_build_default_no_variant():
    assert build_ean13("01", "001") == "2000100100004"


def test_build_custom_internal_prefix():
    code = build_ean13("01", "001", prefix="250")
    assert code.startswith("250") and validate_ean13(code)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"category": "1", "product": "001"},  # parts are not padded here
        {"category": "01", "product": "01"},
        {"category": "01", "product": "001", "variant": "T001"},
        {"category": "01", "product": "001", "variant": "00001"},
        {"category": "01", "product": "001", "prefix": "840"},  # assigned GS1 prefix
        {"category": "01", "product": "001", "prefix": "20"},
    ],
)
def test_build_rejects_bad_parts(kwargs):
    with pytest.raises(EANError):
        build_ean13(**kwargs)


def test_validate():
    assert validate_ean13("2000100100004").internal
    assert validate_ean13(" 2000100100004\n").valid
    assert not validate_ean13("4006381333931").internal
    bad = validate_ean13("2000100100005")
    assert not bad and "debería ser 4" in bad.reason
    assert "longitud" in validate_ean13("123").reason
    assert "no numéricos" in validate_ean13("20001001000O4").reason


def test_parse_roundtrip():
    parts = parse_ean13("2000100400234")
    assert (parts.prefix, parts.category, parts.product, parts.variant, parts.check) == (
        "200", "01", "004", "0023", "4"
    )
    with pytest.raises(EANError):
        parse_ean13("2000100400235")


def test_any_single_digit_error_is_detected():
    code = "2000100400234"
    for pos in range(13):
        for d in "0123456789":
            if d != code[pos]:
                assert not validate_ean13(code[:pos] + d + code[pos + 1:])


def test_encode_structure():
    pattern = encode_modules("4006381333931")
    assert len(pattern) == MODULES
    assert pattern.startswith("101") and pattern.endswith("101")
    assert pattern[45:50] == "01010"
    assert {i for i in guard_modules()} == {0, 1, 2, 45, 46, 47, 48, 49, 92, 93, 94}


def test_encode_matches_python_barcode():
    barcode = pytest.importorskip("barcode")
    ean_cls = barcode.get_barcode_class("ean13")
    rng = random.Random(42)
    for _ in range(500):
        base = "".join(rng.choice("0123456789") for _ in range(12))
        full = base + check_digit(base)
        assert ean_cls(base).build()[0] == encode_modules(full), full
