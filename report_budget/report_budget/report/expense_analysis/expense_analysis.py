# Copyright (c) 2025, Samtech and contributors
# For license information, please see license.txt

import datetime
from dateutil.relativedelta import relativedelta

import frappe
from frappe import _
from frappe.utils import flt, formatdate, getdate, add_months

from erpnext.controllers.trends import get_period_date_ranges, get_period_month_ranges


def execute(filters=None):
    if not filters:
        filters = {}

    # Validate filter type and corresponding filters
    filter_type = filters.get("filter_type", "Date Range")
    
    frappe.logger().debug(f"Filter Type: {filter_type}")
    frappe.logger().debug(f"All Filters: {filters}")
    
    if filter_type == "Date Range":
        from_date = filters.get("from_date")
        to_date = filters.get("to_date")
        
        if not from_date or not to_date:
            frappe.throw(_("Please select From Date and To Date for Date Range filter"))
        
        # Ensure fiscal year filters have some value (won't be used but prevents errors)
        if not filters.get("from_fiscal_year"):
            filters["from_fiscal_year"] = frappe.db.get_value("Fiscal Year", {}, "name")
        if not filters.get("to_fiscal_year"):
            filters["to_fiscal_year"] = filters["from_fiscal_year"]
        
        # Debug: Log the date range
        frappe.logger().debug(f"Date Range Mode: {from_date} to {to_date}")
    else:  # Fiscal Year
        from_fiscal_year = filters.get("from_fiscal_year")
        to_fiscal_year = filters.get("to_fiscal_year")
        
        if not from_fiscal_year or not to_fiscal_year:
            frappe.throw(_("Please select From Fiscal Year and To Fiscal Year for Fiscal Year filter"))
        
        # Ensure date filters have some value (won't be used but prevents errors)
        if not filters.get("from_date"):
            filters["from_date"] = frappe.utils.nowdate()
        if not filters.get("to_date"):
            filters["to_date"] = frappe.utils.nowdate()
        
        frappe.logger().debug(f"Fiscal Year Mode: {from_fiscal_year} to {to_fiscal_year}")
    
    columns = get_columns(filters)
    
    if filters.get("budget_against_filter"):
        dimensions = filters.get("budget_against_filter")
    else:
        dimensions = get_cost_centers(filters)
    
    # Debug: Log dimensions
    frappe.logger().debug(f"Dimensions: {dimensions}")

    # Get period ranges based on filter type
    if filter_type == "Date Range":
        period_ranges = get_period_date_ranges_from_dates(filters)
        frappe.logger().debug(f"Period Ranges: {period_ranges}")
    else:
        period_ranges = get_period_month_ranges(filters["period"], filters["from_fiscal_year"])
    
    cam_map = get_dimension_account_month_map(filters)
    frappe.logger().debug(f"CAM Map dimensions: {list(cam_map.keys())}")
    for dim in cam_map:
        frappe.logger().debug(f"  {dim}: {len(cam_map[dim])} accounts")
    
    all_expense_accounts = get_all_expense_accounts(filters)
    frappe.logger().debug(f"Total Expense Accounts: {len(all_expense_accounts)}")

    data = []
    for dimension in dimensions:
        dimension_items = cam_map.get(dimension)
        frappe.logger().debug(f"Processing dimension {dimension}")
        if dimension_items:
            frappe.logger().debug(f"  Accounts with data: {list(dimension_items.keys())[:5]}...")  # Show first 5
        
        data = get_final_data_for_dimension(
            dimension, 
            dimension_items, 
            all_expense_accounts,
            filters, 
            period_ranges, 
            data, 
            0, 
            actual_only=True
        )

    frappe.logger().debug(f"Total data rows: {len(data)}")
    if data:
        frappe.logger().debug(f"Sample row: {data[0]}")
    
    chart = get_chart_data(filters, columns, data, actual_only=True)

    return columns, data, None, chart


