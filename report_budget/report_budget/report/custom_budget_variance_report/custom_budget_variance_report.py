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
    
    # --- MODIFICATION START ---
    all_expense_accounts = get_all_expense_accounts(filters)
    # --- MODIFICATION END ---

    data = []
    for dimension in dimensions:
        dimension_items = cam_map.get(dimension)
        
        # --- MODIFICATION START: Call the new function to process accounts ---
        data = get_final_data_for_dimension(
            dimension, 
            dimension_items, 
            all_expense_accounts, # Pass all expense accounts
            filters, 
            period_month_ranges, 
            data, 
            0, 
            actual_only=True
        )
        # --- MODIFICATION END ---

    chart = get_chart_data(filters, columns, data, actual_only=True)

    return columns, data, None, chart

# New function to handle iteration over all expense accounts for a dimension
def get_final_data_for_dimension(
    dimension, 
    dimension_items, 
    all_expense_accounts, # New argument
    filters, 
    period_month_ranges, 
    data, 
    DCC_allocation, 
    actual_only=False
):
    # Iterate over ALL non-group Expense accounts
    for account in all_expense_accounts:
        monthwise_data = dimension_items.get(account) if dimension_items else None
        
        if monthwise_data:
            # Case 1: Account has budget/actual data (GL Entry) - use existing logic
            # This is essentially the old logic for that account
            data = get_final_data_row(
                dimension, 
                account, 
                monthwise_data, 
                filters, 
                period_month_ranges, 
                data, 
                DCC_allocation, 
                actual_only
            )
        else:
            # Case 2: Account has NO data (No GL Entry) - add a row of zeros
            # This handles the requirement "even if it has no gl entry"
            
            # Create a dummy monthwise_data structure for accounts with no data
            # to calculate the number of columns and append a zero-filled row.
            dummy_monthwise_data = {} 
            for year in get_fiscal_years(filters):
                for month_range in period_month_ranges:
                    for month in month_range:
                        dummy_monthwise_data.setdefault(year[0], {})[month] = frappe._dict({
                            "target": 0.0, 
                            "actual": 0.0,
                            "variance": 0.0
                        })
            
            # Use the existing row logic with the zero-filled dummy data
            data = get_final_data_row(
                dimension, 
                account, 
                dummy_monthwise_data, 
                filters, 
                period_month_ranges, 
                data, 
                DCC_allocation, 
                actual_only
            )
            
    return data

# Modified to only include Actual and exclude Budget and Variance
# Renamed from get_final_data to get_final_data_row to reflect its purpose: 
# processing a single account's data into a row.
def get_final_data_row(dimension, account, monthwise_data, filters, period_month_ranges, data, DCC_allocation, actual_only=False):
    # Old loop was 'for account, monthwise_data in dimension_items.items():'
    # New function receives a single account and its monthwise_data
    
    row = [dimension, account]
    totals = [0, 0, 0] # totals[0]=Budget, totals[1]=Actual, totals[2]=Variance
    
    # Fieldnames to track: target (Budget), actual, variance. 
    # We only care about actual (index 1) for the output row.
    fieldnames_to_process = ["target", "actual", "variance"] 
    
    for year in get_fiscal_years(filters):
        last_total = 0 # Used for cumulative Budget - Actual
        
        for relevant_months in period_month_ranges:
            period_data = [0, 0, 0] # period_data[0]=Budget, period_data[1]=Actual, period_data[2]=Variance
            
            for month in relevant_months:
                if monthwise_data.get(year[0]):
                    month_data = monthwise_data.get(year[0]).get(month, {})
                    
                    # Always calculate all three internally
                    for i, fieldname in enumerate(fieldnames_to_process):
                        # Ensure we get a value (0.0 if month_data is empty, e.g., for non-GL accounts)
                        value = flt(month_data.get(fieldname)) 
                        period_data[i] += value
                        totals[i] += value

            # Note: Cumulative logic still needs 'Budget' (index 0) and 'Actual' (index 1)
            period_data[0] += last_total

            if DCC_allocation:
                period_data[0] = period_data[0] * (DCC_allocation / 100)
                period_data[1] = period_data[1] * (DCC_allocation / 100)

            if filters.get("show_cumulative"):
                # This calculation needs both Budget (0) and Actual (1)
                last_total = period_data[0] - period_data[1]

            # This calculation needs both Budget (0) and Actual (1)
            period_data[2] = period_data[0] - period_data[1]
            
            # *** Modification: Only append Actual (index 1) ***
            if actual_only:
                row.append(period_data[1]) 
            else:
                # Original logic (append all three: Budget, Actual, Variance)
                row += period_data
                
    # *** Modification: Only append Total Actual (index 1) ***
    totals[2] = totals[0] - totals[1] # Calculate Total Variance
    if filters["period"] != "Yearly":
        if actual_only:
            row.append(totals[1]) # Only Total Actual
        else:
            # Original logic (append all three totals: Budget, Actual, Variance)
            row += totals 
            
    data.append(row)

    return data
