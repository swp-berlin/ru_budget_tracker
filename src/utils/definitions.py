from typing import Literal
from re import Pattern, compile
from pydantic import BaseModel, ConfigDict, computed_field


# ---- Type literals ----

BudgetTypeLiteral = Literal["DRAFT", "LAW", "REPORT", "TOTAL"]
BudgetScopeLiteral = Literal["YEARLY", "QUARTERLY", "MONTHLY"]
DimensionTypeLiteral = Literal["MINISTRY", "CHAPTER", "SUBCHAPTER", "PROGRAM", "EXPENSE_TYPE"]
ViewByDimensionTypeLiteral = Literal["MINISTRY", "CHAPTER", "PROGRAM"]
LanguageTypeLiteral = Literal["EN", "RU"]
SpendingTypeLiteral = Literal["ALL", "MILITARY"]
PeriodTypeLiteral = Literal["ALL", "Q1", "Q2", "Q3", "Q4"]
UnitTypeLiteral = Literal[
    "ABSOLUTE",
    "DOLLARS",
    "PERCENT_GDP_FULL_YEAR",
    "PERCENT_GDP_YEAR_TO_DATE",
    "PERCENT_FULL_YEAR_SPENDING",
    "PERCENT_YEAR_TO_DATE_SPENDING",
    "PERCENT_YEAR_TO_DATE_REVENUE",
]


# ---- Budget constants ----


class BudgetConfig(BaseModel):
    """Immutable constants shared across the data model and ETL pipeline.

    Captures source-data quirks (LAW totals stored in thousands, 2018–2019 values
    doubled) as named multipliers so correction logic is centralised here rather
    than scattered across queries and transforms.
    """

    model_config = ConfigDict(frozen=True)

    # Hierarchy levels used throughout the data model
    hierarchy_objects: tuple[str, ...] = ("MINISTRY", "CHAPTER", "SUBCHAPTER", "PROGRAM")
    # Months that mark the end of a quarter, used for execution budget filtering
    quarterly_months: list[int] = [3, 6, 9, 12]
    # LAW budget totals are stored in thousands in the source data
    law_total_value_multiplier: int = 1000
    report_total_value_multiplier: int = 1
    # 2018 and 2019 LAW values are doubled in the source data
    law_18_19_value_multiplier: float = 0.5


# ---- Menu option groups ----


class ViewByConfig(BaseModel):
    """Options and reverse label map for the "view by" dimension selector.

    ``options`` drives the dropdown; ``map`` translates a dimension value back
    to its display label (e.g. ``"MINISTRY"`` → ``"Ministry"``).
    """

    model_config = ConfigDict(frozen=True)

    options: list[tuple[str, str]] = [
        ("View by ministry", "MINISTRY"),
        ("View by chapter", "CHAPTER"),
        ("View by program", "PROGRAM"),
    ]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def map(self) -> dict[str, str]:
        return {v: l for l, v in self.options}


class SpendingTypeConfig(BaseModel):
    """Options and label map for the spending-type filter (All / Military Only).

    ``map`` labels intentionally differ from the short dropdown labels in
    ``options`` — they are used as chart titles where more context is needed.
    """

    model_config = ConfigDict(frozen=True)

    options: list[tuple[str, str]] = [
        ("All", "ALL"),
        ("Military only", "MILITARY"),
    ]
    # Chart-title labels intentionally differ from the short dropdown labels in options.
    map: dict[str, str] = {"ALL": "All spending", "MILITARY": "Military only"}


class PeriodConfig(BaseModel):
    """Options and reverse label map for the period filter (All / Q1–Q4).

    Period values are cumulative — Q2 means Q1+Q2, Q3 means Q1+Q2+Q3, etc.
    ``map`` translates a period value back to its display label.
    """

    model_config = ConfigDict(frozen=True)

    options: list[tuple[str, str]] = [
        ("All periods", "ALL"),
        ("Q1", "Q1"),
        ("Q1-Q2", "Q2"),
        ("Q1-Q3", "Q3"),
        ("Q1-Q4", "Q4"),
    ]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def map(self) -> dict[str, str]:
        return {v: l for l, v in self.options}