def get_period_date_ranges_from_dates(filters):
    """Generate period ranges based on from_date and to_date"""
    from_date = getdate(filters.get("from_date"))
    to_date = getdate(filters.get("to_date"))
    period = filters.get("period", "Monthly")
    
    date_ranges = []
    
    if period == "Monthly":
        current_date = from_date.replace(day=1)  # Start from first day of month
        while current_date <= to_date:
            month_end = get_last_day_of_month(current_date)
            # Adjust to actual from_date and to_date boundaries
            period_start = max(current_date, from_date)
            period_end = min(month_end, to_date)
            date_ranges.append((period_start, period_end))
            current_date = add_months(current_date, 1)
            
    elif period == "Quarterly":
        current_date = from_date
        while current_date <= to_date:
            quarter_end = add_months(current_date, 3) - relativedelta(days=1)
            if quarter_end > to_date:
                quarter_end = to_date
            date_ranges.append((current_date, quarter_end))
            current_date = add_months(current_date, 3)
            
    elif period == "Half-Yearly":
        current_date = from_date
        while current_date <= to_date:
            half_year_end = add_months(current_date, 6) - relativedelta(days=1)
            if half_year_end > to_date:
                half_year_end = to_date
            date_ranges.append((current_date, half_year_end))
            current_date = add_months(current_date, 6)
            
    elif period == "Yearly":
        # For Yearly, create one range per calendar year in the date range
        current_year = from_date.year
        end_year = to_date.year
        
        while current_year <= end_year:
            year_start = datetime.date(current_year, 1, 1)
            year_end = datetime.date(current_year, 12, 31)
            
            # Adjust to actual from_date and to_date boundaries
            period_start = max(year_start, from_date)
            period_end = min(year_end, to_date)
            
            date_ranges.append((period_start, period_end))
            current_year += 1
    
    return date_ranges


def get_last_day_of_month(date):
    """Get the last day of the month for a given date"""
    next_month = add_months(date, 1)
    return getdate(next_month) - relativedelta(days=next_month.day)


def get_final_data_for_dimension(
    dimension, 
    dimension_items, 
    all_expense_accounts,
    filters, 
    period_ranges, 
    data, 
    DCC_allocation, 
    actual_only=False
):
    filter_type = filters.get("filter_type", "Date Range")
    accounts_processed = 0
    accounts_with_data = 0
    
    # For BOTH modes, show all expense accounts (even those with no data)
    for account in all_expense_accounts:
        accounts_processed += 1
        monthwise_data = dimension_items.get(account) if dimension_items else None
        
        if monthwise_data:
            accounts_with_data += 1
            data = get_final_data_row(
                dimension, 
                account, 
                monthwise_data, 
                filters, 
                period_ranges, 
                data, 
                DCC_allocation, 
                actual_only
            )
        else:
            # Create dummy data for accounts with no GL entries
            dummy_monthwise_data = {}
            
            if filter_type == "Date Range":
                # Create zero-filled data for each period in date range
                for period_start, period_end in period_ranges:
                    period_key = f"{period_start}_{period_end}"
                    dummy_monthwise_data[period_key] = frappe._dict({
                        "target": 0.0, 
                        "actual": 0.0,
                        "variance": 0.0
                    })
            else:  # Fiscal Year
                # Create zero-filled data for each month in fiscal year
                for year in get_fiscal_years(filters):
                    for month_range in period_ranges:
                        for month in month_range:
                            dummy_monthwise_data.setdefault(year[0], {})[month] = frappe._dict({
                                "target": 0.0, 
                                "actual": 0.0,
                                "variance": 0.0
                            })
            
            data = get_final_data_row(
                dimension, 
                account, 
                dummy_monthwise_data, 
                filters, 
                period_ranges, 
                data, 
                DCC_allocation, 
                actual_only
            )
    
    frappe.logger().debug(f"Dimension {dimension}: Processed {accounts_processed} accounts, {accounts_with_data} had data")
    return data