# Modified to only include Actual columns and Total Actual
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
			"fieldname": "Account",
			"fieldtype": "Link",
			"options": "Account",
			"width": 150,
		},
	]

	group_months = False if filters["period"] == "Monthly" else True

	fiscal_year = get_fiscal_years(filters)

	for year in fiscal_year:
		for from_date, to_date in get_period_date_ranges(filters["period"], year[0]):
			if filters["period"] == "Yearly":
				# *** Modification: Only include Actual ***
				labels = [
					_("Actual") + " " + str(year[0]),
				]
				for label in labels:
					columns.append(
						{"label": label, "fieldtype": "Float", "fieldname": frappe.scrub(label), "width": 150}
					)
			else:
				# *** Modification: Only include Actual ***
				for label in [
					_("Actual") + " (%s)" + " " + str(year[0]),
				]:
					if group_months:
						label = label % (
							formatdate(from_date, format_string="MMM")
							+ "-"
							+ formatdate(to_date, format_string="MMM")
						)
					else:
						label = label % formatdate(from_date, format_string="MMM")

					columns.append(
						{"label": label, "fieldtype": "Float", "fieldname": frappe.scrub(label), "width": 150}
					)

	if filters["period"] != "Yearly":
		# *** Modification: Only include Total Actual ***
		for label in [_("Total Actual")]:
			columns.append(
				{"label": label, "fieldtype": "Float", "fieldname": frappe.scrub(label), "width": 150}
			)

		return columns
	else:
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


# Get dimension & target details
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


# Get target distribution details of accounts of cost center
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


# Get actual details from gl entry
def get_actual_details(name, filters):
	budget_against = frappe.scrub(filters.get("budget_against"))
	cond = ""
	
	if filters.get("budget_against") == "Cost Center":
		cc_lft, cc_rgt = frappe.db.get_value("Cost Center", name, ["lft", "rgt"])
		cond += f"""
				and exists(
					select
						name
					from
						`tabCost Center`
					where
						name = gl.{budget_against}
						and lft >= "{cc_lft}"
						and rgt <= "{cc_rgt}"
				)
			"""

	params = {
		"from_fiscal_year": filters.from_fiscal_year,
		"to_fiscal_year": filters.to_fiscal_year,
		"name": name,
	}
	
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
				and gl.fiscal_year between %(from_fiscal_year)s and %(to_fiscal_year)s
				and gl.is_cancelled = 0
				and b.{budget_against} = %(name)s
				{cond}
				group by
					gl.name
				order by gl.fiscal_year
		""",
		params, # Pass the parameters dictionary
		as_dict=1,
	)

	cc_actual_details = {}
	for d in ac_details:
		cc_actual_details.setdefault(d.account, []).append(d)

	return cc_actual_details

def get_dimension_account_month_map(filters):
	dimension_target_details = get_dimension_target_details(filters)
	tdd = get_target_distribution_details(filters)

	cam_map = {}

	for ccd in dimension_target_details:
		actual_details = get_actual_details(ccd.budget_against, filters)

		for month_id in range(1, 13):
			month = datetime.date(2013, month_id, 1).strftime("%B")
			cam_map.setdefault(ccd.budget_against, {}).setdefault(ccd.account, {}).setdefault(
				ccd.fiscal_year, {}
			).setdefault(month, frappe._dict({"target": 0.0, "actual": 0.0}))

			tav_dict = cam_map[ccd.budget_against][ccd.account][ccd.fiscal_year][month]
			month_percentage = (
				tdd.get(ccd.monthly_distribution, {}).get(month, 0)
				if ccd.monthly_distribution
				else 100.0 / 12
			)

			tav_dict.target = flt(ccd.budget_amount) * month_percentage / 100

			for ad in actual_details.get(ccd.account, []):
				if ad.month_name == month and ad.fiscal_year == ccd.fiscal_year:
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


# Modified to only include Actual Expense in the chart
def get_chart_data(filters, columns, data, actual_only=False):
	if not data:
		return None

	labels = []

	fiscal_year = get_fiscal_years(filters)
	group_months = False if filters["period"] == "Monthly" else True

	for year in fiscal_year:
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
	
	# If we are only showing actuals, there is one data point per period.
	# Otherwise, there were three (Budget, Actual, Variance).
	data_points_per_period = 1 if actual_only else 3

	budget_values, actual_values = [0] * no_of_columns, [0] * no_of_columns
	for d in data:
		# Start from the 3rd column (index 2) as the first two are Dimension and Account
		values = d[2:]
		index = 0

		for i in range(no_of_columns):
			if actual_only:
				# If actual_only is True, values[index] is the Actual amount
				actual_values[i] += values[index]
				# index increments by 1
				index += data_points_per_period 
			else:
				# Original logic (Budget is index, Actual is index + 1)
				budget_values[i] += values[index]
				actual_values[i] += values[index + 1]
				# index increments by 3 (Budget, Actual, Variance)
				index += data_points_per_period

	# *** Modification: Only include Actual Expense dataset ***
	# If you want to completely remove the chart, return None here.
	# If you want a chart with only Actual Expense:
	return {
		"data": {
			"labels": labels,
			"datasets": [
				# {"name": _("Budget"), "chartType": "bar", "values": budget_values}, # Removed Budget
				{"name": _("Actual Expense"), "chartType": "bar", "values": actual_values},
			],
		},
		"type": "bar",
	}
 
 
 
 
 # Add this new function to your script

def get_all_expense_accounts(filters):
    """
    Fetches all non-Group, non-disabled Expense accounts for the company.
    """
    return frappe.db.sql_list(
        """
            SELECT
                name
            FROM
                `tabAccount`
            WHERE
                company = %(company)s
                AND root_type = 'Expense'
                AND is_group = 0
                AND disabled = 0
            ORDER BY
                name
        """,
        {"company": filters.get("company")},
    )
    
    
    