class UnitConfig(BaseModel):
    """Options and suffix map for the unit selector.

    ``map`` values for ABSOLUTE and DOLLARS carry a leading space so they can
    be concatenated directly after a formatted number (e.g. ``"100.5"`` +
    ``" Billion RUB"``). Percentage suffixes have no leading space because they
    follow the number with a ``%`` character (e.g. ``"12.3% full-year GDP"``).
    """

    model_config = ConfigDict(frozen=True)

    options: list[tuple[str, UnitTypeLiteral]] = [
        ("billion RUB", "ABSOLUTE"),
        ("billion PPP Dollars", "DOLLARS"),
        ("% full-year GDP", "PERCENT_GDP_FULL_YEAR"),
        ("% year-to-date GDP", "PERCENT_GDP_YEAR_TO_DATE"),
        ("% full-year spending", "PERCENT_FULL_YEAR_SPENDING"),
        ("% year-to-date spending", "PERCENT_YEAR_TO_DATE_SPENDING"),
        ("% year-to-date revenue", "PERCENT_YEAR_TO_DATE_REVENUE"),
    ]
    # ABSOLUTE and DOLLARS carry a leading space for direct number concatenation:
    # "100.5" + " Billion RUB". Cannot be derived from options.
    map: dict[UnitTypeLiteral, str] = {
        "ABSOLUTE": " billion RUB",
        "DOLLARS": " billion PPP Dollars",
        "PERCENT_GDP_FULL_YEAR": "% full-year GDP",
        "PERCENT_GDP_YEAR_TO_DATE": "% year-to-date GDP",
        "PERCENT_FULL_YEAR_SPENDING": "% full-year spending",
        "PERCENT_YEAR_TO_DATE_SPENDING": "% year-to-date spending",
        "PERCENT_YEAR_TO_DATE_REVENUE": "% year-to-date revenue",
    }


# ---- Singleton instances ----

budget_config = BudgetConfig()
viewby_config = ViewByConfig()
spending_type_config = SpendingTypeConfig()
period_config = PeriodConfig()
unit_config = UnitConfig()


# ---- Military spending patterns ----


class _MilitarySpendingConfig(BaseModel):
    """Regex patterns used to identify military spending rows in the dataset.

    ``simple_patterns`` match any row where a single dimension (Chapter, Program,
    or Ministry) fits the pattern. ``combination_patterns`` require all dimensions
    in a dict to match simultaneously (AND logic). ``custom_patterns`` are used
    only for coloring in Military Only mode and must not be used in queries.
    Each pattern set has a ``_sql`` counterpart for use in raw SQL WHERE clauses.
    """

    model_config = ConfigDict(frozen=True)

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
    # This is only important for coloring, when in "Military Only" mode
    # Do not use in queries
    custom_patterns: dict[str, Pattern] = {
        "CHAPTER": compile(r"^10$"),
    }


MilitarySpending = _MilitarySpendingConfig()


# ---- Colors ----


class _ColorsConfig(BaseModel):
    """Named color constants and computed chapter color mapping for the treemap.

    ``filler_colors`` is a curated palette used for program nodes that have no
    fixed color assignment; colors are picked deterministically by CRC32 hash.
    ``color_mapping_chapters`` maps chapter orig_ids to their official colors.
    """

    model_config = ConfigDict(frozen=True)

    CLASSIFIED_GRAY: str = "#dddddd"
    CULTURE_PINK: str = "#ffafcc"
    ECONOMY_BLUE: str = "#80cbc4"
    EDUCATION_PURPLE: str = "#cdb4db"
    ENVIRONMENT_GREEN: str = "#81cf83"
    GENERAL_STATE_BLUE: str = "#93c5fd"
    HEALTHCARE_BLUE: str = "#8dd5e4"
    HOUSING_ORANGE: str = "#f7bb73"
    SERVICING_DEBT_YELLOW: str = "#ffd166"
    INTERBUDGETARY_TRANSFERS_ORANGE: str = "#e0c097"
    LAW_ENFORCEMENT_BLUE: str = "#b3c7ff"
    MASS_MEDIA_PURPLE: str = "#b3c7ff"
    MILITARY_GREEN: str = "#949d85"
    MINISTRY_GRAY: str = CLASSIFIED_GRAY
    ROOT_WHITE: str = "#ffffff"
    SOCIAL_RED: str = "#e46a6a"
    SPORT_GREEN: str = "#c6e48b"

    # Filler palette for nodes that don't match a CHAPTER or PROGRAM color mapping.
    filler_colors: list[str] = [
        "#B37C00",
        "#699470",
        "#669199",
        "#668FAD",
        "#B07A91",
        "#BF7873",
        "#CDAC62",
        "#9BB79B",
        "#99B5BA",
        "#99B5C7",
        "#C9A6B5",
        "#D4A39E",
        # "#E8D6B0",
        # "#D0DACD",
        # "#CCD9DB",
        # "#CCD9E3",
        # "#E3D1D9",
        # "#E6D1CF",
    ]

    # Color mapping for CHAPTERs based on the official color coding in the original dashboard.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def color_mapping_chapters(self) -> dict[str, str]:
        return {
            "01": self.GENERAL_STATE_BLUE,
            "02": self.MILITARY_GREEN,
            "03": self.LAW_ENFORCEMENT_BLUE,
            "04": self.ECONOMY_BLUE,
            "05": self.HOUSING_ORANGE,
            "06": self.ENVIRONMENT_GREEN,
            "07": self.EDUCATION_PURPLE,
            "08": self.CULTURE_PINK,
            "09": self.HEALTHCARE_BLUE,
            "10": self.SOCIAL_RED,
            "11": self.SPORT_GREEN,
            "12": self.MASS_MEDIA_PURPLE,
            "13": self.SERVICING_DEBT_YELLOW,
            "14": self.INTERBUDGETARY_TRANSFERS_ORANGE,
        }


Colors = _ColorsConfig()
