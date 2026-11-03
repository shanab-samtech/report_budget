# Copyright (c) 2025, Samtech and contributors
# For license information, please see license.txt

# Budget targets for ERPNext v16, where each Budget holds a single account and
# amount, spans from_fiscal_year..to_fiscal_year, and is split over time by the
# "Budget Distribution" child table (replaces Budget Account + Monthly Distribution).

import frappe
from frappe.utils import add_months, flt, getdate

from erpnext.accounts.utils import get_fiscal_year


def get_budget_records(filters):
	budget_against = frappe.scrub(filters.get("budget_against"))
	budget = frappe.qb.DocType("Budget")

	query = (
		frappe.qb.from_(budget)
		.select(budget.name, budget.account, budget[budget_against].as_("budget_against"))
		.where(
			(budget.docstatus == 1)
			& (budget.company == filters.get("company"))
			& (budget.budget_against == filters.get("budget_against"))
			& (budget.from_fiscal_year <= filters.get("to_fiscal_year"))
			& (budget.to_fiscal_year >= filters.get("from_fiscal_year"))
		)
	)
	if filters.get("budget_against_filter"):
		query = query.where(budget[budget_against].isin(filters.get("budget_against_filter")))

	return query.run(as_dict=True)


def get_budget_targets(filters):
	"""Return budget target rows as dicts of budget_against, account, fiscal_year, month and amount.

	Each Budget Distribution row's amount is split equally over the months it covers,
	matching ERPNext v16's Budget Variance Report.
	"""
	budgets = get_budget_records(filters)
	if not budgets:
		return []

	distribution = frappe.qb.DocType("Budget Distribution")
	distribution_rows = (
		frappe.qb.from_(distribution)
		.select(distribution.parent, distribution.start_date, distribution.end_date, distribution.amount)
		.where(distribution.parent.isin([b.name for b in budgets]))
		.orderby(distribution.start_date)
	).run(as_dict=True)

	rows_by_budget = {}
	for row in distribution_rows:
		rows_by_budget.setdefault(row.parent, []).append(row)

	fiscal_year_cache = {}
	targets = []
	for budget in budgets:
		for row in rows_by_budget.get(budget.name, []):
			if not row.start_date or not row.end_date:
				continue

			months = get_months_in_range(getdate(row.start_date), getdate(row.end_date))
			if not months:
				continue

			monthly_amount = flt(row.amount) / len(months)
			for month_date in months:
				if month_date not in fiscal_year_cache:
					fiscal_year_cache[month_date] = get_fiscal_year(month_date, company=filters.get("company"))[0]

				targets.append(
					frappe._dict(
						budget_against=budget.budget_against,
						account=budget.account,
						fiscal_year=fiscal_year_cache[month_date],
						month=month_date.strftime("%B"),
						amount=monthly_amount,
					)
				)

	return targets


def get_months_in_range(start_date, end_date):
	months = []
	current = start_date
	while current <= end_date:
		months.append(current)
		current = add_months(current, 1)

	return months
