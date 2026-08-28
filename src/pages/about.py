"""About page for the Russian budget tracker."""

from dash import dcc, html, register_page


register_page(__name__, path="/about", title="Russian Budget Monitor - About")


layout = html.Div(
    className="about-page",
    children=[
        # Hidden graph stubs keep cross-page callbacks satisfied when on this page.
        dcc.Graph(id="treemap-graph", style={"display": "none"}),
        dcc.Graph(id="timeseries-graph", style={"display": "none"}),
        html.Main(
            [
                html.H2("About this project"),
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
                        "Affairs (SWP), in cooperation with the team Digital Services and Open "
                        "Science, namely ",
                        html.A(
                            "Paul Bochtler",
                            href="https://www.swp-berlin.org/en/researcher/paul-bochtler/",
                        ),
                        " and Tom Rüger and ",
                        html.A(
                            "&effect",
                            href="https://www.and-effect.com/",
                        ),
                        ".",
                    ]
                ),
                html.H2("Sources"),
                html.P(
                    "All data is based on official Russian budget and statistical information. "
                    "You can double-check all data using the original sources (you may need a VPN "
                    "to access them):"
                ),
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
                                "Budget allocation at the chapter level for budget/draft budget laws "
                                'in the "Budget For Citizens": ',
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
                                "PPP Dollar by the OECD PPP Program, published by World Bank "
                                "(current year uses PPP rate of last year): ",
                                html.A(
                                    "Link to source",
                                    href="https://data.worldbank.org/indicator/PA.NUS.PPP?locations=RU",
                                ),
                            ]
                        ),
                    ]
                ),
                html.H2("Calculations"),
                html.Ul(
                    [
                        html.Li(
                            [
                                html.Strong("Classified spending:"),
                                " An increasing share of Russia's federal budget is classified, "
                                "meaning that no detailed budget listings are published. However, "
                                "the size of the classified share can be calculated by subtracting "
                                "public spending from total spending, which is still published on a "
                                "monthly basis. In addition, Russia published total spending for "
                                "different budget chapters in its \"Budget For Citizens\", making it "
                                "possible to calculate classified spending for each chapter for the "
                                "budget year.",
                            ]
                        ),
                        html.Li(
                            [
                                html.Strong("Estimated classified spending:"),
                                " While the total amount of classified spending is known on a "
                                "quarterly basis, it is not clear how this spending is allocated to "
                                "budget chapters. For some calculations in the project, classified "
                                "spending on a chapter level is estimated. To estimate classified "
                                "spending, the share of a chapter's classified spending in total "
                                "classified spending of the corresponding budget year is calculated. "
                                "Quarterly classified spending is then multiplied by this share. This "
                                "is particularly relevant for calculating military spending, which "
                                "includes the classified spending portions of the National Defense "
                                "and Social Spending (most likely war-related payouts) chapters. Note "
                                "that the estimate for classified military spending are likely to "
                                "underestimate the true amount: Classified spending has always been "
                                "higher than planned in the federal budget since 2022. The increase "
                                "was most likely exclusively due to the war, but the methodology of "
                                "this project allocates overruns of classified spending according to "
                                "the distribution in budget laws, meaning that only a share of the "
                                "overruns is added to classified military spending.",
                            ]
                        ),
                        html.Li(
                            [
                                html.Strong("Military expenditure:"),
                                ' What counts as "military expenditure" is always a question of '
                                "definitions and data availability. MilEx is not identical to "
                                '"National Defense" in the federal budget, because there is also '
                                "military spending in Social Spending (compensation for soldiers, "
                                "soldier's pensions etc.), National Security (the National Guard) "
                                "etc. In this project, the most widely used definition by SIPRI was "
                                "approximated. Most of military spending consists of National Defense "
                                "plus whatever from the other chapters is controlled by the Ministry "
                                "of Defense. The applicaiton of SIPRI's definition to the Russian "
                                "budget for official SIPRI data is done by Julian Cooper, who also "
                                "publishes excellent annual articles about Russian military spending "
                                "(e.g. on the ",
                                html.A(
                                    "2025 budget",
                                    href="https://www.sipri.org/publications/2025/sipri-insights-peace-and-security/preparing-fourth-year-war-military-spending-russias-budget-2025",
                                ),
                                ") in which the components of military spending are listed. This "
                                "project uses the components listed by Julian Cooper, except for the "
                                "parts of military spending that are estimates based on previous "
                                "years. Cooper's results for Russian military spending should thus "
                                "be higher than the estimates in this project.",
                            ]
                        ),
                    ]
                ),
                html.H2("Limitations and notes"),
                html.Ul(
                    [
                        html.Li(
                            [
                                html.Strong("Precision:"),
                                " The data is not always precise on a 1-ruble level for the following "
                                "reasons:",
                                html.Ul(
                                    [
                                        html.Li(
                                            [
                                                html.Strong(
                                                    "Inconsistencies in Financy Ministry data:"
                                                ),
                                                " Russia publishes three different listings on budget "
                                                "laws and execution. These listings (big Excel files) "
                                                "are often not 100% identical. In some cases, there seem "
                                                "to be typos (zero missing etc.). However, this does not "
                                                "change the data dramatically (less than a billion rubles "
                                                "discrepancy).",
                                            ]
                                        ),
                                        html.Li(
                                            [
                                                html.Strong("Negative budget execution:"),
                                                " In some years, there are cases of negative execution "
                                                "in some budget lines of some execution reports. The "
                                                "amounts are rather small (less than a billion rubles) "
                                                "and temporary. It usually happens early in the year and "
                                                "is probably related to spending to returned expenditure "
                                                "of the previous year. Because the Treemap cannot "
                                                "visualize negative elements, they are ignored, possibly "
                                                "leading to slightly different totals in the Treemap.",
                                            ]
                                        ),
                                        html.Li(
                                            [
                                                html.Strong(
                                                    "Total spending on the chapter level:"
                                                ),
                                                " For a lack of better alternatives, this project uses "
                                                "the total spending from Russia's \"Budget For Citizens\". "
                                                "The BfC publishes total spending per chapter in 100 "
                                                "million rubles resolution. The sum of the chapters "
                                                "sometimes doesn't match the total spending for the year. "
                                                "There appear to be some inconsistencies or rounding "
                                                "errors. The total of these errors does not exceed 20 "
                                                "billion rubles.",
                                            ]
                                        ),
                                    ]
                                ),
                            ]
                        ),
                        html.Li(
                            [
                                html.Strong("Data updates:"),
                                " There are regular updates to past budget execution which could lead "
                                "to changing spending totals.",
                            ]
                        ),
                        html.Li(
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
                                "published yet, it is estimated based on the best available "
                                "information. Estimates are replaced by actual data when they appear "
                                "(nominal GDP for a quarter is usually published 4-6 weeks after "
                                "quarterly budget data is available).",
                            ]
                        ),
                        html.Li(
                            [
                                html.Strong("Execution estimates:"),
                                " The project offers total spending and total revenues as a unit of "
                                "comparison. For the full year, the totals are not known yet. The "
                                "project uses the planned totals from the latest budget law as an "
                                "approximation.",
                            ]
                        ),
                    ]
                ),
                html.H2("Code and Data"),
                html.P(
                    [
                        "The corresponding research dataset is published at GESIS and can be "
                        "accessed via ",
                        html.A(
                            "DOI 10.7802/3100",
                            href="https://doi.org/10.7802/3100",
                        ),
                        ". This dashboard uses the latest version of the data by default and can contain more data than the published data at times.",
                    ]
                ),
                html.P(
                    [
                        "The source code for this dashboard is publicly available on ",
                        html.A(
                            "GitHub",
                            href="https://github.com/swp-berlin/ru_budget_tracker",
                        ),
                        " and permanently archived on Zenodo under ",
                        html.A(
                            "DOI 10.5281/zenodo.21875631",
                            href="https://doi.org/10.5281/zenodo.21875631",
                        ),
                        ". You can clone the repository with:",
                    ]
                ),
                html.Pre(
                    html.Code(
                        "git clone https://github.com/swp-berlin/ru_budget_tracker.git"
                    )
                ),
            ]
        ),
        html.Div(id="moco-bx-root"),
    ],
)
