# Data Model

The current database schema is visualized in the
[Database Schema Overview](../../README.md#database-schema-overview)
using a Mermaid ER diagram.

## Budgets
The `Budget` model represents a budget entity in the database. It contains fields such as `id`, `original_identifier`, `name`, `name_translated`, `description`, `description_translated`,
`type`, `scope`, `published_at`, `planned_at`, `created_at`, and `updated_at`. Each budget can contain multiple expenses. The `type` field is an enumeration that defines the type of budget (e.g., DRAFT, LAW, REPORT, TOTAL), while the `scope` field defines the scope of the budget (e.g., QUARTERLY). The `published_at` and `planned_at` fields are used to track the publication and planning dates of the budget, respectively. These dates should always be in the past and be the first day of a month. The `created_at` and `updated_at` fields are used to track the creation and last update timestamps of the budget record.

### TOTAL Budgets
A "TOTAL" budget represents the overall budget used in real life budgeting and is published retrospectively as a report. To calculate differences between planned, published and actual expenses, we compare the "TOTAL" budget with other budget types and subtract expenses accordingly.

## Dimensions
The `Dimension` model represents a dimension entity in the database. It includes fields like `id`, `original_identifier`, `type`, `name`, `name_translation`, and `parent_id`. Dimensions can be organized hierarchically using the `parent_id` field. The `type` field is an enumeration that defines the type of dimension (e.g., MINISTRY, EXPENSE_TYPE).
Each dimension can be associated with multiple expenses through the `ExpenseDimensions` association table.

## Expenses
The `Expense` model represents an expense entity in the database. It contains fields such as `id`, `budget_id`, `value`, `created_at`, and `updated_at`. Each expense is associated with a budget through the `budget_id` foreign key. The `value` field represents the monetary value of the expense. The `created_at` and `updated_at` fields are used to track the creation and last update timestamps of the expense record. Expenses can be linked to multiple dimensions through the `ExpenseDimensions` association table.

## expense_dimension_association_table
The `expense_dimension_association_table` table is an association table that links expenses to dimensions. It contains two primary key fields: `expense_id` and `dimension_id`, which are foreign keys referencing the `Expense` and `Dimension` models, respectively. This table allows for a many-to-many relationship between expenses and dimensions, enabling each expense to be associated with multiple dimensions and vice versa.

## ConversionRates
The `ConversionRate` model represents currency conversion rates in the database. It includes fields such as `name`, `value`, `started_at`, `ended_at`, `created_at`, and `updated_at`. The `name` field serves as the primary key and typically follows the format "FROM_TO" (e.g., "RUB_USD"). The `value` field represents the conversion rate. The `started_at` and `ended_at` fields define the validity period of the conversion rate. The `created_at` and `updated_at` fields are used to track the creation and last update timestamps of the conversion rate record.
