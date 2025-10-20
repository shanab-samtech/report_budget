# Copyright (c) 2025, Samtech and contributors
# For license information, please see license.txt


import datetime

import frappe
from frappe import _
from frappe.utils import flt, formatdate

from erpnext.controllers.trends import get_period_date_ranges, get_period_month_ranges


def execute(filters=None):
	if not filters:
		filters = {}

	columns = get_columns(filters)
	if filters.get("budget_against_filter"):
		dimensions = filters.get("budget_against_filter")
	else:
		dimensions = get_cost_centers(filters)

	period_month_ranges = get_period_month_ranges(filters["period"], filters["from_fiscal_year"])
	cam_map = get_dimension_account_month_map(filters)

	data = []
	for dimension in dimensions:
		dimension_items = cam_map.get(dimension)
		if dimension_items:
			data = get_final_data(dimension, dimension_items, filters, period_month_ranges, data, 0)

	chart = get_chart_data(filters, columns, data)

	return columns, data, None, chart


def get_final_data(dimension, dimension_items, filters, period_month_ranges, data, DCC_allocation):
	for account, monthwise_data in dimension_items.items():
		# Only include Expense accounts that are not groups and not disabled
		account_doc = frappe.get_value(
			"Account",
			account,
			["root_type", "is_group", "disabled"],
			as_dict=True,
		)
		if not account_doc or account_doc.root_type != "Expense" or account_doc.is_group or account_doc.disabled:
			continue

		row = [dimension, account]
		total_actual = 0

		for year in get_fiscal_years(filters):
			for relevant_months in period_month_ranges:
				period_actual = 0
				for month in relevant_months:
					if monthwise_data.get(year[0]):
						month_data = monthwise_data.get(year[0]).get(month, {})
						value = flt(month_data.get("actual"))
						if DCC_allocation:
							value *= DCC_allocation / 100
						period_actual += value
						total_actual += value
				row.append(period_actual)

		if filters["period"] != "Yearly":
			row.append(total_actual)

		data.append(row)

	return data


def get_columns(filters):
	columns = [
		{
			"label": _(filters.get("budget_against")),
			"fieldtype": "Link",
			"fieldname": "budget_against",
			"options": filters.get("budget_against"),
			"width": 150,
		},
		{
			"label": _("Account"),
			"fieldname": "account",
			"fieldtype": "Link",
			"options": "Account",
			"width": 150,
		},
	]

	fiscal_years = get_fiscal_years(filters)

	for year in fiscal_years:
		for from_date, to_date in get_period_date_ranges(filters["period"], year[0]):
			if filters["period"] == "Yearly":
				columns.append(
					{
						"label": _("Actual") + f" {year[0]}",
						"fieldtype": "Float",
						"fieldname": frappe.scrub(f"Actual {year[0]}"),
						"width": 150,
					}
				)
			else:
				label = (
					formatdate(from_date, format_string="MMM")
					+ "-"
					+ formatdate(to_date, format_string="MMM")
				)
				columns.append(
					{
						"label": _("Actual") + f" ({label}) {year[0]}",
						"fieldtype": "Float",
						"fieldname": frappe.scrub(f"Actual {label} {year[0]}"),
						"width": 150,
					}
				)

	if filters["period"] != "Yearly":
		columns.append(
			{
				"label": _("Total Actual"),
				"fieldtype": "Float",
				"fieldname": "total_actual",
				"width": 150,
			}
		)

	return columns


def get_cost_centers(filters):
	order_by = ""
	if filters.get("budget_against") == "Cost Center":
		order_by = "order by lft"

	if filters.get("budget_against") in ["Cost Center", "Project"]:
		return frappe.db.sql_list(
			"""
				select
					name
				from
					`tab{tab}`
				where
					company = %s
				{order_by}
			""".format(tab=filters.get("budget_against"), order_by=order_by),
			filters.get("company"),
		)
	else:
		return frappe.db.sql_list(
			"""
				select
					name
				from
					`tab{tab}`
			""".format(tab=filters.get("budget_against"))
		)  # nosec


def get_dimension_target_details(filters):
	budget_against = frappe.scrub(filters.get("budget_against"))
	cond = ""
	if filters.get("budget_against_filter"):
		cond += f""" and b.{budget_against} in (%s)""" % ", ".join(
			["%s"] * len(filters.get("budget_against_filter"))
		)

	return frappe.db.sql(
		f"""
			select
				b.{budget_against} as budget_against,
				b.monthly_distribution,
				ba.account,
				ba.budget_amount,
				b.fiscal_year
			from
				`tabBudget` b,
				`tabBudget Account` ba
			where
				b.name = ba.parent
				and b.docstatus = 1
				and b.fiscal_year between %s and %s
				and b.budget_against = %s
				and b.company = %s
				{cond}
			order by
				b.fiscal_year
		""",
		tuple(
			[
				filters.from_fiscal_year,
				filters.to_fiscal_year,
				filters.budget_against,
				filters.company,
			]
			+ (filters.get("budget_against_filter") or [])
		),
		as_dict=True,
	)


