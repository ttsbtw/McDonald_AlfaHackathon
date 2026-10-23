import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, api } from "../api/client.js";
import { Alert, Button, EmptyState, Field, Skeleton, StatusBadge, Toast } from "../components/UI.jsx";
import { PURPOSES, calculateCreditSummary, digitsOnly, draftPayload, matchProduct, normalizeRangeValue, validateApplication, validateNeed } from "../domain/application.js";
import { SliderInput } from "@alfalab/core-components-slider-input";

const emptyForm = {
  product_code: "", requested_amount: "", term_months: "", purpose: "",
  average_monthly_revenue: "0", average_monthly_operating_expenses: "0", existing_monthly_debt_payment: "0",
};
const FINANCIAL_MAX = 10_000_000;
const DEBT_PAYMENT_MAX = 5_000_000;

function withFinancialDefaults(values = {}) {
  return {
    ...emptyForm,
    ...values,
    average_monthly_revenue: values.average_monthly_revenue ?? "0",
    average_monthly_operating_expenses: values.average_monthly_operating_expenses ?? "0",
    existing_monthly_debt_payment: values.existing_monthly_debt_payment ?? "0",
  };
}

function formatMoney(value) {
  if (value === null || value === undefined || value === "" || !Number.isFinite(Number(value))) return "—";
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(Number(value)) + " ₽";
}

