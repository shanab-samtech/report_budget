// Copyright (c) 2025, Samtech and contributors
// For license information, please see license.txt

frappe.query_reports["Expense Analysis"] = {
	filters: get_filters(),

	onload: function (report) {
		// Set fiscal year defaults on load
		let today = frappe.datetime.get_today();
		let current_fiscal_year = erpnext.utils.get_fiscal_year(today);
		report.set_filter_value("from_fiscal_year", current_fiscal_year);
		report.set_filter_value("to_fiscal_year", current_fiscal_year);

		// Get the current default company
		let company = report.get_filter_value("company");

		// Only proceed if the default dimension is Cost Center
		if (report.get_filter_value("budget_against") === "Cost Center") {
			frappe.call({
				method: "frappe.client.get_value",
				args: {
					doctype: "Company",
					fieldname: "cost_center",
					filters: {
						name: company,
					},
				},
				async: false,
				callback: function (r) {
					if (r.message && r.message.cost_center) {
						let default_cc = r.message.cost_center;
						report.set_filter_value("budget_against_filter", [default_cc]);
					}
				},
			});
		}
	},

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

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
		// Filter Type Selection
		{
			fieldname: "filter_type",
			label: __("Filter Type"),
			fieldtype: "Select",
			options: [
				{ value: "Date Range", label: __("Date Range") },
				{ value: "Fiscal Year", label: __("Fiscal Year") },
			],
			default: "Date Range",
			reqd: 1,
			on_change: function () {
				let filter_type = frappe.query_report.get_filter_value("filter_type");

				// Show/hide filters based on selection
				if (filter_type === "Date Range") {
					frappe.query_report.toggle_filter_display("from_date", false);
					frappe.query_report.toggle_filter_display("to_date", false);
					frappe.query_report.toggle_filter_display("from_fiscal_year", true);
					frappe.query_report.toggle_filter_display("to_fiscal_year", true);
				} else {
					frappe.query_report.toggle_filter_display("from_date", true);
					frappe.query_report.toggle_filter_display("to_date", true);
					frappe.query_report.toggle_filter_display("from_fiscal_year", false);
					frappe.query_report.toggle_filter_display("to_fiscal_year", false);

					// Set default fiscal year
					let today = frappe.datetime.get_today();
					let current_fiscal_year = erpnext.utils.get_fiscal_year(today);
					frappe.query_report.set_filter_value("from_fiscal_year", current_fiscal_year);
					frappe.query_report.set_filter_value("to_fiscal_year", current_fiscal_year);
				}

				frappe.query_report.refresh();
			},
		},
		// Date Range Filters
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			depends_on: "eval:doc.filter_type=='Date Range'",
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			depends_on: "eval:doc.filter_type=='Date Range'",
		},
		// Fiscal Year Filters
		{
			fieldname: "from_fiscal_year",
			label: __("From Fiscal Year"),
			fieldtype: "Link",
			options: "Fiscal Year",
			depends_on: "eval:doc.filter_type=='Fiscal Year'",
		},
		{
			fieldname: "to_fiscal_year",
			label: __("To Fiscal Year"),
			fieldtype: "Link",
			options: "Fiscal Year",
			depends_on: "eval:doc.filter_type=='Fiscal Year'",
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
			default: "Monthly",
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
