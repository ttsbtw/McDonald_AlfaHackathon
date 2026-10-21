import test from "node:test";
import assert from "node:assert/strict";
import { draftPayload, matchProduct, validateApplication, validateNeed } from "../src/domain/application.js";

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
