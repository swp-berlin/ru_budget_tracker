"""Unit tests for scripts.rename_dimensions.

Pure functions, synthetic names, no data files or DB.
"""

import pytest

from scripts.rename_dimensions import (
    normalize_name,
    normalize_quotes,
    normalize_translated_name,
    shorten_federation,
    strip_program_prefix,
    strip_trailing_federation,
    strip_type_label,
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
# strip_trailing_federation
# =============================================================================


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Космическая деятельность РФ", "Космическая деятельность"),
        ("Space Activities of the RF", "Space Activities"),
        ("Space Activities OF THE RF", "Space Activities"),
    ],
)
def test_strip_trailing_federation(value: str, expected: str) -> None:
    assert strip_trailing_federation(value) == expected


def test_strip_trailing_federation_keeps_non_trailing_occurrence() -> None:
    value = "Ministry of Justice of the RF Central Office"
    assert strip_trailing_federation(value) == value


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
        == "Космическая деятельность"
    )


def test_normalize_name_non_program_keeps_prefix() -> None:
    name = 'Государственная программа Российской Федерации "Юстиция"'
    assert normalize_name(name, is_program=False) == 'Государственная программа РФ "Юстиция"'


# =============================================================================
# normalize_quotes
# =============================================================================


def test_normalize_quotes_curly_doubles() -> None:
    assert normalize_quotes("A set of procedural measures titled “Safe Work”") == (
        'A set of procedural measures titled "Safe Work"'
    )


def test_normalize_quotes_curly_singles() -> None:
    assert normalize_quotes("‘Polyus’ Research Institute") == "'Polyus' Research Institute"


def test_normalize_quotes_trailing_comma_before_closing_quote() -> None:
    # DeepL put the comma inside the closing quote: '...legal information,”'
    assert normalize_quotes("Main Activity: “Access to legal information,”") == (
        'Main Activity: "Access to legal information"'
    )


def test_normalize_quotes_keeps_inner_comma_quote() -> None:
    # Only the very end of the string is an artifact; mid-string is real text.
    value = '"Energia," Korolev, Moscow Region'
    assert normalize_quotes(value) == value


def test_normalize_quotes_is_idempotent() -> None:
    once = normalize_quotes("Main Activity: “Access to legal information,”")
    assert normalize_quotes(once) == once


def test_normalize_quotes_none() -> None:
    assert normalize_quotes(None) is None


# =============================================================================
# strip_type_label - one real example per Russian type-prefix family
# =============================================================================


# (russian prefix, english rendering as DeepL produced it, expected title)
TYPE_LABEL_CASES = [
    (
        "Государственная программа Российской Федерации",
        'State Program of the RF: "Implementation of State National Policy"',
        "Implementation of State National Policy",
    ),
    (
        "Комплекс процессных мероприятий",
        'A set of procedural measures titled "Organization and Enforcement of Court Orders"',
        "Organization and Enforcement of Court Orders",
    ),
    (
        "Комплекс процессных мероприятий",
        'Set of Process Activities: "Official Statistics"',
        "Official Statistics",
    ),
    (
        "Комплекс процессных мероприятий",
        'A Set of Operational Measures for "Fire Safety"',
        "Fire Safety",
    ),
    (
        "Комплекс процессных мероприятий",
        '"Quality of Education" Set of Process Measures',
        "Quality of Education",
    ),
    ("Подпрограмма", 'Subprogram: "Institutional Development"', "Institutional Development"),
    ("Подпрограмма", '"Workplace Safety" Subprogram', "Workplace Safety"),
    ("Подпрограмма", '"Clean Country" Priority Project Subprogram', "Clean Country"),
    ("Основное мероприятие", 'Main Event: "Support for Cinema"', "Support for Cinema"),
    ("Основное мероприятие", 'Key Initiative: "Water Resources"', "Water Resources"),
    (
        "Основное мероприятие",
        'The main initiative, "Support for Rural Settlements"',
        "Support for Rural Settlements",
    ),
    ("Федеральный проект", 'Federal Project "Autonomous Navigation"', "Autonomous Navigation"),
    ("Федеральный проект", 'The "Road Safety" Federal Project', "Road Safety"),
    ("Национальный проект", 'The "Youth and Children" National Project', "Youth and Children"),
    (
        "Приоритетный проект",
        'Priority Project: "Export of Agricultural Products"',
        "Export of Agricultural Products",
    ),
    ("Ведомственный проект", 'Departmental Project: "Digital Justice"', "Digital Justice"),
    ("Ведомственный проект", 'Ministry-led project: "Digital Agriculture"', "Digital Agriculture"),
    (
        "Ведомственная целевая программа",
        'The "Russian E-School" Departmental Targeted Program',
        "Russian E-School",
    ),
    (
        "Федеральная целевая программа",
        'Federal Target Program "Development of Physical Culture"',
        "Development of Physical Culture",
    ),
]


@pytest.mark.parametrize(("russian_prefix", "english", "expected"), TYPE_LABEL_CASES)
def test_strip_type_label(russian_prefix: str, english: str, expected: str) -> None:
    assert strip_type_label(english) == expected


@pytest.mark.parametrize(("russian_prefix", "english", "expected"), TYPE_LABEL_CASES)
def test_strip_type_label_is_idempotent(russian_prefix: str, english: str, expected: str) -> None:
    assert strip_type_label(expected) == expected


def test_strip_type_label_without_quotes_around_title() -> None:
    assert strip_type_label("Main Activity: Ensuring the Rights of Individuals") == (
        "Ensuring the Rights of Individuals"
    )


def test_strip_type_label_nested_labels() -> None:
    assert strip_type_label('Main Event: "Priority Project: Small Business"') == "Small Business"


def test_strip_type_label_keeps_trailing_text() -> None:
    assert (
        strip_type_label('Subprogram: "Justice" (classified part)') == "Justice (classified part)"
    )


def test_strip_type_label_apostrophe_in_title() -> None:
    assert strip_type_label('Federal Project "Russia\'s Space Activities"') == (
        "Russia's Space Activities"
    )


def test_strip_type_label_leaves_unquoted_title() -> None:
    # A real title that merely starts with label words - there is no quoted title
    # and no colon, so nothing may be stripped.
    name = "Federal Target Program for the Development of the Kaliningrad Region through 2020"
    assert strip_type_label(name) == name


def test_strip_type_label_leaves_trailing_label_in_running_text() -> None:
    name = "Ensuring the Implementation of the Subprogram"
    assert strip_type_label(name) == name


def test_strip_type_label_none() -> None:
    assert strip_type_label(None) is None


# =============================================================================
# normalize_translated_name
# =============================================================================


def test_normalize_translated_name_program_full_pipeline() -> None:
    # Curly quotes are folded first, so the back-referenced quote pair matches.
    assert (
        normalize_translated_name(
            'Federal Project "Space Activities of the Russian Federation”', is_program=True
        )
        == "Space Activities"
    )


def test_normalize_translated_name_non_program_only_normalizes() -> None:
    assert (
        normalize_translated_name(
            "Ministry of Justice of the Russian Federation “Central Office”", is_program=False
        )
        == 'Ministry of Justice of the RF "Central Office"'
    )


@pytest.mark.parametrize(("russian_prefix", "english", "expected"), TYPE_LABEL_CASES)
def test_normalize_translated_name_is_idempotent(
    russian_prefix: str, english: str, expected: str
) -> None:
    once = normalize_translated_name(english, is_program=True)
    assert normalize_translated_name(once, is_program=True) == once
