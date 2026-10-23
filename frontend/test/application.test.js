import test from "node:test";
import assert from "node:assert/strict";
import { calculateCreditSummary, digitsOnly, draftPayload, matchProduct, normalizeRangeValue, validateApplication, validateNeed } from "../src/domain/application.js";

const product = { code: "equipment", min_amount: "300000.00", max_amount: "10000000.00", min_term_months: 6, max_term_months: 60 };

test("product matching explains success", () => {
  const result = matchProduct(product, { purposeCode: "equipment", amount: "500000", termMonths: "24" });
  assert.equal(result.matches, true);
  assert.equal(result.reasons.length, 3);
});

test("product matching reports every blocker", () => {
  const result = matchProduct(product, { purposeCode: "working_capital", amount: "100000", termMonths: "72" });
  assert.equal(result.matches, false);
  assert.equal(result.blockers.length, 3);
});

test("need validation rejects empty and non-integer values", () => {
  assert.deepEqual(Object.keys(validateNeed({ purposeCode: "", amount: "0", termMonths: "1.5" })).sort(), ["amount", "purposeCode", "termMonths"]);
});

test("draft payload sends money as decimal strings and preserves nulls", () => {
  const result = draftPayload({ product_code: "equipment", requested_amount: "300 000,5", term_months: "12", purpose: "  Станок  ", average_monthly_revenue: "", average_monthly_operating_expenses: "10", existing_monthly_debt_payment: "0" });
  assert.equal(result.requested_amount, "300000.50");
  assert.equal(result.average_monthly_revenue, null);
  assert.equal(result.existing_monthly_debt_payment, "0.00");
  assert.equal(result.purpose, "Станок");
});

test("complete application validation requires financial fields", () => {
  const errors = validateApplication({ product_code: "equipment", requested_amount: "300000", term_months: "12", purpose: "Станок", average_monthly_revenue: "", average_monthly_operating_expenses: "0", existing_monthly_debt_payment: "0" });
  assert.equal(errors.average_monthly_revenue, "Заполните поле");
  assert.equal(errors.average_monthly_operating_expenses, undefined);
});

test("complete application validation rejects an invalid term", () => {
  const errors = validateApplication({ product_code: "equipment", requested_amount: "300000", term_months: "12.5", purpose: "Станок", average_monthly_revenue: "500000", average_monthly_operating_expenses: "250000", existing_monthly_debt_payment: "0" });
  assert.equal(errors.term_months, "Укажите целое число от 1 до 360");
});

test("credit summary calculates annuity payment and total", () => {
  const summary = calculateCreditSummary("300000", "12", "17.5");
  assert.equal(summary.monthlyPayment, 27432.67);
  assert.equal(summary.totalPayment, 329192.04);
  assert.equal(summary.overpayment, 29192.04);
});

test("numeric input removes formatting and non-digits", () => {
  assert.equal(digitsOnly("5 100 000 ₽"), "5100000");
  assert.equal(digitsOnly("abc"), "");
});

test("range input is clamped to the visible boundaries", () => {
  assert.equal(normalizeRangeValue("25 000 000", 300_000, 10_000_000), "10000000");
  assert.equal(normalizeRangeValue("1", 6, 60), "6");
  assert.equal(normalizeRangeValue("", 0, 5_000_000), "");
});

test("application validation follows selected product boundaries", () => {
  const form = { product_code: "equipment", requested_amount: "200000", term_months: "72", purpose: "Станок", average_monthly_revenue: "500000", average_monthly_operating_expenses: "250000", existing_monthly_debt_payment: "0" };
  const errors = validateApplication(form, product);
  assert.match(errors.requested_amount, /300000/);
  assert.match(errors.term_months, /60/);
});