def get_final_data_row(dimension, account, period_data_map, filters, period_ranges, data, DCC_allocation, actual_only=False):
    filter_type = filters.get("filter_type", "Date Range")
    row = [dimension, account]
    totals = [0, 0, 0]  # totals[0]=Budget, totals[1]=Actual, totals[2]=Variance
    
    fieldnames_to_process = ["target", "actual", "variance"]
    last_total = 0
    
    if filter_type == "Date Range":
        # Date Range Logic
        for period_start, period_end in period_ranges:
            period_data = [0, 0, 0]
            period_key = f"{period_start}_{period_end}"
            period_info = period_data_map.get(period_key, frappe._dict({"target": 0.0, "actual": 0.0, "variance": 0.0}))
            
            for i, fieldname in enumerate(fieldnames_to_process):
                value = flt(period_info.get(fieldname, 0))
                period_data[i] += value
                totals[i] += value
            
            period_data[0] += last_total
            
            if DCC_allocation:
                period_data[0] = period_data[0] * (DCC_allocation / 100)
                period_data[1] = period_data[1] * (DCC_allocation / 100)
            
            if filters.get("show_cumulative"):
                last_total = period_data[0] - period_data[1]
            
            period_data[2] = period_data[0] - period_data[1]
            
            if actual_only:
                row.append(period_data[1])
            else:
                row += period_data
    else:
        # Fiscal Year Logic
        for year in get_fiscal_years(filters):
            for relevant_months in period_ranges:
                period_data = [0, 0, 0]
                
                for month in relevant_months:
                    if period_data_map.get(year[0]):
                        month_data = period_data_map.get(year[0]).get(month, {})
                        
                        for i, fieldname in enumerate(fieldnames_to_process):
                            value = flt(month_data.get(fieldname))
                            period_data[i] += value
                            totals[i] += value
                
                period_data[0] += last_total
                
                if DCC_allocation:
                    period_data[0] = period_data[0] * (DCC_allocation / 100)
                    period_data[1] = period_data[1] * (DCC_allocation / 100)
                
                if filters.get("show_cumulative"):
                    last_total = period_data[0] - period_data[1]
                
                period_data[2] = period_data[0] - period_data[1]
                
                if actual_only:
                    row.append(period_data[1])
                else:
                    row += period_data
    
    totals[2] = totals[0] - totals[1]
    
    # Add total column for non-Yearly periods OR when there are multiple periods
    # In Date Range Yearly mode with multiple years, we still want totals
    if filter_type == "Date Range":
        # For date range, add total if period is not Yearly OR if we have multiple years
        if filters["period"] != "Yearly" or len(period_ranges) > 1:
            if actual_only:
                row.append(totals[1])
            else:
                row += totals
    else:
        # Original fiscal year logic
        if filters["period"] != "Yearly":
            if actual_only:
                row.append(totals[1])
            else:
                row += totals
            
    data.append(row)
    return data


def get_columns(filters):
    filter_type = filters.get("filter_type", "Date Range")
    
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

    if filter_type == "Date Range":
        # Date Range Columns
        period_date_ranges = get_period_date_ranges_from_dates(filters)
        
        for from_date, to_date in period_date_ranges:
            if filters["period"] == "Yearly":
                # For yearly, show the year
                year = from_date.year
                label = _("Actual") + f" {year}"
            else:
                if filters["period"] in ["Quarterly", "Half-Yearly"]:
                    label = _("Actual") + f" ({formatdate(from_date, format_string='MMM')}-{formatdate(to_date, format_string='MMM')})"
                else:
                    label = _("Actual") + f" ({formatdate(from_date, format_string='MMM YYYY')})"
            
            columns.append(
                {"label": label, "fieldtype": "Float", "fieldname": frappe.scrub(label), "width": 150}
            )
    else:
        # Fiscal Year Columns
        fiscal_year = get_fiscal_years(filters)
        
        for year in fiscal_year:
            for from_date, to_date in get_period_date_ranges(filters["period"], year[0]):
                if filters["period"] == "Yearly":
                    label = _("Actual") + " " + str(year[0])
                    columns.append(
                        {"label": label, "fieldtype": "Float", "fieldname": frappe.scrub(label), "width": 150}
                    )
                else:
                    label = _("Actual") + " (%s)" + " " + str(year[0])
                    
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

    # Add total column
    if filter_type == "Date Range":
        period_date_ranges = get_period_date_ranges_from_dates(filters)
        # For date range, add total if period is not Yearly OR if we have multiple years
        if filters["period"] != "Yearly" or len(period_date_ranges) > 1:
            columns.append(
                {"label": _("Total Actual"), "fieldtype": "Float", "fieldname": "total_actual", "width": 150}
            )
    else:
        # Original fiscal year logic
        if filters["period"] != "Yearly":
            columns.append(
                {"label": _("Total Actual"), "fieldtype": "Float", "fieldname": "total_actual", "width": 150}
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
        )


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
    
    # Add date range filter if using Date Range mode
    if filters.get("filter_type") == "Date Range":
        if filters.get("from_date"):
            cond += " and gl.posting_date >= %(from_date)s"
        if filters.get("to_date"):
            cond += " and gl.posting_date <= %(to_date)s"
    else:
        # Use fiscal year filter
        cond += " and gl.fiscal_year between %(from_fiscal_year)s and %(to_fiscal_year)s"

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
        "from_fiscal_year": filters.get("from_fiscal_year"),
        "to_fiscal_year": filters.get("to_fiscal_year"),
        "name": name,
        "from_date": filters.get("from_date"),
        "to_date": filters.get("to_date"),
    }
    
    ac_details = frappe.db.sql(
        f"""
            select
                gl.account,
                gl.debit,
                gl.credit,
                gl.fiscal_year,
                MONTHNAME(gl.posting_date) as month_name,
                gl.posting_date,
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
                and gl.is_cancelled = 0
                and b.{budget_against} = %(name)s
                {cond}
            group by
                gl.name
            order by gl.posting_date
        """,
        params,
        as_dict=1,
    )

    cc_actual_details = {}
    for d in ac_details:
        cc_actual_details.setdefault(d.account, []).append(d)

    return cc_actual_details


