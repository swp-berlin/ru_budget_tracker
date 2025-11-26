from typing import Literal


HIERARCHY_OBJECTS = ("MINISTRY", "CHAPTER", "PROGRAMM")

LanguageTypeLiteral = Literal["EN", "ORIGINAL"]
SpendingTypeLiteral = Literal["ALL", "MILITARY"]
SpendingScopeLiteral = Literal[
    "ABSOLUT",
    "PERCENT_GDP_FULL_YEAR",
    "PERCENT_GDP_YEAR_TO_YEAR",
    "PERCENT_FULL_YEAR_SPENDING",
    "PERCENT_YEAR_TO_YEAR_SPENDING",
    "PERCENT_YEAR_TO_YEAR_REVENUE",
]
