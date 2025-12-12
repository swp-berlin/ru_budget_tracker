from typing import Literal
from re import Pattern, compile


HIERARCHY_OBJECTS = ("MINISTRY", "CHAPTER", "SUBCHAPTER", "PROGRAMM")

BudgetTypeLiteral = Literal["DRAFT", "LAW", "REPORT", "TOTAL"]
BudgetScopeLiteral = Literal["YEARLY", "QUARTERLY", "MONTHLY"]
DimensionTypeLiteral = Literal["MINISTRY", "CHAPTER", "SUBCHAPTER", "PROGRAMM", "EXPENSE_TYPE"]
ViewByDimensionTypeLiteral = Literal["MINISTRY", "CHAPTER", "PROGRAMM"]

LanguageTypeLiteral = Literal["EN", "ORIGINAL"]
SpendingTypeLiteral = Literal["ALL", "MILITARY"]
SpendingScopeLiteral = Literal[
    "ABSOLUTE",
    "PERCENT_GDP_FULL_YEAR",
    "PERCENT_GDP_YEAR_TO_YEAR",
    "PERCENT_FULL_YEAR_SPENDING",
    "PERCENT_YEAR_TO_YEAR_SPENDING",
    "PERCENT_YEAR_TO_YEAR_REVENUE",
]
# (Chapter = 02*) oder (Program = 31*)  oder (Ministry = 187) oder (Ministry = 180 und Chapter = 03*)
MilitarySpendingDictionary: dict[str, Pattern | list[dict[str, Pattern]]] = {
    "CHAPTER": compile(r"^02.*"),
    "PROGRAM": compile(r"^31.*"),
    "MINISTRY": compile(r"^187$"),
    "COMBINATION": [
        {
            "MINISTRY": compile(r"^180$"),
            "CHAPTER": compile(r"^03.*"),
        }
    ],
}
