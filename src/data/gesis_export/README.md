# Russian federal budget expense data: methodological report

## Scope and contents

This dataset contains the publicly disclosed expenditure structure of the Russian federal budget. It combines annual federal budget laws with quarterly budget execution reports for 2018–2026. The release contains 216,500 observations: 27,734 from nine annual laws (2018–2026) and 188,766 from 33 quarterly reports (March 2018–March 2026).

The unit of observation is one expenditure row at the most detailed level retained from a source document. Each row combines an amount with five classifications: responsible ministry, functional chapter, functional subchapter, government programme, and expense type. Law observations describe annual budget allocations. Report observations use the source column “Исполнено” (executed) and describe cumulative execution from the beginning of the calendar year through the reporting month; they are not expenditure flows for the individual quarter.

Only values printed in the law and execution-report workbooks are included. Values therefore represent nominal Russian rubles at current prices.

## Sources and collection

The source workbooks were downloaded manually from two official Russian government publications:

- Federal budget laws and their ведомственная структура расходов (departmental expenditure structure) were obtained from the [Russian budget portal](https://budget.gov.ru/Бюджет/Закон-о-бюджете). There is one workbook for each year.
- Quarterly federal budget execution reports were obtained from the [Federal Treasury](https://roskazna.gov.ru/ispolnenie-byudzhetov/federalnyj-byudzhet/). The relevant table is sheet 2.1, “Ведомственная структура расходов федерального бюджета.” Reports are available for March, June, September, and December in 2018–2025 and for March in 2026.

The files are administrative publications rather than survey data. Collection does not involve sampling, weighting, imputation, or contact with individuals. The export reflects the versions of the official files collected for this release; subsequent revisions by the publishing institutions are not incorporated automatically.

## Extraction and processing

Both source types present a hierarchy in a flat spreadsheet. Rows with progressively more codes identify a ministry (Мин/ГРБС), chapter (Рз), subchapter (ПР), programme (ЦСР), and expense type (ВР). Heading rows name categories and often contain subtotals, while the lowest-level rows contain the observations used here. Heading and subtotal amounts are not exported because adding them to their component rows would double-count expenditure.

For budget laws, wrapped titles that occupy several spreadsheet rows are joined before codes and values are read. A row becomes an observation only when it has an expense-type code and a numeric amount. The source sheets label their unit `тыс. рублей` (thousands of rubles): each source unit therefore represents 1,000 rubles. Source amounts are multiplied by 1,000 to express `value_rub` in individual rubles; for example, `6,261,943.9` thousand rubles becomes `6,261,943,900` rubles. Law files provide expense types only at the broad `x00` level (for example, 100 or 200).

For execution reports, only rows with a responsible ministry, a numeric executed amount, and a detailed expense-type code are retained. Expense-type codes divisible by 100 (100, 200, …, 800) are source roll-ups and are removed; retaining them would duplicate the detailed codes below them. The alternative report columns for allocations under the law and allocations after amendments are not exported. Report values are published in rubles, including kopecks, and are stored without unit conversion.

Codes are treated as text so leading zeros are preserved. Four-digit functional codes are separated into chapter and subchapter. Programme codes encode a hierarchy; trailing all-zero hierarchy segments are removed where applicable, and the programme key attached to an observation combines the programme and expense-type codes. Consequently, `program_code` is a constructed classification key rather than always a verbatim cell value. Programme parentage is inferred from the longest matching code prefix, but parent rows are not included in this flat export.

Names are cleaned by removing line breaks and repeated whitespace. A known punctuation variant in the 2020 title of chapter 13 is harmonised across years. Programme-title boilerplate is shortened, and long forms of “Russian Federation” are abbreviated. English labels were machine-translated with DeepL and subsequently normalised for quotation marks, capitalisation, and recurring programme-type prefixes. The Russian labels should be treated as the primary-language variables; the English labels are aids to interpretation rather than independent classifications.

## Variables

`expense_id` identifies a row within this release and has no substantive meaning. `budget_identifier` identifies the source series and period (`LAW-YYYY` or `REPORT-YYYY-MM`). `budget_type`, `budget_scope`, `budget_name`, and `budget_description` provide source metadata. `period_start` is the first day of the represented year or reporting month; it is a period marker, not the document’s download date. `year` repeats its calendar year for convenient analysis. `value_rub` is the source amount expressed in nominal rubles.

Each classification is represented by three fields: `_code`, `_name`, and `_name_en`. This pattern is used for `ministry`, `chapter`, `subchapter`, `program`, and `expense_type`. Codes are the appropriate variables for grouping; labels can change between documents or be normalised as described above. Empty `_name_en` cells indicate that no English translation is available.

## Quality assurance

Import stops if the expected report headings or the start of the data table cannot be identified, or if a value used as an observation is not numeric. Every source row is classified as an observation, a hierarchy heading, an excluded roll-up, or a non-data row. Duplicate dimension records are removed, unresolved hierarchy relationships are reported, and the final export requires every observation to have exactly one of each of the five classifications.

For this release, the retained rows in all 33 execution reports reproduce each workbook’s printed expenditure-structure total. Independent row-level parses were also compared for the March 2026 execution report (4,979 matching classification keys) and the 2025 budget law (3,156 matching keys). Cross-source checks against separately collected official monthly chapter totals found no excess among the 224 comparable chapter-month combinations.

## Interpretation and limitations

The law and report series should not be interpreted as directly interchangeable measures. Laws contain annual allocations, whereas reports contain cumulative realised expenditure at quarterly cut-off dates. Their expense-type classifications also have different granularity: broad `x00` groups in laws and detailed codes in reports. Comparisons should normally aggregate report expense types to a compatible level and match periods deliberately.

The dataset covers only expenditure disclosed in the detailed official structures. It does not contain classified amounts omitted from those structures, and it must not be treated as a complete measure of total federal expenditure without an appropriate external total. No classified amount is estimated in this release. Published law detail can also differ slightly from headline totals; such differences can reflect undisclosed expenditure, amendments, rounding, or inconsistencies between official publications. In particular, separate official summary brochures for 2018 and 2021 appear to reproduce draft-era chapter totals for several chapters. Those summary totals are not part of this dataset and no correction is applied to the detailed law observations.

Source classifications and institutional names change over time. Identical codes do not necessarily guarantee identical substantive coverage in every year, and renamed or reorganised ministries and programmes require substantive review before longitudinal comparison. Numeric values are not adjusted for inflation, exchange rates, changes in accounting practice, or later revisions of the source publications.
