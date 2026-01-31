from typing import Literal
from re import Pattern, compile


HIERARCHY_OBJECTS = ("MINISTRY", "CHAPTER", "SUBCHAPTER", "PROGRAMM")

BudgetTypeLiteral = Literal["DRAFT", "LAW", "REPORT", "TOTAL"]
BudgetScopeLiteral = Literal["YEARLY", "QUARTERLY", "MONTHLY"]
DimensionTypeLiteral = Literal["MINISTRY", "CHAPTER", "SUBCHAPTER", "PROGRAMM", "EXPENSE_TYPE"]
ViewByDimensionTypeLiteral = Literal["MINISTRY", "CHAPTER", "PROGRAMM"]

LanguageTypeLiteral = Literal["EN", "ORIGINAL"]
SpendingTypeLiteral = Literal["ALL", "MILITARY"]
UnitLiteral = Literal[
    "ABSOLUTE",
    "DOLLARS",
    "PERCENT_GDP_FULL_YEAR",
    "PERCENT_GDP_YEAR_TO_DATE",
    "PERCENT_FULL_YEAR_SPENDING",
    "PERCENT_YEAR_TO_DATE_SPENDING",
    "PERCENT_YEAR_TO_DATE_REVENUE",
]
# (Chapter = 02*) oder (Program = 31*)  oder (Ministry = 187) oder (Ministry = 180 und Chapter = 03*)
MilitarySpendingDictionary: dict[str, Pattern | list[dict[str, Pattern]]] = {
    "CHAPTER": compile(r"^02.*"),
    "PROGRAM_0": compile(r"^31.*"),
    "PROGRAM_1": compile(r"^31.*"),
    "PROGRAM_2": compile(r"^31.*"),
    "PROGRAM_3": compile(r"^31.*"),
    "MINISTRY": compile(r"^187$"),
    "COMBINATION": [
        {
            "MINISTRY": compile(r"^180$"),
            "CHAPTER": compile(r"^03.*"),
        }
    ],
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
