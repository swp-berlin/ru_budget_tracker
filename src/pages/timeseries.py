# from typing import Any
# import pandas as pd
# import plotly.express as px
# import plotly.graph_objects as go
# from dash import (
#     Input,
#     Output,
#     State,
#     callback,
#     dcc,
#     html,
#     register_page,
# )

# from models import ViewByDimensionTypeLiteral
# from utils.transform import BarchartTransformer
# from utils.definitions import (
#     SpendingScopeLiteral,
#     SpendingTypeLiteral,
# )
# from utils.fetch import fetch_barchart_data, fetch_budgets


# register_page(__name__, path="/timeseries")


# def layout(**other_unknown_query_strings: str | None) -> html.Div:
#     # Load budget data from database to populate dropdown options
#     budgets = fetch_budgets()

#     # Create dropdown options from budget data
#     # Using name_translated for display label and type for value
#     budget_options = []
#     for budget in budgets:
#         budget_options.append(
#             {
#                 "label": budget["name_translated"]
#                 or budget["name"],  # Use translated name if available, fallback to name
#                 "value": budget["id"],  # Use budget type as the value
#             }
#         )
#     return html.Div(
#         [
#             # dcc.Location is used to read the URL from the browser's address bar.
#             # Its 'search' property (the query string) is used to get the 'focus' parameter.
#             dcc.Location(id="url"),
#             # Add Buttons and dropdowns for filtering by budget type
#             html.Div(
#                 [
#                     html.Div(
#                         [
#                             html.H1("Filters: "),
#                             dcc.Dropdown(
#                                 id="budget-dataset-dropdown",
#                                 options=budget_options,
#                                 clearable=False,
#                                 value=budget_options[0]["value"] if budget_options else None,
#                                 placeholder=budget_options[0]["label"]
#                                 if budget_options
#                                 else "Select Budget",
#                                 searchable=True,
#                                 style={"width": "100px"},
#                             ),
#                             dcc.Dropdown(
#                                 id="viewby-dropdown",
#                                 options=[
#                                     {"label": "Ministry", "value": "MINISTRY"},
#                                     {"label": "Chapter", "value": "CHAPTER"},
#                                     {"label": "Programm", "value": "PROGRAMM"},
#                                 ],
#                                 clearable=False,
#                                 value="MINISTRY",
#                                 placeholder="Ministry",
#                                 style={"width": "150px"},
#                                 disabled=True,
#                             ),
#                             dcc.Dropdown(
#                                 id="spending-type-dropdown",
#                                 options=[
#                                     {"label": "All", "value": "ALL"},
#                                     {"label": "Military Only", "value": "MILITARY"},
#                                 ],
#                                 clearable=False,
#                                 placeholder="All",
#                                 value="ALL",
#                                 style={"width": "150px"},
#                             ),
#                             dcc.Dropdown(
#                                 id="spending-scope-dropdown",
#                                 options=[
#                                     {"label": "Billion RUB", "value": "ABSOLUT"},
#                                     {"label": "% full-year GDP", "value": "PERCENT_GDP_FULL_YEAR"},
#                                     {
#                                         "label": "% year-to-year GDP",
#                                         "value": "PERCENT_GDP_YEAR_TO_YEAR",
#                                     },
#                                     {
#                                         "label": "% full-year spending",
#                                         "value": "PERCENT_FULL_YEAR_SPENDING",
#                                     },
#                                     {
#                                         "label": "% year-to-year spending",
#                                         "value": "PERCENT_YEAR_TO_YEAR_SPENDING",
#                                     },
#                                     {
#                                         "label": "% year-to-year revenue",
#                                         "value": "PERCENT_YEAR_TO_YEAR_REVENUE",
#                                     },
#                                 ],
#                                 clearable=False,
#                                 value="ABSOLUT",
#                                 placeholder="Billion RUB",
#                                 style={"width": "200px"},
#                             ),
#                         ],
#                         style={
#                             "display": "flex",
#                             "flex-wrap": "wrap",
#                             "justify-content": "flex-start",
#                             "gap": "10px",
#                         },
#                     ),
#                     html.Div(
#                         [
#                             html.Div(
#                                 [
#                                     html.Button("Download CSV", id="btn-download-csv"),
#                                     dcc.Download(id="download-barchart-data"),
#                                 ]
#                             ),
#                             dcc.Link(
#                                 html.Button("Treemap"),
#                                 href="/",
#                             ),
#                             dcc.Link(
#                                 html.Button("About"),
#                                 href="/about",
#                             ),
#                         ],
#                         style={
#                             "display": "flex",
#                             "flex-wrap": "wrap",
#                             "justify-content": "flex-end",
#                             "gap": "10px",
#                         },
#                     ),
#                 ],
#                 style={
#                     "display": "flex",
#                     "flex-wrap": "wrap",
#                     "justify-content": "space-between",
#                     "gap": "10px",
#                     "margin-bottom": "20px",
#                     "margin-top": "20px",
#                 },
#             ),
#             # Graph to display the treemap
#             dcc.Store(id="barchart-store"),
#             dcc.Graph(id="barchart-graph"),
#         ]
#     )


# def generate_figure(df: pd.DataFrame) -> go.Figure:
#     fig = px.histogram(
#         data_frame=df,
#         x="dates",
#         y="expenses",
#         color="types",
#         barmode="relative",
#     )
#     fig.update_layout(margin=dict(t=50, l=25, r=25, b=25))
#     return fig


# # Callback to populate the graph on load and when filters change
# @callback(
#     Output("barchart-graph", "figure"),
#     Input("budget-dataset-dropdown", "value"),
#     Input("viewby-dropdown", "value"),
#     Input("spending-type-dropdown", "value"),
#     Input("spending-scope-dropdown", "value"),
# )
# def update_figure_from_filters(
#     budget_dataset: int | None = None,
#     viewby: ViewByDimensionTypeLiteral = "MINISTRY",
#     spending_type: SpendingTypeLiteral = "ALL",
#     spending_scope: SpendingScopeLiteral = "ABSOLUT",
# ) -> go.Figure:
#     """
#     This callback is triggered on page load and when the budget type dropdown changes.
#     It loads the appropriate data and generates the treemap figure.

#     Args:
#         budget_type (str | None): The selected value from the budget type dropdown.

#     Returns:
#         go.Figure: The generated treemap figure to display in the dcc.Graph.
#     """
#     # Load data based on the selected filter
#     data = fetch_barchart_data(
#         budget_dataset=budget_dataset,
#         viewby=viewby,
#         spending_type=spending_type,
#         spending_scope=spending_scope,
#     )
#     transformer = BarchartTransformer(data, translated=False)
#     df = transformer.transform_data()
#     # Generate and return the figure
#     return generate_figure(df=df)


# @callback(
#     Output("download-barchart-data", "data"),
#     Input("btn-download-csv", "n_clicks"),
#     State("barchart-store", "data"),
#     prevent_initial_call=True,
# )
# def download_data(n_clicks, data) -> dict[str, Any]:
#     """
#     Callback to download the current treemap data as a csv file.
#     Returns:
#         dict[str, Any]: The data for download.
#     """
#     return dcc.send_data_frame(  # type: ignore
#         pd.DataFrame(
#             fetch_barchart_data(
#                 budget_dataset=data["budget_dataset"],
#                 viewby=data["viewby"],
#                 spending_type=data["spending_type"],
#                 spending_scope=data["spending_scope"],
#             )
#         ).to_csv,
#         "treemap_data.csv",
#         sep=";",
#         index=False,
#     )
