// Copyright (c) 2025, Samtech and contributors
// For license information, please see license.txt

frappe.query_reports["Expense Analysis"] = {
	filters: get_filters(),
	// --- MODIFICATION START: Use onload to set default filter value ---
	onload: function (report) {
		// Set the fiscal year defaults based on today's date
		let today = frappe.datetime.get_today();
		let current_fiscal_year = erpnext.utils.get_fiscal_year(today);
		report.set_filter_value("from_fiscal_year", current_fiscal_year);
		report.set_filter_value("to_fiscal_year", current_fiscal_year);

		// 1. Get the current default company
		let company = report.get_filter_value("company");

		// 2. Only proceed if the default dimension is Cost Center
		if (report.get_filter_value("budget_against") === "Cost Center") {
			// 3. Fetch the default cost center asynchronously or use a synchronous call
			// Using synchronous call for simplicity in onload, as report filters are ready.
			frappe.call({
				method: "frappe.client.get_value",
				args: {
					doctype: "Company",
					fieldname: "cost_center",
					filters: {
						name: company,
					},
				},
				async: false, // Ensure this completes before moving on
				callback: function (r) {
					if (r.message && r.message.cost_center) {
						let default_cc = r.message.cost_center;

						// 4. Set the value for the MultiSelectList (must be an array)
						// This uses set_filter_value, which correctly updates the UI.
						report.set_filter_value("budget_against_filter", [default_cc]);
					}
				},
			});
		}
	},
	// --- MODIFICATION END ---

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		// NOTE: This formatter targets the 'variance' column which your Python script
		// is currently configured to hide (actual_only=True).
		// If you revert 'actual_only=True' in Python, this formatting will work again.
		if (column.fieldname.includes(__("variance"))) {
			if (data[column.fieldname] < 0) {
				value = "<span style='color:red'>" + value + "</span>";
			} else if (data[column.fieldname] > 0) {
				value = "<span style='color:green'>" + value + "</span>";
			}
		}

		return value;
	},
};
function get_filters() {
	function get_dimensions() {
		let result = [];
		frappe.call({
			method: "erpnext.accounts.doctype.accounting_dimension.accounting_dimension.get_dimensions",
			args: {
				with_cost_center_and_project: true,
			},
			async: false,
			callback: function (r) {
				if (!r.exc) {
					result = r.message[0].map((elem) => elem.document_type);
				}
			},
		});
		return result;
	}

	let budget_against_options = get_dimensions();

	let filters = [
		// --- NEW DATE RANGE FILTERS ADDED ---
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			reqd: 0,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 0,
		},
		// ------------------------------------
		{
			fieldname: "from_fiscal_year",
			label: __("From Fiscal Year"),
			fieldtype: "Link",
			options: "Fiscal Year",
			reqd: 1,
			hidden: 1,
			// Removed default here, setting in onload
		},
		{
			fieldname: "to_fiscal_year",
			label: __("To Fiscal Year"),
			fieldtype: "Link",
			options: "Fiscal Year",
			reqd: 1,
			hidden: 1,
			// Removed default here, setting in onload
		},
		{
			fieldname: "period",
			label: __("Period"),
			fieldtype: "Select",
			options: [
				{ value: "Monthly", label: __("Monthly") },
				{ value: "Quarterly", label: __("Quarterly") },
				{ value: "Half-Yearly", label: __("Half-Yearly") },
				{ value: "Yearly", label: __("Yearly") },
			],
			default: "Yearly",
			reqd: 1,
		},
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "budget_against",
			label: __("Budget Against"),
			fieldtype: "Select",
			options: budget_against_options,
			default: "Cost Center",
			reqd: 1,
			on_change: function () {
				frappe.query_report.set_filter_value("budget_against_filter", []);
				frappe.query_report.refresh();
			},
		},
		{
			fieldname: "budget_against_filter",
			label: __("Dimension Filter"),
			fieldtype: "MultiSelectList",
			options: "budget_against",
			// IMPORTANT: Removed the `default` property here, it is now set in `onload`.
			get_data: function (txt) {
				if (!frappe.query_report.filters) return;

				let budget_against = frappe.query_report.get_filter_value("budget_against");
				if (!budget_against) return;

				return frappe.db.get_link_options(budget_against, txt);
			},
		},
		{
			fieldname: "show_cumulative",
			label: __("Show Cumulative Amount"),
			fieldtype: "Check",
			default: 0,
		},
	];

	return filters;
}
