"""About page for the Russian budget tracker."""

from dash import html, register_page

# Register this page with Dash
register_page(__name__, path="/about")

# Define the layout of the about page using Dash HTML components
layout = html.Div(
    [
        # Header section
        html.Header(
            [
                # Logo image without button styling - only the image is visible
                html.A(
                    [
                        html.Img(
                            src="/assets/logo/logo.svg",
                            style={"height": "2em"},
                            alt="Logo of Stiftung Wissenschaft und Politik",
                        ),
                    ],
                    style={"margin-right": "20px", "align-self": "center"},
                    href="/",
                    title="Go to Home Page",
                ),
                html.Div(className="spacer"),
                html.H1("About this project"),
            ]
        ),
        # Main content section
        html.Main(
            [
                # "What you are looking at" section
                html.H2("What you are looking at"),
                html.P(
                    [
                        "This site visualizes Russia’s federal budget (law and execution) as an "
                        "interactive treemap and time-series charts. It is meant to make Russia's "
                        "budget more transparent for the public by enabling data-driven research "
                        "and journalism. It was created by ",
                        html.A(
                            "Janis Kluge",
                            href="https://www.swp-berlin.org/en/researcher/janis-kluge/",
                        ),
                        ", a researcher at the German Institute for International and Security "
                        "Affairs (SWP).",
                    ]
                ),
                # "Data & methodology" section
                html.H2("Data & methodology"),
                html.Ul(
                    [
                        # Change log list item
                        html.Li(
                            [
                                html.Strong("Change log:"),
                                html.P(
                                    "29.9.2025: Uploaded 2026 data. Until the final budget is out, the "
                                    "draft budget will be categorized as a budget law to enable "
                                    "comparisons to previous years."
                                ),
                                html.P(
                                    "29.9.2025: Updated 2025 GDP to match latest MER estimate (217290 "
                                    "billion RUB)"
                                ),
                            ]
                        ),
                        # Sources list item
                        html.Li(
                            [
                                html.Strong("Sources:"),
                                " All data is based on official Russian budget and statistical "
                                "information. You can double-check all data using the original "
                                "sources (you may need a VPN to access them):",
                                html.Ul(
                                    [
                                        html.Li(
                                            [
                                                "Quarterly budget execution reports published by Russia's Treasury "
                                                "(Roskazna): ",
                                                html.A(
                                                    "Link to source",
                                                    href="https://roskazna.gov.ru/ispolnenie-byudzhetov/federalnyj-byudzhet/",
                                                ),
                                            ]
                                        ),
                                        html.Li(
                                            [
                                                "Russian budget laws, amendments and their budget listings (usually "
                                                "attachment 12, 15, 17): ",
                                                html.A(
                                                    "Link to source",
                                                    href="https://budget.gov.ru/%D0%91%D1%8E%D0%B4%D0%B6%D0%B5%D1%82/%D0%97%D0%B0%D0%BA%D0%BE%D0%BD-%D0%BE-%D0%B1%D1%8E%D0%B4%D0%B6%D0%B5%D1%82%D0%B5",
                                                ),
                                            ]
                                        ),
                                        html.Li(
                                            [
                                                "Budget allocation at the chapter level for budget/draft budget "
                                                'laws in the "Budget For Citizens": ',
                                                html.A(
                                                    "Link to source",
                                                    href="https://budget.gov.ru/%D0%91%D1%8E%D0%B4%D0%B6%D0%B5%D1%82/%D0%97%D0%B0%D0%BA%D0%BE%D0%BD-%D0%BE-%D0%B1%D1%8E%D0%B4%D0%B6%D0%B5%D1%82%D0%B5/%D0%91%D1%8E%D0%B4%D0%B6%D0%B5%D1%82-%D0%B4%D0%BB%D1%8F-%D0%B3%D1%80%D0%B0%D0%B6%D0%B4%D0%B0%D0%BD",
                                                ),
                                            ]
                                        ),
                                        html.Li(
                                            [
                                                "Russian total budget execution published monthly by the Finance "
                                                "Mininstry: ",
                                                html.A(
                                                    "Link to source",
                                                    href="https://minfin.gov.ru/ru/document?id_4=80042-kratkaya_ezhemesyachnaya_informatsiya_ob_ispolnenii_federalnogo_byudzheta_mlrd._rub._nakopleno_s_nachala_goda",
                                                ),
                                            ]
                                        ),
                                        html.Li(
                                            [
                                                "Quarterly nominal GDP published by Rosstat: ",
                                                html.A(
                                                    "Link to source",
                                                    href="https://rosstat.gov.ru/storage/mediabank/VVP_kvartal_s1995-2025.xlsx",
                                                ),
                                            ]
                                        ),
                                        html.Li(
                                            [
                                                "PPP Dollar by the OECD PPP Programme, published by World Bank "
                                                "(current year uses PPP rate of last year): ",
                                                html.A(
                                                    "Link to source",
                                                    href="https://data.worldbank.org/indicator/PA.NUS.PPP?locations=RU",
                                                ),
                                            ]
                                        ),
                                    ]
                                ),
                            ]
                        ),
                        # Classified spending list item
                        html.Li(
                            [
                                html.P(
                                    [
                                        html.Strong("Classified spending:"),
                                        " An increasing share of Russia's federal budget is classified, "
                                        "meaning that no detailed budget listings are published. However, the "
                                        "size of the classified share can be calculated by subtracting public "
                                        "spending from total spending, which is still published on a monthly "
                                        "basis. In addition, Russia published total spending for different "
                                        'budget chapters in its "Budget For Citizens", making it possible to '
                                        "calculate classified spending for each chapter for the budget year",
                                    ]
                                )
                            ]
                        ),
                        # Estimated classified spending list item
                        html.Li(
                            [
                                html.P(
                                    [
                                        html.Strong("Estimated classified spending:"),
                                        " While the total amount of classified spending is known on a quarterly "
                                        "basis, it is not clear how this spending is allocated to budget "
                                        "chapters. For some calculations in the project, classified spending on "
                                        "a chapter level is estimated. To estimate classified spending, the "
                                        "share of a chapter's classified spending in total classified spending "
                                        "of the corresponding budget year is calculated. Quarterly classified "
                                        "spending is then multiplied by this share. This is particularly "
                                        "relevant for calculating military spending, which includes the "
                                        "classified spending portions of the National Defense and Social "
                                        "Spending (compensation for KIA/WIA) chapters. Note that the estimate "
                                        "for classified military spending are likely to underestimate the "
                                        "true amount: Classified spending has always been higher than planned "
                                        "in the federal budget since 2022. The increase was most likely "
                                        "exclusively due to the war, but the methodology of this project "
                                        "allocates overruns of classified spending according to the "
                                        "distribution in budget laws, meaning that only a share of the "
                                        "overruns is added to classified military spending.",
                                    ]
                                )
                            ]
                        ),
                        # Military spending list item
                        html.Li(
                            [
                                html.P(
                                    [
                                        html.Strong("Military spending:"),
                                        ' What counts as "military spending" is always a question of '
                                        'definitions. It is not identical to "National Defense" in the '
                                        "federal budget, because there is also military spending in Social "
                                        "Spending (compensation for soldiers, soldier's pensions etc.), "
                                        "National Security (the National Guard) etc. In this project, the "
                                        "most widely used definition by SIPRI was appproximated. Most of "
                                        "military spending consists of National Defense plus whatever from "
                                        "the other chapters is controlled by the Ministry of Defense. The "
                                        "applicaiton of SIPRI's definition to the Russian budget for "
                                        "official SIPRI data is done by Julian Cooper, who also publishes "
                                        "excellent annual articles about Russian military spending (e.g. on "
                                        "the ",
                                        html.A(
                                            "2025 budget",
                                            href="https://www.sipri.org/publications/2025/sipri-insights-peace-and-security/preparing-fourth-year-war-military-spending-russias-budget-2025",
                                        ),
                                        ") in which the components of military spending are listed. This "
                                        "project uses the components listed by Julian Cooper, except for the "
                                        "parts of military spending that are estimates based on previous "
                                        "years. Cooper's results for Russian military spending should thus be "
                                        "higher than the estimates in this project.",
                                    ]
                                )
                            ]
                        ),
                    ]
                ),
                # "Limitations and notes" section
                html.H2("Limitations and notes"),
                html.Ul(
                    [
                        # Precision list item
                        html.Li(
                            [
                                html.Strong("Precision:"),
                                " The data is not always precise on a 1-ruble level for the following reasons:",
                                html.Ul(
                                    [
                                        html.Li(
                                            html.P(
                                                "Inconsistencies in Financy Ministry data: Russia publishes three "
                                                "different listings on budget laws and execution. These listings "
                                                "(big Excel files) are often not 100% identical. In some cases, "
                                                "there seem to be typos (zero missing etc.). However, this does "
                                                "not change the data dramatically (less than a billion rubles "
                                                "discrepancy)."
                                            )
                                        ),
                                        html.Li(
                                            html.P(
                                                "Negative budget execution: In some years, there are cases of "
                                                "negative execution in some budget lines of some execution "
                                                "reports. The amounts are rather small (less than a billion "
                                                "rubles) and temporary. It usually happens early in the year and "
                                                "is probably related to spending to returned expenditure of the "
                                                "previous year. Because the Treemap cannot visualize negative "
                                                "elements, they are ignored, possibly leading to slightly "
                                                "different totals in the Treemap."
                                            )
                                        ),
                                        html.Li(
                                            html.P(
                                                "Total spending on the chapter level: For a lack of better "
                                                "alternatives, this project uses the total spending from Russia's "
                                                '"Budget For Citizens". The BfC publishes total spending per '
                                                "chapter in 100 million rubles resolution. The sum of the "
                                                "chapters sometimes doesn't match the total spending for the "
                                                "year. There appear to be some inconsistencies or rounding "
                                                "errors. The total of these errors does not exceed 20 billion "
                                                "rubles."
                                            )
                                        ),
                                    ]
                                ),
                            ]
                        ),
                        # Data updates list item
                        html.Li(
                            html.P(
                                [
                                    html.Strong("Data updates:"),
                                    " There are regular updates to past budget execution which could lead to "
                                    "changing spending totals.",
                                ]
                            )
                        ),
                        # GDP estimates list item
                        html.Li(
                            html.P(
                                [
                                    html.Strong("GDP estimates:"),
                                    " Total GDP for the current year is not known for certain. To offer "
                                    "annual GDP as a unit of comparison, the project relies on the ",
                                    html.A(
                                        "official forecast",
                                        href="https://economy.gov.ru/material/directions/makroec/prognozy_socialno_ekonomicheskogo_razvitiya/",
                                    ),
                                    " that is prepared by Russia's Economy Ministry and used in Russia's "
                                    "budget law. For the latest quarter, if nominal GDP has not been "
                                    "published yet, it is estimated by assuming the same "
                                    "quarter-over-quarter % change as in the previous year (a crude way "
                                    "to deal with the seasonality of Russian GDP).",
                                ]
                            )
                        ),
                        # Execution estimates list item
                        html.Li(
                            html.P(
                                [
                                    html.Strong("Execution estimates:"),
                                    " The project offers total spending and total revenues as a unit of "
                                    "comparison. For the full year, the totals are not known yet. The "
                                    "project uses the planned totals from the latest budget law as an "
                                    "approximation.",
                                ]
                            )
                        ),
                    ]
                ),
                # Last updated paragraph
                html.P("Janis Kluge — Last updated: 2025-08-22", className="muted"),
            ]
        ),
        # Placeholder for any additional root-level elements
        html.Div(id="moco-bx-root"),
    ]
)