def get_dimension_account_month_map(filters):
    filter_type = filters.get("filter_type", "Date Range")
    
    if filter_type == "Date Range":
        return get_dimension_account_map_date_range(filters)
    else:
        return get_dimension_account_map_fiscal_year(filters)


def get_dimension_account_map_date_range(filters):
    """Get actual amounts grouped by dimension, account, and period for date range"""
    budget_against = frappe.scrub(filters.get("budget_against"))
    dimensions = filters.get("budget_against_filter") or get_cost_centers(filters)
    
    cam_map = {}
    
    for dimension in dimensions:
        actual_details = get_actual_details_by_period(dimension, filters)
        frappe.logger().debug(f"Actual details for {dimension}: {len(actual_details)} accounts")
        
        if actual_details:
            cam_map[dimension] = actual_details
        else:
            # Even if no GL entries, initialize the dimension in the map
            cam_map[dimension] = {}
    
    return cam_map


def get_actual_details_by_period(name, filters):
    """Fetch GL entries grouped by account and period for date range"""
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
        "from_date": filters.get("from_date"),
        "to_date": filters.get("to_date"),
        "name": name,
        "company": filters.get("company"),
    }
    
    # Get all expense accounts to filter
    gl_entries = frappe.db.sql(
        f"""
            select
                gl.account,
                gl.debit,
                gl.credit,
                gl.posting_date,
                acc.root_type
            from
                `tabGL Entry` gl
            inner join
                `tabAccount` acc on acc.name = gl.account
            where
                gl.{budget_against} = %(name)s
                and gl.posting_date between %(from_date)s and %(to_date)s
                and gl.is_cancelled = 0
                and acc.company = %(company)s
                and acc.root_type = 'Expense'
                and acc.is_group = 0
                {cond}
            order by
                gl.posting_date
        """,
        params,
        as_dict=1,
    )
    
    frappe.logger().debug(f"GL Entries found for {name}: {len(gl_entries)}")
    if gl_entries:
        frappe.logger().debug(f"Sample entry: {gl_entries[0]}")
    
    # Group by account and period
    period_date_ranges = get_period_date_ranges_from_dates(filters)
    account_period_map = {}
    
    for entry in gl_entries:
        account = entry.account
        posting_date = getdate(entry.posting_date)
        amount = flt(entry.debit) - flt(entry.credit)
        
        # Find which period this entry belongs to
        for period_start, period_end in period_date_ranges:
            if period_start <= posting_date <= period_end:
                period_key = f"{period_start}_{period_end}"
                
                if account not in account_period_map:
                    account_period_map[account] = {}
                
                if period_key not in account_period_map[account]:
                    account_period_map[account][period_key] = frappe._dict({
                        "target": 0.0,
                        "actual": 0.0,
                        "variance": 0.0
                    })
                
                account_period_map[account][period_key]["actual"] += amount
                break
    
    return account_period_map


def get_dimension_account_map_fiscal_year(filters):
    """Original fiscal year logic"""
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


def get_chart_data(filters, columns, data, actual_only=False):
    if not data:
        return None

    filter_type = filters.get("filter_type", "Date Range")
    labels = []

    if filter_type == "Date Range":
        # Date Range Labels
        period_date_ranges = get_period_date_ranges_from_dates(filters)
        
        for from_date, to_date in period_date_ranges:
            if filters["period"] == "Yearly":
                labels.append(str(from_date.year))
            else:
                if filters["period"] in ["Quarterly", "Half-Yearly"]:
                    label = f"{formatdate(from_date, format_string='MMM')}-{formatdate(to_date, format_string='MMM')}"
                else:
                    label = formatdate(from_date, format_string="MMM YYYY")
                labels.append(label)
    else:
        # Fiscal Year Labels
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
    data_points_per_period = 1 if actual_only else 3

    budget_values, actual_values = [0] * no_of_columns, [0] * no_of_columns
    
    for d in data:
        values = d[2:]  # Skip dimension and account columns
        index = 0

        for i in range(no_of_columns):
            if actual_only:
                actual_values[i] += values[index]
                index += data_points_per_period
            else:
                budget_values[i] += values[index]
                actual_values[i] += values[index + 1]
                index += data_points_per_period

    return {
        "data": {
            "labels": labels,
            "datasets": [
                {"name": _("Actual Expense"), "chartType": "bar", "values": actual_values},
            ],
        },
        "type": "bar",
    }


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