function formatPercent(value) {
  if (value === null || value === undefined || value === "" || !Number.isFinite(Number(value))) return "—";
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(value) * 100)}%`;
}

function hasChangedApprovedTerms(application) {
  if (application?.approved_amount === null || application?.approved_amount === undefined) return false;
  return Number(application.approved_amount) !== Number(application.requested_amount)
    || Number(application.approved_term_months) !== Number(application.term_months);
}

function formatCompactMoney(value) {
  if (value >= 1_000_000) return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(value / 1_000_000)} млн ₽`;
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(value / 1_000)} тыс. ₽`;
}

function formatInputNumber(value) {
  if (value === "" || value === null || value === undefined) return "";
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(Number(value));
}

function formatTerm(value) {
  if (value < 12) return `${value} мес.`;
  const years = Math.floor(value / 12);
  const months = value % 12;
  const yearsLabel = years === 1 ? "год" : years < 5 ? "года" : "лет";
  return months ? `${years} ${yearsLabel} ${months} мес.` : `${years} ${yearsLabel}`;
}

function getCreditHints(form, product) {
  const number = (value) => {
    if (value === "" || value === null || value === undefined) return null;
    const parsed = Number(String(value).replace(/\s/g, "").replace(",", "."));
    return Number.isFinite(parsed) ? parsed : null;
  };
  const hints = [];
  const amount = number(form.requested_amount);
  const term = number(form.term_months);
  const revenue = number(form.average_monthly_revenue);
  const expenses = number(form.average_monthly_operating_expenses);
  const existingDebt = number(form.existing_monthly_debt_payment);
  const percent = (value) => `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(value * 100)}%`;

  if (product && amount !== null && (amount < Number(product.min_amount) || amount > Number(product.max_amount))) {
    hints.push({ severity: "warning", title: "Проверьте сумму кредита", text: `Для этого кредита можно запросить от ${formatMoney(product.min_amount)} до ${formatMoney(product.max_amount)}. Измените сумму, чтобы продолжить.` });
  }
  if (product && term !== null && (term < product.min_term_months || term > product.max_term_months)) {
    hints.push({ severity: "warning", title: "Проверьте срок кредита", text: `Для этого кредита срок может быть от ${product.min_term_months} до ${product.max_term_months} месяцев. Измените срок, чтобы продолжить.` });
  }

  if (revenue !== null && expenses !== null && revenue > 0) {
    const operatingProfit = revenue - expenses;
    const margin = operatingProfit / revenue;
    if (operatingProfit <= 0) {
      hints.push({ severity: "critical", title: "Проверьте выручку и расходы", text: "Сейчас расходы не меньше выручки. При таких цифрах банку будет сложно одобрить кредит. Проверьте, правильно ли указали суммы." });
    } else if (margin < 0.15) {
      hints.push({ severity: "warning", title: "После расходов остаётся мало денег", text: `По вашим данным, после расходов остаётся ${percent(margin)} выручки. Чем больше денег остаётся бизнесу, тем проще ему выплачивать кредит.` });
    }

    if (operatingProfit > 0 && amount > 0 && Number.isInteger(term) && term > 0 && existingDebt !== null && product?.annual_interest_rate !== undefined) {
      const monthlyRate = Number(product.annual_interest_rate) / 1200;
      const payment = monthlyRate === 0
        ? amount / term
        : amount * monthlyRate / (1 - (1 + monthlyRate) ** -term);
      const burden = (existingDebt + payment) / operatingProfit;
      // Both current demo products use the same 70% hard limit in backend policy.
      if (burden > 0.7) {
        hints.push({ severity: "critical", title: "Платёж по кредиту может быть тяжёлым", text: `С учётом нового кредита выплаты займут около ${percent(burden)} денег, которые остаются после расходов. При таких цифрах кредит сложно одобрить. Можно попробовать запросить меньшую сумму или выбрать более долгий срок.` });
      } else if (burden > 0.5) {
        hints.push({ severity: "warning", title: "Выплаты могут быть высокими", text: `С учётом нового кредита выплаты займут около ${percent(burden)} денег, которые остаются после расходов. Это может повлиять на решение. Меньшая сумма или более долгий срок снизят ежемесячный платёж.` });
      }
    }
  }
  return hints;
}

function NeedStep({ products, initial, onChange, onBack, onContinue }) {
  const [need, setNeed] = useState(initial || { purposeCode: "", amount: "1000000", termMonths: "24" });
  const [errors, setErrors] = useState({});
  const [searched, setSearched] = useState(false);
  const [focusedRange, setFocusedRange] = useState("");
  const matches = useMemo(() => products.map((product) => ({ product, fit: matchProduct(product, need) })), [products, need]);
  const amountMin = products.length ? Math.min(...products.map((product) => Number(product.min_amount))) : 300_000;
  const amountMax = products.length ? Math.max(...products.map((product) => Number(product.max_amount))) : 10_000_000;
  const termMin = products.length ? Math.min(...products.map((product) => product.min_term_months)) : 6;
  const termMax = products.length ? Math.max(...products.map((product) => product.max_term_months)) : 60;
  const amountMid = Math.round((amountMin + amountMax) / 2 / 50_000) * 50_000;
  const termMid = Math.round((termMin + termMax) / 2);
  const sliderValue = (value, min, max) => Math.min(max, Math.max(min, Number(value) || min));
  function updateNeed(next) { setNeed(next); onChange?.(next); }
  function updateRange(field, value) {
    updateNeed({ ...need, [field]: digitsOnly(value) });
    setErrors((current) => ({ ...current, [field]: undefined }));
  }
  function finishRange(field, min, max) {
    updateNeed({ ...need, [field]: normalizeRangeValue(need[field], min, max) });
    setFocusedRange("");
  }

  function search(event) {
    event?.preventDefault();
    const next = validateNeed(need); setErrors(next); setSearched(Object.keys(next).length === 0);
  }
  return <div className="content content--wide">
    <button className="back-link" onClick={onBack}>← К заявкам</button>
    <div className="page-heading"><div><span className="eyebrow eyebrow--red">Шаг 1 из 2</span><h1>Что нужно вашему бизнесу?</h1><p>Ответьте на три вопроса — покажем продукты, которые подходят по открытым условиям.</p></div><span className="big-number">01</span></div>
    <form className="need-grid" onSubmit={search}>
      <section className="panel panel--form">
        <h2>Цель финансирования</h2>
        <div className="purpose-grid">{PURPOSES.map((purpose) => <button type="button" key={purpose.value} className={`purpose-card ${need.purposeCode === purpose.value ? "is-selected" : ""}`} onClick={() => { updateNeed({ ...need, purposeCode: purpose.value }); setErrors((current) => ({ ...current, purposeCode: undefined })); }}><i /><strong>{purpose.label}</strong><span>{purpose.hint}</span></button>)}</div>
        {errors.purposeCode && <span className="form-error">{errors.purposeCode}</span>}
        <div className="need-ranges">
          <div className="need-range">
            <SliderInput
              className="need-range__control"
              label="Сумма кредита"
              value={focusedRange === "amount" ? need.amount : formatInputNumber(need.amount)}
              sliderValue={sliderValue(need.amount, amountMin, amountMax)}
              min={amountMin}
              max={amountMax}
              step={50_000}
              size={64}
              client="desktop"
              rightAddons="₽"
              steps={[formatCompactMoney(amountMin), formatCompactMoney(amountMid), formatCompactMoney(amountMax)]}
              onChange={(_, payload) => updateRange("amount", payload.value)}
              onFocus={() => setFocusedRange("amount")}
              onBlur={() => finishRange("amount", amountMin, amountMax)}
              dataTestId="credit-amount-slider"
            />
            {errors.amount && <span className="form-error">{errors.amount}</span>}
          </div>
          <div className="need-range">
            <SliderInput
              className="need-range__control"
              label="Срок кредита"
              value={focusedRange === "termMonths" ? need.termMonths : formatInputNumber(need.termMonths)}
              sliderValue={sliderValue(need.termMonths, termMin, termMax)}
              min={termMin}
              max={termMax}
              step={1}
              size={64}
              client="desktop"
              rightAddons="мес."
              steps={[formatTerm(termMin), formatTerm(termMid), formatTerm(termMax)]}
              onChange={(_, payload) => updateRange("termMonths", payload.value)}
              onFocus={() => setFocusedRange("termMonths")}
              onBlur={() => finishRange("termMonths", termMin, termMax)}
              dataTestId="credit-term-slider"
            />
            {errors.termMonths && <span className="form-error">{errors.termMonths}</span>}
          </div>
        </div>
        <Button type="submit" onClick={search}>Подобрать продукты</Button>
      </section>
      <aside className="need-aside"><div className="metric"><span>до</span><b>10 млн ₽</b><small>в демонстрационных продуктах</small></div><div className="metric"><span>решение</span><b>прозрачно</b><small>покажем причины рекомендации</small></div></aside>
    </form>
    {searched && <section className="results"><div className="section-title"><div><span className="eyebrow">Результат подбора</span><h2>{matches.filter(({ fit }) => fit.matches).length ? "Нашли подходящие варианты" : "Точного совпадения нет"}</h2></div><span>{matches.filter(({ fit }) => fit.matches).length} из {matches.length}</span></div>
      <div className="product-grid">{matches.map(({ product, fit }) => <article key={product.code} className={`product-card ${fit.matches ? "product-card--fit" : "product-card--muted"}`}><div className="product-card__top"><span>{fit.matches ? "Подходит" : "Не подходит"}</span><b>{product.annual_interest_rate}%*</b></div><h3>{product.name}</h3><p>{product.description}</p><dl><div><dt>Сумма</dt><dd>{formatMoney(product.min_amount)} — {formatMoney(product.max_amount)}</dd></div><div><dt>Срок</dt><dd>{product.min_term_months}–{product.max_term_months} мес.</dd></div></dl><ul>{(fit.matches ? fit.reasons : fit.blockers).map((text) => <li key={text}>{text}</li>)}</ul>{fit.matches && <Button onClick={() => onContinue(need, product)}>Выбрать продукт</Button>}<small>{product.rate_note}</small></article>)}</div>
    </section>}
  </div>;
}

function Editor({ application, product, company, need, formSnapshot, onFormChange, onClose, onSaved, onDeleted, onToast }) {
  const [form, setForm] = useState(() => withFinancialDefaults(formSnapshot || (application ? application : {
    product_code: product?.code || "", requested_amount: need?.amount || product?.min_amount || "", term_months: need?.termMonths || product?.min_term_months || "",
    purpose: PURPOSES.find((item) => item.value === need?.purposeCode)?.label || "",
  })));
  const [saved, setSaved] = useState(application || null);
  const [errors, setErrors] = useState({});
  const [notice, setNotice] = useState("");
  const [noticeType, setNoticeType] = useState("info");
  const [busy, setBusy] = useState(false);
  const [focusedRange, setFocusedRange] = useState("");
  const [infoRequest, setInfoRequest] = useState({ loading: false, error: "", message: "" });
  const [alternativeOffer, setAlternativeOffer] = useState(null);
  const [alternativeError, setAlternativeError] = useState("");
  const [alternativeBusy, setAlternativeBusy] = useState(false);
  const [creditHistoryConsent, setCreditHistoryConsent] = useState(false);
  const [history, setHistory] = useState({ loading: false, error: "", items: [] });
  const status = saved?.status;
  const readOnly = ["SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED"].includes(status);
  const finalDecision = ["APPROVED", "REJECTED"].includes(status);
  const approvedDecision = status === "APPROVED";
  const heading = finalDecision
    ? { eyebrow: "Этап 3 из 3", title: "Решение по заявке", number: "03" }
    : status === "UNDER_REVIEW" || status === "SUBMITTED"
      ? { eyebrow: "Этап 3 из 3", title: "Заявка на рассмотрении", number: "03" }
      : status === "NEEDS_INFO"
        ? { eyebrow: "Требуется уточнение", title: "Дополните заявку", number: "02" }
        : { eyebrow: "Шаг 2 из 2", title: saved ? "Заявка" : "Расскажите о бизнесе", number: "02" };
  const creditHints = useMemo(() => getCreditHints(form, product), [form, product]);
  const amountMin = Number(product?.min_amount ?? 300_000);
  const amountMax = Number(product?.max_amount ?? 10_000_000);
  const termMin = Number(product?.min_term_months ?? 6);
  const termMax = Number(product?.max_term_months ?? 60);
  const sliderValue = (value, min, max) => Math.min(max, Math.max(min, Number(value) || min));
  const displayedAmount = approvedDecision && saved?.approved_amount != null
    ? saved.approved_amount : form.requested_amount;
  const displayedTerm = approvedDecision && saved?.approved_term_months != null
    ? saved.approved_term_months : form.term_months;
  const displayedRate = approvedDecision && saved?.approved_annual_interest_rate != null
    ? saved.approved_annual_interest_rate : product?.annual_interest_rate;
  const creditSummary = useMemo(() => calculateCreditSummary(
    displayedAmount,
    displayedTerm,
    displayedRate,
  ), [displayedAmount, displayedTerm, displayedRate]);

  useEffect(() => {
    if (["NEEDS_INFO", "APPROVED", "REJECTED"].includes(status)) setNotice("");
  }, [status]);

  useEffect(() => {
    if (!saved?.id) {
      setInfoRequest({ loading: false, error: "", message: "" });
      setHistory({ loading: false, error: "", items: [] });
      return;
    }
    let active = true;
    setHistory((current) => ({ ...current, loading: true, error: "" }));
    api.applicationEvents(saved.id)
      .then((events) => {
        if (!active) return;
        setHistory({ loading: false, error: "", items: events });
        const eventType = status === "NEEDS_INFO" ? "INFO_REQUESTED" : "REJECTED";
        const latestEvent = [...events].reverse().find((event) => event.event_type === eventType);
        setInfoRequest({ loading: false, error: "", message: latestEvent?.message?.trim() || "" });
      })
      .catch((err) => {
        if (active) {
          setHistory({ loading: false, error: err.message, items: [] });
          setInfoRequest({ loading: false, error: err.message, message: "" });
        }
      });
    return () => { active = false; };
  }, [saved?.id, status, saved?.revision]);

  useEffect(() => {
    if (!saved?.id || ["APPROVED", "REJECTED"].includes(status)) return undefined;
    const refresh = async () => {
      if (document.visibilityState !== "visible") return;
      try {
        const current = await api.application(saved.id);
        if (current.status === "UNDER_REVIEW") {
          const offer = await api.applicationAlternativeOffer(saved.id).catch(() => null);
          setAlternativeOffer(offer);
        }
        if (current.status !== saved.status || current.revision !== saved.revision) {
          setSaved(current);
          setForm(withFinancialDefaults(current));
          onSaved(current);
        }
      } catch {
        // The visible error remains tied to explicit user actions; polling retries automatically.
      }
    };
    const timer = window.setInterval(refresh, 5000);
    return () => window.clearInterval(timer);
  }, [saved?.id, saved?.revision, status]);

  useEffect(() => {
    if (!saved?.id || status !== "UNDER_REVIEW") {
      setAlternativeOffer(null); setAlternativeError("");
      return;
    }
    let active = true;
    api.applicationAlternativeOffer(saved.id)
      .then((offer) => { if (active) { setAlternativeOffer(offer); setAlternativeError(""); } })
      .catch((err) => { if (active) setAlternativeError(err.message); });
    return () => { active = false; };
  }, [saved?.id, status]);

  async function decideAlternative(decision) {
    if (!saved?.id || !alternativeOffer) return;
    setAlternativeBusy(true); setAlternativeError("");
    try {
      const result = await api.decideAlternativeOffer(saved.id, alternativeOffer.id, { decision });
      setAlternativeOffer(result);
    } catch (err) { setAlternativeError(err.message); }
    finally { setAlternativeBusy(false); }
  }

  const set = (field) => (event) => {
    if (readOnly) return;
    const next = { ...form, [field]: event.target.value };
    setForm(next); onFormChange(next);
    setErrors((current) => ({ ...current, [field]: undefined }));
  };
  function updateRange(field, value) {
    if (readOnly) return;
    const next = { ...form, [field]: digitsOnly(value) };
    setForm(next); onFormChange(next);
    setErrors((current) => ({ ...current, [field]: undefined }));
  }
  function finishRange(field, min, max) {
    if (readOnly) return;
    const next = { ...form, [field]: normalizeRangeValue(form[field], min, max) };
    setForm(next); onFormChange(next); setFocusedRange("");
  }
  async function save(event) {
    event?.preventDefault(); if (readOnly) return;
    setBusy(true); setNotice(""); setErrors({});
    try {
      const payload = draftPayload(form);
      const result = saved ? await api.updateApplication(saved.id, { revision: saved.revision, ...payload }) : await api.createApplication(payload);
      setSaved(result); setForm(withFinancialDefaults(result)); setNotice("Черновик сохранён"); setNoticeType("success"); onSaved(result);
    } catch (err) {
      if (err instanceof ApiError && err.fields.length) setErrors(Object.fromEntries(err.fields.map((item) => [item.field.split(".").pop(), item.message])));
      setNotice(err.message); setNoticeType("error");
    } finally { setBusy(false); }
  }
  async function submit() {
    if (readOnly) return;
    const nextErrors = validateApplication(form, product); setErrors(nextErrors); setNotice("");
    if (Object.keys(nextErrors).length) return;
    setBusy(true);
    try {
      let current = saved;
      if (!current) current = await api.createApplication(draftPayload(form));
      else current = await api.updateApplication(current.id, { revision: current.revision, ...draftPayload(form) });
      const result = await api.submitApplication(current.id, { credit_history_consent: creditHistoryConsent });
      setSaved(result); onSaved(result); onToast("Заявка отправлена на рассмотрение");
    } catch (err) {
      if (err.status === 404 || err.status === 405) { setNotice("Не удалось запустить рассмотрение. Черновик сохранён — попробуйте отправить его позже."); setNoticeType("info"); }
      else { setNotice(err.message); setNoticeType("error"); }
    } finally { setBusy(false); }
  }

  async function deleteDraft() {
    if (!saved || saved.status !== "DRAFT" || !window.confirm("Удалить этот черновик? Восстановить его не получится.")) return;
    setBusy(true); setNotice("");
    try {
      await api.deleteApplication(saved.id);
      onDeleted(saved.id);
    } catch (err) {
      setNotice(err.message); setNoticeType("error");
    } finally { setBusy(false); }
  }

  return <div className="content content--form"><button className="back-link" onClick={onClose}>← К заявкам</button><div className="page-heading"><div><span className="eyebrow eyebrow--red">{heading.eyebrow}</span><h1>{heading.title}</h1>{saved && <><StatusBadge status={status} />{alternativeOffer?.status === "OFFERED" && <span className="status status--offer">Нужно ваше решение</span>}</>}<p>{readOnly ? (status === "APPROVED" ? "Заявка одобрена. Ниже сохранены итог и данные отправленной анкеты." : status === "REJECTED" ? "По заявке принято решение об отказе. Ниже сохранены данные отправленной анкеты." : "Заявка отправлена и ожидает решения. Изменения пока недоступны.") : "Известные банку сведения уже заполнены. Добавьте только показатели для оценки."}</p></div><span className="big-number">{heading.number}</span></div>
    {notice && <Alert type={noticeType}>{notice}</Alert>}
    {status === "NEEDS_INFO" && <Alert title="Банк запросил уточнения">{infoRequest.loading ? "Загружаем сообщение сотрудника…" : infoRequest.error ? `Не удалось загрузить сообщение: ${infoRequest.error}` : infoRequest.message || "В истории нет текста запроса. Свяжитесь с сотрудником банка, чтобы уточнить, какие сведения нужно добавить."}</Alert>}
    {status === "REJECTED" && <Alert title="Комментарий банка">{infoRequest.loading ? "Загружаем сообщение сотрудника…" : infoRequest.error ? `Не удалось загрузить сообщение: ${infoRequest.error}` : infoRequest.message || "Сотрудник не добавил комментарий к решению."}</Alert>}
    {status === "UNDER_REVIEW" && alternativeError && <Alert type="error">Не удалось загрузить предложение: {alternativeError}</Alert>}
    {status === "UNDER_REVIEW" && alternativeOffer && <ClientAlternativeCard offer={alternativeOffer} busy={alternativeBusy} onDecision={decideAlternative} />}
    {status === "APPROVED" && hasChangedApprovedTerms(saved) && <ApprovedConditions application={saved} />}
    {saved?.id && <ApplicationTimeline history={history} status={status} />}
    <form className="application-layout" onSubmit={save}>
      <div className="application-main">
        <section className="panel form-section"><div className="form-section__heading"><span>01</span><div><h2>Компания</h2><p>Сведения действующего клиента</p></div></div><div className="company-card"><b>{company.name}</b><span>{company.legal_form} · ИНН {company.inn}</span><small>Работает с {new Date(company.registration_date).toLocaleDateString("ru-RU")}</small></div></section>
        <section className="panel form-section">
          <div className="form-section__heading"><span>02</span><div><h2>Параметры кредита</h2><p>{readOnly ? "Параметры отправленной заявки" : "Можно изменить до отправки"}</p></div></div>
          {readOnly ? <>
            <dl className="facts readonly-facts"><div><dt>Продукт</dt><dd>{product?.name || form.product_code || "—"}</dd></div><div><dt>{approvedDecision ? "Одобренная сумма" : "Сумма"}</dt><dd>{formatMoney(displayedAmount)}</dd></div><div><dt>{approvedDecision ? "Одобренный срок" : "Срок"}</dt><dd>{displayedTerm || "—"} мес.</dd></div></dl>
            {creditSummary && <CreditSummary summary={creditSummary} rate={displayedRate} approved={approvedDecision} />}
            <div className="readonly-copy"><small>Цель финансирования</small><p>{form.purpose || "Не указана"}</p></div>
          </> : <>
            <Field label="Продукт" error={errors.product_code}><input value={product?.name || form.product_code} disabled /></Field>
            <div className="form-row application-ranges"><div className="application-range"><SliderInput className="need-range__control" label="Сумма" value={focusedRange === "amount" ? form.requested_amount : formatInputNumber(form.requested_amount)} sliderValue={sliderValue(form.requested_amount, amountMin, amountMax)} min={amountMin} max={amountMax} step={50_000} size={64} client="desktop" rightAddons="₽" steps={[formatCompactMoney(amountMin), formatCompactMoney(Math.round((amountMin + amountMax) / 2 / 50_000) * 50_000), formatCompactMoney(amountMax)]} error={errors.requested_amount} onChange={(_, payload) => updateRange("requested_amount", payload.value)} onFocus={() => setFocusedRange("amount")} onBlur={() => finishRange("requested_amount", amountMin, amountMax)} dataTestId="application-amount-slider" /></div><div className="application-range"><SliderInput className="need-range__control" label="Срок" value={focusedRange === "term" ? form.term_months : formatInputNumber(form.term_months)} sliderValue={sliderValue(form.term_months, termMin, termMax)} min={termMin} max={termMax} step={1} size={64} client="desktop" rightAddons="мес." steps={[formatTerm(termMin), formatTerm(Math.round((termMin + termMax) / 2)), formatTerm(termMax)]} error={errors.term_months} onChange={(_, payload) => updateRange("term_months", payload.value)} onFocus={() => setFocusedRange("term")} onBlur={() => finishRange("term_months", termMin, termMax)} dataTestId="application-term-slider" /></div></div>
            {creditSummary && <CreditSummary summary={creditSummary} rate={product?.annual_interest_rate} />}
            <Field label="Цель" error={errors.purpose}><textarea rows="3" maxLength="200" value={form.purpose ?? ""} onChange={set("purpose")} /></Field>
          </>}
        </section>
        <section className="panel form-section">
          <div className="form-section__heading"><span>03</span><div><h2>Финансовые показатели</h2><p>Средние значения за последние 12 завершённых месяцев</p></div></div>
          {readOnly ? <><dl className="facts readonly-facts readonly-facts--financial"><div><dt>Выручка в месяц</dt><dd>{formatMoney(form.average_monthly_revenue)}</dd></div><div><dt>Операционные расходы</dt><dd>{formatMoney(form.average_monthly_operating_expenses)}</dd></div><div><dt>Платежи по действующим кредитам</dt><dd>{formatMoney(form.existing_monthly_debt_payment)}</dd></div></dl>{approvedDecision && <p className="approved-financial-note">Выручка, расходы и платежи по действующим кредитам сохранены из анкеты. Платёж по одобренному кредиту рассчитан выше.</p>}</> : <>
            <div className="form-row application-ranges"><div className="application-range"><SliderInput className="need-range__control" label="Выручка в месяц" value={focusedRange === "revenue" ? form.average_monthly_revenue : formatInputNumber(form.average_monthly_revenue)} sliderValue={sliderValue(form.average_monthly_revenue, 0, FINANCIAL_MAX)} min={0} max={FINANCIAL_MAX} step={50_000} size={64} client="desktop" rightAddons="₽" steps={["0 ₽", formatCompactMoney(FINANCIAL_MAX / 2), formatCompactMoney(FINANCIAL_MAX)]} error={errors.average_monthly_revenue} onChange={(_, payload) => updateRange("average_monthly_revenue", payload.value)} onFocus={() => setFocusedRange("revenue")} onBlur={() => finishRange("average_monthly_revenue", 0, FINANCIAL_MAX)} dataTestId="application-revenue-slider" /></div><div className="application-range"><SliderInput className="need-range__control" label="Операционные расходы" hint="Без платежей по кредитам" value={focusedRange === "expenses" ? form.average_monthly_operating_expenses : formatInputNumber(form.average_monthly_operating_expenses)} sliderValue={sliderValue(form.average_monthly_operating_expenses, 0, FINANCIAL_MAX)} min={0} max={FINANCIAL_MAX} step={50_000} size={64} client="desktop" rightAddons="₽" steps={["0 ₽", formatCompactMoney(FINANCIAL_MAX / 2), formatCompactMoney(FINANCIAL_MAX)]} error={errors.average_monthly_operating_expenses} onChange={(_, payload) => updateRange("average_monthly_operating_expenses", payload.value)} onFocus={() => setFocusedRange("expenses")} onBlur={() => finishRange("average_monthly_operating_expenses", 0, FINANCIAL_MAX)} dataTestId="application-expenses-slider" /></div></div>
            <div className="application-range application-range--full"><SliderInput className="need-range__control" label="Ежемесячные платежи по действующим кредитам" value={focusedRange === "debt" ? form.existing_monthly_debt_payment : formatInputNumber(form.existing_monthly_debt_payment)} sliderValue={sliderValue(form.existing_monthly_debt_payment, 0, DEBT_PAYMENT_MAX)} min={0} max={DEBT_PAYMENT_MAX} step={50_000} size={64} client="desktop" rightAddons="₽" steps={["0 ₽", formatCompactMoney(DEBT_PAYMENT_MAX / 2), formatCompactMoney(DEBT_PAYMENT_MAX)]} error={errors.existing_monthly_debt_payment} onChange={(_, payload) => updateRange("existing_monthly_debt_payment", payload.value)} onFocus={() => setFocusedRange("debt")} onBlur={() => finishRange("existing_monthly_debt_payment", 0, DEBT_PAYMENT_MAX)} dataTestId="application-debt-slider" /></div>
            {creditHints.length > 0 && <div className="credit-hints" role="status" aria-live="polite">{creditHints.map((hint) => <article className={`credit-hint credit-hint--${hint.severity}`} key={hint.title}><strong>{hint.title}</strong><span>{hint.text}</span></article>)}<small>Это подсказка, а не решение по кредиту. Банк проверит заявку и сообщит результат.</small></div>}
          </>}
        </section>
      </div>
      <aside className="application-aside"><div className="panel sticky-card">{readOnly ? <><span className="eyebrow">{finalDecision ? "Решение банка" : "Заявка отправлена"}</span><h3>{status === "APPROVED" ? "Кредит одобрен" : status === "REJECTED" ? "Заявка отклонена" : "Заявка на рассмотрении"}</h3><p className="muted">{finalDecision ? "Изменить или отправить эту заявку повторно нельзя." : "Пока заявка рассматривается, редактирование и повторная отправка недоступны."}</p></> : <><span className="eyebrow">Перед отправкой</span><h3>Что произойдёт дальше</h3><ol><li>Проверим полноту анкеты</li><li>Выполним локальные проверки</li><li>Передадим сотруднику банка</li></ol><label className="consent-field"><input type="checkbox" checked={creditHistoryConsent} onChange={(event) => setCreditHistoryConsent(event.target.checked)} /><span>Согласен на запрос синтетической кредитной истории для проверки заявки.</span></label><Button type="submit" variant="secondary" busy={busy}>Сохранить черновик</Button><Button type="button" onClick={submit} busy={busy}>Отправить заявку</Button>{saved?.status === "DRAFT" && <Button type="button" variant="ghost" busy={busy} onClick={deleteDraft}>Удалить черновик</Button>}<small>Без согласия демо-проверка кредитной истории будет отмечена как недоступная. Это может ограничить решение и подбор альтернативных условий.</small></>}</div></aside>
    </form>
  </div>;
}

function CreditSummary({ summary, rate, approved = false }) {
  return <div className="credit-summary" aria-live="polite">
    <div><small>Платёж в месяц</small><strong>{formatMoney(summary.monthlyPayment)}</strong></div>
    <div><small>Всего выплат</small><strong>{formatMoney(summary.totalPayment)}</strong></div>
    <div><small>Переплата</small><strong>{formatMoney(summary.overpayment)}</strong></div>
    <p>{approved ? `Платёж рассчитан по одобренным сумме и сроку, ставка ${rate}% годовых.` : `Расчёт по аннуитетной схеме и ставке ${rate}% годовых. Точные условия определит банк после рассмотрения.`}</p>
  </div>;
}

const eventLabels = {
  DRAFT_CREATED: "Черновик создан",
  DRAFT_UPDATED: "Анкета обновлена",
  SUBMITTED: "Заявка отправлена",
  RESUBMITTED: "Заявка отправлена повторно",
  INFO_REQUESTED: "Банк запросил сведения",
  APPROVED: "Заявка одобрена",
  REJECTED: "По заявке отказ",
  ALTERNATIVE_ACCEPTED: "Альтернативные условия приняты",
  ALTERNATIVE_DECLINED: "Альтернативные условия отклонены",
};

function ApplicationTimeline({ history, status }) {
  return <section className="panel client-timeline">
    <div className="client-timeline__heading"><div><span className="eyebrow eyebrow--red">Путь заявки</span><h2>Статус и история</h2></div><StatusBadge status={status} /></div>
    {history.loading && !history.items.length ? <Skeleton rows={2} /> : history.error ? <Alert type="error">Не удалось загрузить историю: {history.error}</Alert> : history.items.length ? <ol>{history.items.map((event) => <li key={event.id}><i aria-hidden="true" /><div><strong>{eventLabels[event.event_type] || "Статус заявки изменён"}</strong><span>{new Date(event.created_at).toLocaleString("ru-RU")}</span>{event.message && <p>{event.message}</p>}</div></li>)}</ol> : <p className="muted">История появится после сохранения заявки.</p>}
  </section>;
}

function ApprovedConditions({ application }) {
  const requestedAmount = formatMoney(application.requested_amount);
  const requestedTerm = `${application.term_months || "—"} мес.`;
  const approvedAmount = formatMoney(application.approved_amount);
  const approvedTerm = `${application.approved_term_months} мес.`;
  return <section className="panel approval-terms">
    <div className="approval-terms__heading"><span className="eyebrow eyebrow--red">Решение банка</span><h2>Условия одобрения</h2><p>Банк одобрил финансирование на изменённых условиях.</p></div>
    <div className="approval-terms__flow">
      <div className="approval-terms__side approval-terms__side--requested"><small>Запрошено</small><strong><s>{requestedAmount}</s></strong><span><s>{requestedTerm}</s></span></div>
      <span className="approval-terms__arrow" aria-label="Изменено на">→</span>
      <div className="approval-terms__side approval-terms__side--approved"><small>Одобрено</small><strong>{approvedAmount}</strong><span>{approvedTerm}</span><small>Ставка {formatPercent(Number(application.approved_annual_interest_rate) / 100)} годовых</small></div>
    </div>
    <p className="approval-terms__note">Исходная заявка сохранена в истории. Параметры и расчёт платежа ниже соответствуют одобренным условиям.</p>
  </section>;
}

function ClientAlternativeCard({ offer, busy, onDecision }) {
  const pending = offer.status === "OFFERED";
  const title = pending ? "Банк предлагает изменить условия" : offer.status === "ACCEPTED" ? "Вы приняли альтернативные условия" : "Вы отказались от альтернативных условий";
  return <section className="panel client-alternative"><div><span className="eyebrow eyebrow--red">Альтернатива от банка · демо-расчёт</span><h2>{title}</h2><p>{offer.reason}</p></div><dl className="facts"><div><dt>Сумма</dt><dd>{formatMoney(offer.amount)}</dd></div><div><dt>Срок</dt><dd>{offer.term_months} мес.</dd></div><div><dt>Ставка</dt><dd>{formatPercent(Number(offer.annual_interest_rate) / 100)}</dd></div><div><dt>Ежемесячный платёж</dt><dd>{formatMoney(offer.monthly_payment)}</dd></div><div><dt>Долговая нагрузка</dt><dd>{formatPercent(offer.debt_burden)}</dd></div></dl>{pending ? <><p className="muted">Если вы примете вариант, сотрудник банка всё равно должен принять итоговое решение. Исходные параметры заявки не изменятся.</p><div className="client-alternative__actions"><Button busy={busy} onClick={() => onDecision("ACCEPTED")}>Принять условия</Button><Button disabled={busy} variant="secondary" onClick={() => onDecision("DECLINED")}>Отказаться</Button></div></> : <p className="muted">{offer.status === "ACCEPTED" ? "Заявка остаётся на рассмотрении до решения сотрудника банка." : "Банк продолжит рассматривать исходную заявку."}</p>}</section>;
}

function Dashboard({ company, applications, onNew, onOpen }) {
  return <div className="content"><section className="client-hero"><div><span className="eyebrow">Кабинет предпринимателя</span><h1>Здравствуйте,<br />{company.name}</h1><p>Подберите финансирование и следите за решением без звонков и визитов.</p><Button onClick={onNew}>Подобрать финансирование</Button></div><div className="hero-shape" aria-hidden="true"><b>₽</b><i /><i /></div></section>
    <section className="dashboard-section"><div className="section-title"><div><span className="eyebrow eyebrow--red">Мои заявки</span><h2>История финансирования</h2></div><span>{applications.length}</span></div>{applications.length ? <div className="application-list">{applications.map((item) => <button key={item.id} onClick={() => onOpen(item)}><div className="application-list__summary"><span className="application-list__badges"><StatusBadge status={item.status} />{item.has_pending_alternative_offer && <span className="status status--offer">Нужно ваше решение</span>}</span><h3>{item.purpose || "Заявка без названия"}</h3><ApplicationTerms item={item} compact /></div><div><small>Обновлена</small><b>{new Date(item.updated_at).toLocaleDateString("ru-RU")}</b><i>→</i></div></button>)}</div> : <EmptyState icon="₽" title="Заявок пока нет" action={<Button onClick={onNew}>Начать подбор</Button>}>Начните с потребности — сумму, срок и продукт подберём на следующем шаге.</EmptyState>}</section>
  </div>;
}

function ApplicationTerms({ item, compact = false }) {
  const requested = `${formatMoney(item.requested_amount)} · ${item.term_months || "—"} мес.`;
  const hasApproval = hasChangedApprovedTerms(item);
  if (!hasApproval) return <span className="application-terms__plain">{item.status === "APPROVED" ? "Одобрено" : "Запрошено"}: {requested}</span>;

  const approved = `${formatMoney(item.approved_amount)} · ${item.approved_term_months} мес.`;
  return <span className={`application-terms${compact ? " application-terms--compact" : ""}`}>
    <span className="application-terms__requested"><small>Запрошено</small><s>{requested}</s></span>
    <span className="application-terms__arrow" aria-hidden="true">→</span>
    <span className="application-terms__approved"><small>Одобрено</small><strong>{approved}</strong></span>
  </span>;
}

export default function ClientWorkspace({ pathname, navigate }) {
  const [data, setData] = useState(null); const [error, setError] = useState(""); const [selection, setSelection] = useState(null); const [needSnapshot, setNeedSnapshot] = useState(null); const [formSnapshot, setFormSnapshot] = useState(null); const [toast, setToast] = useState(null);
  const showToast = useCallback((message) => setToast({ id: Date.now(), message }), []);
  const dismissToast = useCallback(() => setToast(null), []);
  async function load() { setError(""); try { const [company, products, page] = await Promise.all([api.company(), api.products(), api.applications()]); setData({ company, products, applications: page.items }); } catch (err) { setError(err.message); } }
  useEffect(() => { load(); }, []);
  useEffect(() => {
    const refreshApplications = async () => {
      if (document.visibilityState !== "visible") return;
      try {
        const page = await api.applications();
        setData((current) => current ? { ...current, applications: page.items } : current);
      } catch {
        // Keep the current screen usable; the next refresh can recover.
      }
    };
    const timer = window.setInterval(refreshApplications, 5000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => { if (data && pathname === "/client/new/application" && !selection) navigate("/client/new", { replace: true }); }, [data, pathname, selection, navigate]);
  if (error) return <div className="content"><Alert type="error">{error}</Alert><Button onClick={load}>Повторить</Button></div>;
  if (!data) return <div className="content"><Skeleton rows={5} /></div>;
  if (pathname === "/client/new") return <NeedStep products={data.products} initial={needSnapshot} onChange={setNeedSnapshot} onBack={() => navigate("/client", { replace: true })} onContinue={(need, product) => { setNeedSnapshot(need); setSelection({ need, product }); navigate("/client/new/application"); }} />;
  if (pathname === "/client/new/application" && !selection) return <NeedStep products={data.products} initial={needSnapshot} onChange={setNeedSnapshot} onBack={() => navigate("/client", { replace: true })} onContinue={(need, product) => { setNeedSnapshot(need); setSelection({ need, product }); navigate("/client/new/application"); }} />;
  const applicationMatch = pathname.match(/^\/client\/applications\/([^/]+)$/);
  const application = applicationMatch ? data.applications.find((item) => item.id === applicationMatch[1]) : null;
  if (applicationMatch && !application) return <div className="content"><Alert type="error">Заявка не найдена в списке.</Alert><Button onClick={() => navigate("/client")}>К заявкам</Button></div>;
  if (pathname === "/client/new/application" || applicationMatch) {
    const product = data.products.find((item) => item.code === (application?.product_code || selection?.product.code));
    return <><Editor application={application} product={product} need={selection?.need} formSnapshot={formSnapshot} onFormChange={setFormSnapshot} company={data.company} onClose={() => navigate("/client", { replace: true })} onToast={showToast} onSaved={(saved) => setData({ ...data, applications: [saved, ...data.applications.filter((item) => item.id !== saved.id)] })} onDeleted={(id) => { setData({ ...data, applications: data.applications.filter((item) => item.id !== id) }); setFormSnapshot(null); showToast("Черновик заявки удалён"); navigate("/client", { replace: true }); }} />{toast && <Toast key={toast.id} message={toast.message} onClose={dismissToast} />}</>;
  }
  return <><Dashboard company={data.company} applications={data.applications} onNew={() => { setSelection(null); setNeedSnapshot(null); setFormSnapshot(null); navigate("/client/new"); }} onOpen={(item) => { setFormSnapshot(null); navigate(`/client/applications/${item.id}`); }} />{toast && <Toast key={toast.id} message={toast.message} onClose={dismissToast} />}</>;
}