def get_target_distribution_details(filters):
	target_details = {}
	for d in frappe.db.sql(
		"""
			select
				md.name,
				mdp.month,
				mdp.percentage_allocation
			from
				`tabMonthly Distribution Percentage` mdp,
				`tabMonthly Distribution` md
			where
				mdp.parent = md.name
				and md.fiscal_year between %s and %s
			order by
				md.fiscal_year
		""",
		(filters.from_fiscal_year, filters.to_fiscal_year),
		as_dict=1,
	):
		target_details.setdefault(d.name, {}).setdefault(d.month, flt(d.percentage_allocation))

	return target_details


def get_actual_details(name, filters):
	budget_against = frappe.scrub(filters.get("budget_against"))
	cond = ""

	if filters.get("budget_against") == "Cost Center":
		cc_lft, cc_rgt = frappe.db.get_value("Cost Center", name, ["lft", "rgt"])
		cond = f"""
				and lft >= "{cc_lft}"
				and rgt <= "{cc_rgt}"
			"""

	ac_details = frappe.db.sql(
		f"""
			select
				gl.account,
				gl.debit,
				gl.credit,
				gl.fiscal_year,
				MONTHNAME(gl.posting_date) as month_name,
				b.{budget_against} as budget_against
			from
				`tabGL Entry` gl,
				`tabBudget Account` ba,
				`tabBudget` b
			where
				b.name = ba.parent
				and b.docstatus = 1
				and ba.account=gl.account
				and b.{budget_against} = gl.{budget_against}
				and gl.fiscal_year between %s and %s
				and gl.is_cancelled = 0
				and b.{budget_against} = %s
				and exists(
					select
						name
					from
						`tab{filters.budget_against}`
					where
						name = gl.{budget_against}
						{cond}
				)
				group by
					gl.name
				order by gl.fiscal_year
		""",
		(filters.from_fiscal_year, filters.to_fiscal_year, name),
		as_dict=1,
	)

	cc_actual_details = {}
	for d in ac_details:
		cc_actual_details.setdefault(d.account, []).append(d)

	return cc_actual_details


def get_dimension_account_month_map(filters):
    # Get budgeted accounts
    dimension_target_details = get_dimension_target_details(filters)
    tdd = get_target_distribution_details(filters)

    cam_map = {}

    # First, get all Expense accounts in the company
    all_accounts = frappe.get_all(
        "Account",
        filters={"company": filters.get("company"), "root_type": "Expense"},
        fields=["name"],
    )
    all_accounts = [a.name for a in all_accounts]

    for dimension in get_cost_centers(filters):  # or projects, depending on budget_against
        actual_details = get_actual_details(dimension, filters)

        # Merge budgeted accounts with all expense accounts
        accounts_to_process = list({ccd.account for ccd in dimension_target_details if ccd.budget_against == dimension})
        accounts_to_process = list(set(accounts_to_process + all_accounts))

        for account in accounts_to_process:
            for month_id in range(1, 13):
                month = datetime.date(2013, month_id, 1).strftime("%B")
                for fy in get_fiscal_years(filters):
                    fy = fy[0]
                    cam_map.setdefault(dimension, {}).setdefault(account, {}).setdefault(fy, {}).setdefault(
                        month, frappe._dict({"target": 0.0, "actual": 0.0})
                    )

                    tav_dict = cam_map[dimension][account][fy][month]

                    # Fill budget if exists
                    budget_entry = next(
                        (b for b in dimension_target_details if b.account == account and b.budget_against == dimension and b.fiscal_year == fy),
                        None,
                    )

                    month_percentage = (
                        tdd.get(budget_entry.monthly_distribution, {}).get(month, 0) if budget_entry and budget_entry.monthly_distribution else 100.0 / 12
                    )

                    if budget_entry:
                        tav_dict.target = flt(budget_entry.budget_amount) * month_percentage / 100

                    # Fill actuals
                    for ad in actual_details.get(account, []):
                        if ad.month_name == month and ad.fiscal_year == fy:
                            tav_dict.actual += flt(ad.debit) - flt(ad.credit)

    return cam_map



def get_fiscal_years(filters):
	fiscal_year = frappe.db.sql(
		"""
			select
				name
			from
				`tabFiscal Year`
			where
				name between %(from_fiscal_year)s and %(to_fiscal_year)s
		""",
		{"from_fiscal_year": filters["from_fiscal_year"], "to_fiscal_year": filters["to_fiscal_year"]},
	)

	return fiscal_year


def get_chart_data(filters, columns, data):
	if not data:
		return None

	labels = []

	fiscal_years = get_fiscal_years(filters)
	group_months = False if filters["period"] == "Monthly" else True

	for year in fiscal_years:
		for from_date, to_date in get_period_date_ranges(filters["period"], year[0]):
			if filters["period"] == "Yearly":
				labels.append(year[0])
			else:
				if group_months:
					label = (
						formatdate(from_date, format_string="MMM")
						+ "-"
						+ formatdate(to_date, format_string="MMM")
					)
					labels.append(label)
				else:
					label = formatdate(from_date, format_string="MMM")
					labels.append(label)

	no_of_columns = len(labels)
	actual_values = [0] * no_of_columns

	for d in data:
		values = d[2:]
		for i in range(no_of_columns):
			actual_values[i] += values[i]

	return {
		"data": {
			"labels": labels,
			"datasets": [
				{"name": _("Actual Expense"), "chartType": "bar", "values": actual_values},
			],
		},
		"type": "bar",
	}



