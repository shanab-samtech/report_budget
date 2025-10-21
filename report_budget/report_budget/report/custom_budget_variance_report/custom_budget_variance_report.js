// Copyright (c) 2025, Samtech and contributors
// For license information, please see license.txt

frappe.query_reports["Custom Budget Variance Report"] = {
	filters: get_filters(),

	onload: function (report) {
		// Hide date filters initially if fiscal year mode is active
		let filter_type = frappe.query_report.get_filter_value("filter_type") || "fiscal_year";
		toggle_filter_fields(filter_type);
	},

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "actual" && data[column.fieldname] < 0) {
			value = `<span style="color:red">${value}</span>`;
		}
		return value;
	},
};

function get_filters() {
	function get_dimensions() {
		let result = [];
		frappe.call({
			method: "erpnext.accounts.doctype.accounting_dimension.accounting_dimension.get_dimensions",
			args: { with_cost_center_and_project: true },
			async: false,
			callback: function (r) {
				if (!r.exc && r.message?.[0]) {
					result = r.message[0].map((elem) => elem.document_type);
				}
			},
		});
		return result;
	}

	let budget_against_options = get_dimensions();

	return [
		{
			fieldname: "filter_type",
			label: __("Filter Type"),
			fieldtype: "Select",
			options: [
				{ label: __("Fiscal Year"), value: "fiscal_year" },
				{ label: __("Date Range"), value: "date_range" },
			],
			default: "fiscal_year",
			reqd: 1,
			on_change: function () {
				let filter_type = frappe.query_report.get_filter_value("filter_type");
				toggle_filter_fields(filter_type);
				frappe.query_report.refresh();
			},
		},
		{
			fieldname: "from_fiscal_year",
			label: __("From Fiscal Year"),
			fieldtype: "Link",
			options: "Fiscal Year",
			default: erpnext.utils.get_fiscal_year(frappe.datetime.get_today()),
			reqd: 1,
		},
		{
			fieldname: "to_fiscal_year",
			label: __("To Fiscal Year"),
			fieldtype: "Link",
			options: "Fiscal Year",
			default: erpnext.utils.get_fiscal_year(frappe.datetime.get_today()),
			reqd: 1,
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			hidden: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			hidden: 1,
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
		},
		{
			fieldname: "budget_against_filter",
			label: __("Dimension Filter"),
			fieldtype: "MultiSelectList",
			get_data: function (txt) {
				let budget_against = frappe.query_report.get_filter_value("budget_against");
				if (!budget_against) return;
				return frappe.db.get_link_options(budget_against, txt);
			},
		},
	];
}

function toggle_filter_fields(filter_type) {
	// Correct logic: show fiscal year fields when fiscal_year is selected
	let show_fy = filter_type === "fiscal_year";

	frappe.query_report.toggle_filter_display("from_fiscal_year", show_fy);
	frappe.query_report.toggle_filter_display("to_fiscal_year", show_fy);
	frappe.query_report.toggle_filter_display("from_date", !show_fy);
	frappe.query_report.toggle_filter_display("to_date", !show_fy);

	// Reset values appropriately
	if (show_fy) {
		frappe.query_report.set_filter_value("from_date", null);
		frappe.query_report.set_filter_value("to_date", null);
	} else {
		frappe.query_report.set_filter_value("from_fiscal_year", null);
		frappe.query_report.set_filter_value("to_fiscal_year", null);
	}
}
