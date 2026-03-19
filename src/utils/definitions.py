from typing import Literal
from re import Pattern, compile


HIERARCHY_OBJECTS = ("MINISTRY", "CHAPTER", "SUBCHAPTER", "PROGRAMM")
# Quarterly months for execution budget filtering
QUARTERLY_MONTHS = [3, 6, 9, 12]

BudgetTypeLiteral = Literal["DRAFT", "LAW", "REPORT", "TOTAL"]
BudgetScopeLiteral = Literal["YEARLY", "QUARTERLY", "MONTHLY"]
DimensionTypeLiteral = Literal["MINISTRY", "CHAPTER", "SUBCHAPTER", "PROGRAMM", "EXPENSE_TYPE"]
ViewByDimensionTypeLiteral = Literal["MINISTRY", "CHAPTER", "PROGRAMM"]
# Menu option definitions to avoid duplication and keep layout concise
VIEWBY_OPTIONS: list[tuple[str, str]] = [
    ("Ministry", "MINISTRY"),
    ("Chapter", "CHAPTER"),
    ("Program", "PROGRAM"),
]

LanguageTypeLiteral = Literal["EN", "ORIGINAL"]
SpendingTypeLiteral = Literal["ALL", "MILITARY"]
# Menu option definitions to avoid duplication and keep layout concise
SPENDING_TYPE_OPTIONS: list[tuple[str, str]] = [
    ("All", "ALL"),
    ("Military Only", "MILITARY"),
]
PeriodLiteral = Literal["ALL", "Q1", "Q2", "Q3", "Q4"]
UnitLiteral = Literal[
    "ABSOLUTE",
    "DOLLARS",
    "PERCENT_GDP_FULL_YEAR",
    "PERCENT_GDP_YEAR_TO_DATE",
    "PERCENT_FULL_YEAR_SPENDING",
    "PERCENT_YEAR_TO_DATE_SPENDING",
    "PERCENT_YEAR_TO_DATE_REVENUE",
]


class MilitarySpending:
    """
    The MilitarySpending class defines the patterns
    used to identify military spending in the dataset.
    It includes both single-level patterns (e.g., any node with a Chapter ID of "02")
    and combination patterns (e.g., nodes that are classified as Ministry 180 AND Chapter 03).
    The patterns are defined using regular expressions
    and are used in the filtering logic to determine whether a given node
    in the hierarchy should be classified as military spending.
    """

    simple_patterns: dict[str, Pattern] = {
        "CHAPTER": compile(r"^02$"),
        "PROGRAM_0": compile(r"^31.*"),
        "PROGRAM_1": compile(r"^31.*"),
        "PROGRAM_2": compile(r"^31.*"),
        "PROGRAM_3": compile(r"^31.*"),
        "PROGRAM_4": compile(r"^31.*"),
        "MINISTRY": compile(r"^187$"),
    }

    simple_patterns_sql: dict[str, str] = {
        "CHAPTER": "^02$",
        "PROGRAM": "^31.*",
        "MINISTRY": "^187$",
    }
    combination_patterns: list[dict[str, Pattern]] = [
        {
            "MINISTRY": compile(r"^180$"),
            "CHAPTER": compile(r"^03$"),
        }
    ]
    combination_patterns_sql: list[dict[str, str]] = [
        {
            "MINISTRY": "^180$",
            "CHAPTER": "^03$",
        }
    ]

    custom_patterns: dict[str, Pattern] = {
        "CHAPTER": compile(r"^10$"),
    }


PERIOD_OPTIONS: list[tuple[str, str]] = [
    ("All Periods", "ALL"),
    ("Q1", "Q1"),
    ("Q1-Q2", "Q2"),
    ("Q1-Q3", "Q3"),
    ("Q1-Q4", "Q4"),
]

period_map = {
    "ALL": "All Periods",
    "Q1": "Q1",
    "Q2": "Q1-Q2",
    "Q3": "Q1-Q3",
    "Q4": "Q1-Q4",
}

