"""Unit tests for scripts.rename_dimensions.

Pure functions, synthetic names, no data files or DB.
"""

from scripts.rename_dimensions import (
    normalize_name,
    shorten_federation,
    strip_program_prefix,
)


# =============================================================================
# strip_program_prefix
# =============================================================================


def test_strip_prefix_ru() -> None:
    assert (
        strip_program_prefix('Государственная программа Российской Федерации "Юстиция"')
        == "Юстиция"
    )


def test_strip_prefix_ru_keeps_trailing_text() -> None:
    assert (
        strip_program_prefix(
            'Государственная программа Российской Федерации "Юстиция" (закрытая часть)'
        )
        == "Юстиция (закрытая часть)"
    )


def test_strip_prefix_en() -> None:
    assert strip_program_prefix('State Program of the Russian Federation "Justice"') == "Justice"


def test_strip_prefix_en_apostrophe_in_title() -> None:
    # The closing quote must match the opening one: an apostrophe inside the
    # title used to close the match early, eating the apostrophe and leaving the
    # real closing quote dangling ('Russias Space Activities"').
    assert (
        strip_program_prefix('State Program of the Russian Federation "Russia\'s Space Activities"')
        == "Russia's Space Activities"
    )


def test_strip_prefix_single_quoted_title() -> None:
    assert (
        strip_program_prefix("State Program of the Russian Federation 'Justice' phase two")
        == "Justice phase two"
    )


def test_strip_prefix_no_match_is_unchanged() -> None:
    name = 'Подпрограмма "Развитие транспортной системы"'
    assert strip_program_prefix(name) == name


def test_strip_prefix_is_idempotent() -> None:
    once = strip_program_prefix(
        'State Program of the Russian Federation "Russia\'s Space Activities"'
    )
    assert strip_program_prefix(once) == once


def test_strip_prefix_none() -> None:
    assert strip_program_prefix(None) is None


# =============================================================================
# shorten_federation
# =============================================================================


def test_shorten_federation_ru_declensions() -> None:
    assert (
        shorten_federation("Министерство юстиции Российской Федерации") == "Министерство юстиции РФ"
    )


def test_shorten_federation_en() -> None:
    assert shorten_federation("Government of the Russian Federation") == "Government of the RF"


# =============================================================================
# normalize_name
# =============================================================================


def test_normalize_name_program_strips_then_shortens() -> None:
    assert (
        normalize_name(
            'Государственная программа Российской Федерации "Космическая деятельность '
            'Российской Федерации"',
            is_program=True,
        )
        == "Космическая деятельность РФ"
    )


def test_normalize_name_non_program_keeps_prefix() -> None:
    name = 'Государственная программа Российской Федерации "Юстиция"'
    assert normalize_name(name, is_program=False) == 'Государственная программа РФ "Юстиция"'
