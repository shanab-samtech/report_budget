# Copyright (c) 2025, Samtech and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	if not filters:
		filters = {}

	columns = get_columns(filters)

	filter_type = filters.get("filter_type") or "fiscal_year"

	if filter_type == "date_range":
		date_cond = "and gl.posting_date between %(from_date)s and %(to_date)s"
	else:
		date_cond = "and gl.fiscal_year between %(from_fiscal_year)s and %(to_fiscal_year)s"

	dimensions = (
		filters.get("budget_against_filter")
		or get_cost_centers(filters)
	)

	data = []

	for dimension in dimensions:
		# Fetch all expense accounts (not group, not disabled)
		accounts = frappe.db.sql(
			"""
			select name
			from `tabAccount`
			where
				company = %s
				and root_type = 'Expense'
				and is_group = 0
				and disabled = 0
			order by name
			""",
			(filters.get("company"),),
			as_dict=True,
		)

		for acc in accounts:
			actual = frappe.db.sql(
				f"""
				select
					sum(gl.debit - gl.credit)
				from
					`tabGL Entry` gl
				where
					gl.company = %(company)s
					and gl.account = %(account)s
					and gl.{frappe.scrub(filters.get("budget_against"))} = %(dimension)s
					and gl.is_cancelled = 0
					{date_cond}
				""",
				{
					"company": filters.get("company"),
					"account": acc.name,
					"dimension": dimension,
					"from_fiscal_year": filters.get("from_fiscal_year"),
					"to_fiscal_year": filters.get("to_fiscal_year"),
					"from_date": filters.get("from_date"),
					"to_date": filters.get("to_date"),
				},
			)[0][0] or 0.0

			data.append({
				"budget_against": dimension,
				"account": acc.name,
				"actual": flt(actual),
			})

	chart = get_chart_data(data)
	return columns, data, None, chart

def get_columns(filters):
	return [
		{
			"label": _(filters.get("budget_against")),
			"fieldtype": "Link",
			"fieldname": "budget_against",
			"options": filters.get("budget_against"),
			"width": 180,
		},
		{
			"label": _("Account"),
			"fieldtype": "Link",
			"fieldname": "account",
			"options": "Account",
			"width": 180,
		},
		{
			"label": _("Actual Value"),
			"fieldtype": "Float",
			"fieldname": "actual",
			"width": 150,
		},
	]


def get_cost_centers(filters):
	if filters.get("budget_against") == "Cost Center":
		return frappe.db.sql_list("""
			select name from `tabCost Center`
			where company = %s and is_group = 0 order by lft
		""", filters.get("company"))
	elif filters.get("budget_against") == "Project":
		return frappe.db.sql_list("""
			select name from `tabProject`
			where company = %s
		""", filters.get("company"))
	else:
		return frappe.db.sql_list(f"select name from `tab{filters.get('budget_against')}`")


def get_chart_data(data):
	if not data:
		return None

	# aggregate by dimension
	agg = {}
	for d in data:
		agg[d["budget_against"]] = agg.get(d["budget_against"], 0) + d["actual"]

	labels = list(agg.keys())
	values = list(agg.values())

	return {
		"data": {
			"labels": labels,
			"datasets": [
				{"name": _("Total Actual"), "chartType": "bar", "values": values},
			],
		},
		"type": "bar",
	}