UNIT_OPTIONS: list[tuple[str, UnitLiteral]] = [
    ("Billion RUB", "ABSOLUTE"),
    ("Billion PPP Dollars", "DOLLARS"),
    ("% full-year GDP", "PERCENT_GDP_FULL_YEAR"),
    ("% year-to-date GDP", "PERCENT_GDP_YEAR_TO_DATE"),
    ("% full-year spending", "PERCENT_FULL_YEAR_SPENDING"),
    ("% year-to-date spending", "PERCENT_YEAR_TO_DATE_SPENDING"),
    ("% year-to-date revenue", "PERCENT_YEAR_TO_DATE_REVENUE"),
]

unit_map: dict[UnitLiteral, str] = {
    "ABSOLUTE": " Billion RUB",
    "DOLLARS": " Billion PPP Dollars",
    "PERCENT_GDP_FULL_YEAR": "% full-year GDP",
    "PERCENT_GDP_YEAR_TO_DATE": "% year-to-date GDP",
    "PERCENT_FULL_YEAR_SPENDING": "% full-year spending",
    "PERCENT_YEAR_TO_DATE_SPENDING": "% year-to-date spending",
    "PERCENT_YEAR_TO_DATE_REVENUE": "% year-to-date revenue",
}

viewby_map = {
    "MINISTRY": "Ministry",
    "CHAPTER": "Chapter",
    "PROGRAM": "Program",
}
spending_type_map = {
    "ALL": "All Spending",
    "MILITARY": "Military Only",
}


class Colors:
    CLASSIFIED_GRAY = "#dddddd"
    CULTURE_PINK = "#ffafcc"
    ECONOMY_BLUE = "#80cbc4"
    EDUCATION_PURPLE = "#cdb4db"
    ENVIRONMENT_GREEN = "#81cf83"
    GENERAL_STATE_BLUE = "#93c5fd"
    HEALTHCARE_BLUE = "#8dd5e4"
    HOUSING_ORANGE = "#f7bb73"
    SERVICING_DEBT_YELLOW = "#ffd166"
    INTERBUDGETARY_TRANSFERS_ORANGE = "#e0c097"
    LAW_ENFORCEMENT_BLUE = "#b3c7ff"
    MASS_MEDIA_PURPLE = "b3c7ff"
    MILITARY_GREEN = "#949d85"
    MINISTRY_GRAY = "#aaaaaa"
    ROOT_WHITE = "#ffffff"
    SOCIAL_RED = "#e46a6a"
    SPORT_GREEN = "#c6e48b"

    # The color mappings CHAPTERs is based on the official color coding used in the original Dashboard.
    color_mapping_chapters = {
        "01": GENERAL_STATE_BLUE,
        "02": MILITARY_GREEN,
        "03": LAW_ENFORCEMENT_BLUE,
        "04": ECONOMY_BLUE,
        "05": HOUSING_ORANGE,
        "06": ENVIRONMENT_GREEN,
        "07": EDUCATION_PURPLE,
        "08": CULTURE_PINK,
        "09": HEALTHCARE_BLUE,
        "10": SOCIAL_RED,
        "11": SPORT_GREEN,
        "12": MASS_MEDIA_PURPLE,
        "13": SERVICING_DEBT_YELLOW,
        "14": INTERBUDGETARY_TRANSFERS_ORANGE,
    }

    # The color palette filler is used for any nodes that do not match
    # the CHAPTER or PROGRAM color mappings.
    color_mapping_filler = [
        "#93c5fd",
        "#fbc4ab",
        "#a3d9a5",
        "#ffd166",
        "#80cbc4",
        "#b3c7ff",
        "#f7c6c7",
        "#b5e2a4",
        "#e0c097",
        "#fefaff",
        "#cce5ff",
        "#ffd6a5",
        "#bfc9ad",
        "#aec9e9",
        "#cdb4db",
        "#a0e4f1",
        "#ec9d9d",
        "#c6e48b",
    ]
