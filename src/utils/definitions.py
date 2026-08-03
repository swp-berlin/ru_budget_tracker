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

    All category colors come from the SWP corporate-design palette (six hues at
    three tints). ``filler_colors`` is that palette as a flat list, used for program
    nodes that have no fixed color assignment; they take slots by spending rank.
    ``color_mapping_chapters`` maps chapter orig_ids onto the same slots.
    """

    model_config = ConfigDict(frozen=True)

    # SWP corporate-design palette: six hues, three tints each.
    BRAND_GOLD_DARK: str = "#B37C00"
    BRAND_GOLD_MID: str = "#CDAC62"
    BRAND_GOLD_LIGHT: str = "#E8D6B0"
    BRAND_GREEN_DARK: str = "#699470"
    BRAND_GREEN_MID: str = "#9BB79B"
    BRAND_GREEN_LIGHT: str = "#D0DACD"
    BRAND_TEAL_DARK: str = "#669199"
    BRAND_TEAL_MID: str = "#99B5BA"
    BRAND_TEAL_LIGHT: str = "#CCD9DB"
    BRAND_BLUE_DARK: str = "#668FAD"
    BRAND_BLUE_MID: str = "#99B5C7"
    BRAND_BLUE_LIGHT: str = "#CCD9E3"
    BRAND_MAUVE_DARK: str = "#B07A91"
    BRAND_MAUVE_MID: str = "#C9A6B5"
    BRAND_MAUVE_LIGHT: str = "#E3D1D9"
    BRAND_SALMON_DARK: str = "#BF7873"
    BRAND_SALMON_MID: str = "#D4A39E"
    BRAND_SALMON_LIGHT: str = "#E6D1CF"

    # Grays are deliberately outside the brand palette: they mark nodes that carry no
    # category identity, so they must not collide with a chapter or program color.
    CLASSIFIED_GRAY: str = "#dddddd"
    MINISTRY_GRAY: str = CLASSIFIED_GRAY
    ROOT_WHITE: str = "#ffffff"
    # Root node in "Military only" mode; matches chapter 02 so the root reads as its total.
    MILITARY_GREEN: str = BRAND_GREEN_DARK

    # Label text. #444444 fails contrast on every dark tint (2.7-2.9:1); white clears
    # the WCAG large-text threshold there (3.4-3.6:1), so dark-filled tiles flip to it.
    TEXT_ON_LIGHT: str = "#444444"
    TEXT_ON_DARK: str = "#ffffff"

    # Filler palette for nodes that don't match a CHAPTER or PROGRAM color mapping.
    # Order is load-bearing: program colors index into this list by spending rank, so
    # reordering repaints every program node. Dark tints come first so the largest
    # programs get the most separable steps, as with the chapters below.
    filler_colors: list[str] = [
        BRAND_GOLD_DARK,
        BRAND_GREEN_DARK,
        BRAND_TEAL_DARK,
        BRAND_BLUE_DARK,
        BRAND_MAUVE_DARK,
        BRAND_SALMON_DARK,
        BRAND_GOLD_MID,
        BRAND_GREEN_MID,
        BRAND_TEAL_MID,
        BRAND_BLUE_MID,
        BRAND_MAUVE_MID,
        BRAND_SALMON_MID,
        BRAND_GOLD_LIGHT,
        BRAND_GREEN_LIGHT,
        BRAND_TEAL_LIGHT,
        BRAND_BLUE_LIGHT,
        BRAND_MAUVE_LIGHT,
        BRAND_SALMON_LIGHT,
    ]

    # Fills that need TEXT_ON_DARK label text — the six dark tints.
    dark_fills: frozenset[str] = frozenset(
        {
            BRAND_GOLD_DARK,
            BRAND_GREEN_DARK,
            BRAND_TEAL_DARK,
            BRAND_BLUE_DARK,
            BRAND_MAUVE_DARK,
            BRAND_SALMON_DARK,
        }
    )

    # Chapter colors, drawn from the SWP brand palette above.
    #
    # Slots are assigned by share of total spending, not by chapter number: the six
    # largest chapters (~77% of spending) take the six dark tints, which are the most
    # distinguishable steps the palette offers, and the smallest chapters take the
    # light tints. Fourteen categories exceed what any palette can separate by color
    # alone, so this ordering concentrates the unavoidable near-collisions on the
    # tiles too small to read anyway; the treemap's own labels carry identity.
    color_mapping_chapters: dict[str, str] = {
        "01": BRAND_BLUE_DARK,  # National Issues, 6.9%
        "02": BRAND_GREEN_DARK,  # National Defense, 11.5%
        "03": BRAND_MAUVE_DARK,  # Security and Law Enforcement, 9.0%
        "04": BRAND_TEAL_DARK,  # National Economy, 13.8%
        "05": BRAND_SALMON_MID,  # Housing and Public Utilities, 3.0%
        "06": BRAND_GREEN_MID,  # Environmental Protection, 1.7%
        "07": BRAND_MAUVE_MID,  # Education, 5.2%
        "08": BRAND_MAUVE_LIGHT,  # Culture, Cinema, 0.7%
        "09": BRAND_TEAL_MID,  # Health Care, 5.6%
        "10": BRAND_SALMON_DARK,  # Social Policy, 30.0%
        "11": BRAND_GREEN_LIGHT,  # Physical Education and Sports, 0.3%
        "12": BRAND_BLUE_MID,  # Mass Media, 0.5%
        "13": BRAND_GOLD_DARK,  # Servicing State and Municipal Debt, 6.1%
        "14": BRAND_GOLD_MID,  # Intergovernmental Transfers, 5.7%
    }


Colors = _ColorsConfig()
