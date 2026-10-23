export const PURPOSES = [
  { value: "working_capital", label: "Пополнить оборотные средства", hint: "Закупки, текущие расходы и сезонный рост" },
  { value: "equipment", label: "Купить оборудование", hint: "Техника, оснащение и модернизация бизнеса" },
  { value: "other", label: "Другая бизнес-цель", hint: "Опишите задачу своими словами" },
];

export const STATUS_LABELS = {
  DRAFT: "Черновик",
  SUBMITTED: "Отправлена",
  UNDER_REVIEW: "На рассмотрении",
  NEEDS_INFO: "Нужны сведения",
  APPROVED: "Одобрена",
  REJECTED: "Отказ",
};

const toNumber = (value) => Number(String(value ?? "").replace(/\s/g, ""));

export function digitsOnly(value) {
  return String(value ?? "").replace(/\D/g, "");
}

export function normalizeRangeValue(value, min, max) {
  const digits = digitsOnly(value);
  if (!digits) return "";
  const number = Number(digits);
  if (!Number.isFinite(number)) return "";
  return String(Math.min(Number(max), Math.max(Number(min), number)));
}

export function calculateCreditSummary(amountValue, termValue, annualRateValue) {
  const amount = toNumber(amountValue);
  const term = toNumber(termValue);
  const annualRate = Number(annualRateValue);
  if (!Number.isFinite(amount) || amount <= 0 || !Number.isInteger(term) || term <= 0
      || !Number.isFinite(annualRate) || annualRate < 0) return null;
  const monthlyRate = annualRate / 1200;
  const rawPayment = monthlyRate === 0
    ? amount / term
    : amount * monthlyRate / (1 - (1 + monthlyRate) ** -term);
  const monthlyPayment = Math.ceil(rawPayment * 100) / 100;
  const totalPayment = Math.round(monthlyPayment * term * 100) / 100;
  return {
    monthlyPayment,
    totalPayment,
    overpayment: Math.max(0, Math.round((totalPayment - amount) * 100) / 100),
  };
}

export function matchProduct(product, need) {
  const amount = toNumber(need.amount);
  const term = toNumber(need.termMonths);
  const reasons = [];
  const blockers = [];

  if (Number.isFinite(amount)) {
    const min = toNumber(product.min_amount);
    const max = toNumber(product.max_amount);
    if (amount < min || amount > max) blockers.push(`Сумма должна быть от ${min} до ${max} ₽`);
    else reasons.push("Сумма входит в диапазон продукта");
  }
  if (Number.isFinite(term)) {
    if (term < product.min_term_months || term > product.max_term_months) {
      blockers.push(`Срок должен быть от ${product.min_term_months} до ${product.max_term_months} мес.`);
    } else reasons.push("Подходит по сроку");
  }
  if (need.purposeCode && need.purposeCode !== "other") {
    if (product.code === need.purposeCode) reasons.push("Соответствует указанной цели");
    else blockers.push("Продукт предназначен для другой цели");
  }
  return { matches: blockers.length === 0, reasons, blockers };
}

export function validateNeed(need) {
  const errors = {};
  const amount = toNumber(need.amount);
  const term = toNumber(need.termMonths);
  if (!need.purposeCode) errors.purposeCode = "Выберите цель финансирования";
  if (!Number.isFinite(amount) || amount <= 0) errors.amount = "Укажите сумму больше нуля";
  if (!Number.isInteger(term) || term < 1 || term > 360) errors.termMonths = "Укажите срок от 1 до 360 месяцев";
  return errors;
}

export function validateApplication(form, product = null) {
  const errors = {};
  for (const field of ["product_code", "requested_amount", "term_months", "purpose",
    "average_monthly_revenue", "average_monthly_operating_expenses", "existing_monthly_debt_payment"]) {
    if (form[field] === "" || form[field] === null || form[field] === undefined) errors[field] = "Заполните поле";
  }
  for (const field of ["requested_amount", "average_monthly_revenue", "average_monthly_operating_expenses", "existing_monthly_debt_payment"]) {
    const value = toNumber(form[field]);
    if (form[field] !== "" && (!Number.isFinite(value) || value < 0)) errors[field] = "Введите неотрицательную сумму";
  }
  if (toNumber(form.requested_amount) === 0) errors.requested_amount = "Сумма кредита должна быть больше нуля";
  const term = toNumber(form.term_months);
  if (form.term_months !== "" && (!Number.isInteger(term) || term < 1 || term > 360)) {
    errors.term_months = "Укажите целое число от 1 до 360";
  }
  if (product && !errors.requested_amount) {
    const min = toNumber(product.min_amount);
    const max = toNumber(product.max_amount);
    const amount = toNumber(form.requested_amount);
    if (amount < min || amount > max) {
      errors.requested_amount = `Укажите сумму от ${min} до ${max} ₽`;
    }
  }
  if (product && !errors.term_months) {
    const min = Number(product.min_term_months);
    const max = Number(product.max_term_months);
    if (term < min || term > max) {
      errors.term_months = `Укажите срок от ${min} до ${max} месяцев`;
    }
  }
  return errors;
}

export function moneyForApi(value) {
  if (value === "" || value === null || value === undefined) return null;
  const normalized = String(value).replace(/\s/g, "").replace(",", ".");
  const number = Number(normalized);
  return Number.isFinite(number) ? number.toFixed(2) : normalized;
}

export function draftPayload(form) {
  return {
    product_code: form.product_code || null,
    requested_amount: moneyForApi(form.requested_amount),
    term_months: form.term_months === "" ? null : Number(form.term_months),
    purpose: form.purpose?.trim() || null,
    average_monthly_revenue: moneyForApi(form.average_monthly_revenue),
    average_monthly_operating_expenses: moneyForApi(form.average_monthly_operating_expenses),
    existing_monthly_debt_payment: moneyForApi(form.existing_monthly_debt_payment),
  };
}
