import { useEffect, useMemo, useState } from "react";
import { ApiError, api } from "../api/client.js";
import { Alert, Button, EmptyState, Field, Skeleton, StatusBadge } from "../components/UI.jsx";
import { PURPOSES, draftPayload, matchProduct, validateApplication, validateNeed } from "../domain/application.js";
import { SliderInput } from "@alfalab/core-components-slider-input";

const emptyForm = {
  product_code: "", requested_amount: "", term_months: "", purpose: "",
  average_monthly_revenue: "", average_monthly_operating_expenses: "", existing_monthly_debt_payment: "",
};

function formatMoney(value) {
  if (value === null || value === undefined || value === "") return "—";
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(Number(value)) + " ₽";
}

function formatPercent(value) {
  if (value === null || value === undefined || value === "" || !Number.isFinite(Number(value))) return "—";
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(value) * 100)}%`;
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
  function updateRange(field, value) { updateNeed({ ...need, [field]: value === "" ? "" : String(value) }); }

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
        <div className="purpose-grid">{PURPOSES.map((purpose) => <button type="button" key={purpose.value} className={`purpose-card ${need.purposeCode === purpose.value ? "is-selected" : ""}`} onClick={() => updateNeed({ ...need, purposeCode: purpose.value })}><i /><strong>{purpose.label}</strong><span>{purpose.hint}</span></button>)}</div>
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
              onBlur={() => setFocusedRange("")}
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
              onBlur={() => setFocusedRange("")}
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

function Editor({ application, product, company, need, formSnapshot, onFormChange, onClose, onSaved, onDeleted }) {
  const [form, setForm] = useState(() => formSnapshot || (application ? { ...emptyForm, ...application } : {
    ...emptyForm, product_code: product?.code || "", requested_amount: need?.amount || "", term_months: need?.termMonths || "",
    purpose: PURPOSES.find((item) => item.value === need?.purposeCode)?.label || "",
  }));
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
  const status = saved?.status;
  const readOnly = ["SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED"].includes(status);
  const finalDecision = ["APPROVED", "REJECTED"].includes(status);
  const creditHints = useMemo(() => getCreditHints(form, product), [form, product]);
  const amountMin = Number(product?.min_amount ?? 300_000);
  const amountMax = Number(product?.max_amount ?? 10_000_000);
  const termMin = Number(product?.min_term_months ?? 6);
  const termMax = Number(product?.max_term_months ?? 60);
  const sliderValue = (value, min, max) => Math.min(max, Math.max(min, Number(value) || min));

  useEffect(() => {
    if (!saved?.id || !["NEEDS_INFO", "REJECTED"].includes(status)) {
      setInfoRequest({ loading: false, error: "", message: "" });
      return;
    }
    let active = true;
    setInfoRequest({ loading: true, error: "", message: "" });
    api.applicationEvents(saved.id)
      .then((events) => {
        if (!active) return;
        const eventType = status === "NEEDS_INFO" ? "INFO_REQUESTED" : "REJECTED";
        const latestEvent = [...events].reverse().find((event) => event.event_type === eventType);
        setInfoRequest({ loading: false, error: "", message: latestEvent?.message?.trim() || "" });
      })
      .catch((err) => {
        if (active) setInfoRequest({ loading: false, error: err.message, message: "" });
      });
    return () => { active = false; };
  }, [saved?.id, status]);

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
  };
  function updateRange(field, value) {
    const next = { ...form, [field]: value === "" ? "" : String(value) };
    setForm(next); onFormChange(next);
  }
  async function save(event) {
    event?.preventDefault(); if (readOnly) return;
    setBusy(true); setNotice(""); setErrors({});
    try {
      const payload = draftPayload(form);
      const result = saved ? await api.updateApplication(saved.id, { revision: saved.revision, ...payload }) : await api.createApplication(payload);
      setSaved(result); setForm({ ...emptyForm, ...result }); setNotice("Черновик сохранён"); setNoticeType("success"); onSaved(result);
    } catch (err) {
      if (err instanceof ApiError && err.fields.length) setErrors(Object.fromEntries(err.fields.map((item) => [item.field.split(".").pop(), item.message])));
      setNotice(err.message); setNoticeType("error");
    } finally { setBusy(false); }
  }
  async function submit() {
    if (readOnly) return;
    const nextErrors = validateApplication(form); setErrors(nextErrors); setNotice("");
    if (Object.keys(nextErrors).length) return;
    setBusy(true);
    try {
      let current = saved;
      if (!current) current = await api.createApplication(draftPayload(form));
      else current = await api.updateApplication(current.id, { revision: current.revision, ...draftPayload(form) });
      const result = await api.submitApplication(current.id, { credit_history_consent: creditHistoryConsent });
      setSaved(result); onSaved(result); setNotice("Заявка отправлена на рассмотрение"); setNoticeType("success");
    } catch (err) {
      if (err.status === 404 || err.status === 405) { setNotice("Отправка появится после подключения backend-процесса задачи №5. Черновик сохранён и не потерян."); setNoticeType("info"); }
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

  return <div className="content content--form"><button className="back-link" onClick={onClose}>← К заявкам</button><div className="page-heading"><div><span className="eyebrow eyebrow--red">Шаг 2 из 2</span><h1>{saved ? "Заявка" : "Расскажите о бизнесе"}</h1>{saved && <StatusBadge status={status} />}<p>{readOnly ? (status === "APPROVED" ? "Заявка одобрена. Анкета доступна только для просмотра." : status === "REJECTED" ? "По заявке принято решение об отказе. Анкета доступна только для просмотра." : "Заявка уже отправлена и ожидает решения. Изменения пока недоступны.") : "Известные банку сведения уже заполнены. Добавьте только показатели для оценки."}</p></div><span className="big-number">02</span></div>
    {notice && <Alert type={noticeType}>{notice}</Alert>}
    {status === "NEEDS_INFO" && <Alert title="Банк запросил уточнения">{infoRequest.loading ? "Загружаем сообщение сотрудника…" : infoRequest.error ? `Не удалось загрузить сообщение: ${infoRequest.error}` : infoRequest.message || "В истории нет текста запроса. Свяжитесь с сотрудником банка, чтобы уточнить, какие сведения нужно добавить."}</Alert>}
    {status === "REJECTED" && <Alert title="Комментарий банка">{infoRequest.loading ? "Загружаем сообщение сотрудника…" : infoRequest.error ? `Не удалось загрузить сообщение: ${infoRequest.error}` : infoRequest.message || "Сотрудник не добавил комментарий к решению."}</Alert>}
    {status === "UNDER_REVIEW" && alternativeError && <Alert type="error">Не удалось загрузить предложение: {alternativeError}</Alert>}
    {status === "UNDER_REVIEW" && alternativeOffer && <ClientAlternativeCard offer={alternativeOffer} busy={alternativeBusy} onDecision={decideAlternative} />}
    {status === "APPROVED" && application?.approved_amount !== null && application?.approved_amount !== undefined && <ApprovedConditions application={application} />}
    <form className="application-layout" onSubmit={save}>
      <div className="application-main">
        <section className="panel form-section"><div className="form-section__heading"><span>01</span><div><h2>Компания</h2><p>Сведения действующего клиента</p></div></div><div className="company-card"><b>{company.name}</b><span>{company.legal_form} · ИНН {company.inn}</span><small>Работает с {new Date(company.registration_date).toLocaleDateString("ru-RU")}</small></div></section>
        <section className="panel form-section"><div className="form-section__heading"><span>02</span><div><h2>Параметры кредита</h2><p>{readOnly ? "Параметры отправленной заявки" : "Можно изменить до отправки"}</p></div></div><Field label="Продукт" error={errors.product_code}><input value={product?.name || form.product_code} disabled /></Field><div className="form-row application-ranges"><div className="application-range"><SliderInput className="need-range__control" label="Сумма" value={focusedRange === "amount" ? form.requested_amount : formatInputNumber(form.requested_amount)} sliderValue={sliderValue(form.requested_amount, amountMin, amountMax)} min={amountMin} max={amountMax} step={50_000} size={64} client="desktop" rightAddons="₽" steps={[formatCompactMoney(amountMin), formatCompactMoney(Math.round((amountMin + amountMax) / 2 / 50_000) * 50_000), formatCompactMoney(amountMax)]} disabled={readOnly} error={errors.requested_amount} onChange={(_, payload) => updateRange("requested_amount", payload.value)} onFocus={() => setFocusedRange("amount")} onBlur={() => setFocusedRange("")} dataTestId="application-amount-slider" /></div><div className="application-range"><SliderInput className="need-range__control" label="Срок" value={focusedRange === "term" ? form.term_months : formatInputNumber(form.term_months)} sliderValue={sliderValue(form.term_months, termMin, termMax)} min={termMin} max={termMax} step={1} size={64} client="desktop" rightAddons="мес." steps={[formatTerm(termMin), formatTerm(Math.round((termMin + termMax) / 2)), formatTerm(termMax)]} disabled={readOnly} error={errors.term_months} onChange={(_, payload) => updateRange("term_months", payload.value)} onFocus={() => setFocusedRange("term")} onBlur={() => setFocusedRange("")} dataTestId="application-term-slider" /></div></div><Field label="Цель" error={errors.purpose}><textarea rows="3" maxLength="200" value={form.purpose ?? ""} onChange={set("purpose")} disabled={readOnly} /></Field></section>
        <section className="panel form-section"><div className="form-section__heading"><span>03</span><div><h2>Финансовые показатели</h2><p>Средние значения за последние 12 завершённых месяцев</p></div></div><div className="form-row application-ranges"><div className="application-range"><SliderInput className="need-range__control" label="Выручка в месяц" value={focusedRange === "revenue" ? form.average_monthly_revenue : formatInputNumber(form.average_monthly_revenue)} sliderValue={sliderValue(form.average_monthly_revenue, 50_000, 10_000_000)} min={50_000} max={10_000_000} step={50_000} size={64} client="desktop" rightAddons="₽" steps={[formatCompactMoney(50_000), formatCompactMoney(5_000_000), formatCompactMoney(10_000_000)]} disabled={readOnly} error={errors.average_monthly_revenue} onChange={(_, payload) => updateRange("average_monthly_revenue", payload.value)} onFocus={() => setFocusedRange("revenue")} onBlur={() => setFocusedRange("")} dataTestId="application-revenue-slider" /></div><div className="application-range"><SliderInput className="need-range__control" label="Операционные расходы" hint="Без платежей по кредитам" value={focusedRange === "expenses" ? form.average_monthly_operating_expenses : formatInputNumber(form.average_monthly_operating_expenses)} sliderValue={sliderValue(form.average_monthly_operating_expenses, 50_000, 10_000_000)} min={50_000} max={10_000_000} step={50_000} size={64} client="desktop" rightAddons="₽" steps={[formatCompactMoney(50_000), formatCompactMoney(5_000_000), formatCompactMoney(10_000_000)]} disabled={readOnly} error={errors.average_monthly_operating_expenses} onChange={(_, payload) => updateRange("average_monthly_operating_expenses", payload.value)} onFocus={() => setFocusedRange("expenses")} onBlur={() => setFocusedRange("")} dataTestId="application-expenses-slider" /></div></div><div className="application-range application-range--full"><SliderInput className="need-range__control" label="Ежемесячные платежи по действующим кредитам" value={focusedRange === "debt" ? form.existing_monthly_debt_payment : formatInputNumber(form.existing_monthly_debt_payment)} sliderValue={sliderValue(form.existing_monthly_debt_payment, 0, 10_000_000)} min={0} max={10_000_000} step={50_000} size={64} client="desktop" rightAddons="₽" steps={["0 ₽", formatCompactMoney(5_000_000), formatCompactMoney(10_000_000)]} disabled={readOnly} error={errors.existing_monthly_debt_payment} onChange={(_, payload) => updateRange("existing_monthly_debt_payment", payload.value)} onFocus={() => setFocusedRange("debt")} onBlur={() => setFocusedRange("")} dataTestId="application-debt-slider" /></div>{!readOnly && creditHints.length > 0 && <div className="credit-hints" role="status" aria-live="polite">{creditHints.map((hint) => <article className={`credit-hint credit-hint--${hint.severity}`} key={hint.title}><strong>{hint.title}</strong><span>{hint.text}</span></article>)}<small>Это подсказка, а не решение по кредиту. Банк проверит заявку и сообщит результат.</small></div>}</section>
      </div>
      <aside className="application-aside"><div className="panel sticky-card">{readOnly ? <><span className="eyebrow">{finalDecision ? "Решение банка" : "Заявка отправлена"}</span><h3>{status === "APPROVED" ? "Кредит одобрен" : status === "REJECTED" ? "Заявка отклонена" : "Заявка на рассмотрении"}</h3><p className="muted">{finalDecision ? "Изменить или отправить эту заявку повторно нельзя." : "Пока заявка рассматривается, редактирование и повторная отправка недоступны."}</p></> : <><span className="eyebrow">Перед отправкой</span><h3>Что произойдёт дальше</h3><ol><li>Проверим полноту анкеты</li><li>Выполним локальные проверки</li><li>Передадим сотруднику банка</li></ol><label className="consent-field"><input type="checkbox" checked={creditHistoryConsent} onChange={(event) => setCreditHistoryConsent(event.target.checked)} /><span>Согласен на запрос синтетической кредитной истории для проверки заявки.</span></label><Button type="submit" variant="secondary" busy={busy}>Сохранить черновик</Button><Button type="button" onClick={submit} busy={busy}>Отправить заявку</Button>{saved?.status === "DRAFT" && <Button type="button" variant="ghost" busy={busy} onClick={deleteDraft}>Удалить черновик</Button>}<small>Без согласия демо-проверка кредитной истории будет отмечена как недоступная. Это может ограничить решение и подбор альтернативных условий.</small></>}</div></aside>
    </form>
  </div>;
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
    <p className="approval-terms__note">Исходные параметры заявки сохранены в анкете ниже.</p>
  </section>;
}

function ClientAlternativeCard({ offer, busy, onDecision }) {
  const pending = offer.status === "OFFERED";
  const title = pending ? "Банк предлагает изменить условия" : offer.status === "ACCEPTED" ? "Вы приняли альтернативные условия" : "Вы отказались от альтернативных условий";
  return <section className="panel client-alternative"><div><span className="eyebrow eyebrow--red">Альтернатива от банка · демо-расчёт</span><h2>{title}</h2><p>{offer.reason}</p></div><dl className="facts"><div><dt>Сумма</dt><dd>{formatMoney(offer.amount)}</dd></div><div><dt>Срок</dt><dd>{offer.term_months} мес.</dd></div><div><dt>Ставка</dt><dd>{formatPercent(Number(offer.annual_interest_rate) / 100)}</dd></div><div><dt>Ежемесячный платёж</dt><dd>{formatMoney(offer.monthly_payment)}</dd></div><div><dt>Долговая нагрузка</dt><dd>{formatPercent(offer.debt_burden)}</dd></div></dl>{pending ? <><p className="muted">Если вы примете вариант, сотрудник банка всё равно должен принять итоговое решение. Исходные параметры заявки не изменятся.</p><div className="client-alternative__actions"><Button busy={busy} onClick={() => onDecision("ACCEPTED")}>Принять условия</Button><Button disabled={busy} variant="secondary" onClick={() => onDecision("DECLINED")}>Отказаться</Button></div></> : <p className="muted">{offer.status === "ACCEPTED" ? "Заявка остаётся на рассмотрении до решения сотрудника банка." : "Банк продолжит рассматривать исходную заявку."}</p>}</section>;
}

function Dashboard({ company, applications, onNew, onOpen }) {
  return <div className="content"><section className="client-hero"><div><span className="eyebrow">Кабинет предпринимателя</span><h1>Здравствуйте,<br />{company.name}</h1><p>Подберите финансирование и следите за решением без звонков и визитов.</p><Button onClick={onNew}>Подобрать финансирование</Button></div><div className="hero-shape" aria-hidden="true"><b>₽</b><i /><i /></div></section>
    <section className="dashboard-section"><div className="section-title"><div><span className="eyebrow eyebrow--red">Мои заявки</span><h2>История финансирования</h2></div><span>{applications.length}</span></div>{applications.length ? <div className="application-list">{applications.map((item) => <button key={item.id} onClick={() => onOpen(item)}><div><StatusBadge status={item.status} /><h3>{item.purpose || "Заявка без названия"}</h3><ApplicationTerms item={item} compact /></div><div><small>Обновлена</small><b>{new Date(item.updated_at).toLocaleDateString("ru-RU")}</b><i>→</i></div></button>)}</div> : <EmptyState icon="₽" title="Заявок пока нет" action={<Button onClick={onNew}>Начать подбор</Button>}>Начните с потребности — сумму, срок и продукт подберём на следующем шаге.</EmptyState>}</section>
  </div>;
}

function ApplicationTerms({ item, compact = false }) {
  const requested = `${formatMoney(item.requested_amount)} · ${item.term_months || "—"} мес.`;
  const hasApproval = item.approved_amount !== null && item.approved_amount !== undefined;
  if (!hasApproval) return <span className="application-terms__plain">Запрошено: {requested}</span>;

  const approved = `${formatMoney(item.approved_amount)} · ${item.approved_term_months} мес.`;
  return <span className={`application-terms${compact ? " application-terms--compact" : ""}`}>
    <span className="application-terms__requested"><small>Запрошено</small><s>{requested}</s></span>
    <span className="application-terms__arrow" aria-hidden="true">→</span>
    <span className="application-terms__approved"><small>Одобрено</small><strong>{approved}</strong></span>
  </span>;
}

export default function ClientWorkspace({ pathname, navigate }) {
  const [data, setData] = useState(null); const [error, setError] = useState(""); const [selection, setSelection] = useState(null); const [needSnapshot, setNeedSnapshot] = useState(null); const [formSnapshot, setFormSnapshot] = useState(null);
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
    return <Editor application={application} product={product} need={selection?.need} formSnapshot={formSnapshot} onFormChange={setFormSnapshot} company={data.company} onClose={() => navigate("/client", { replace: true })} onSaved={(saved) => setData({ ...data, applications: [saved, ...data.applications.filter((item) => item.id !== saved.id)] })} onDeleted={(id) => { setData({ ...data, applications: data.applications.filter((item) => item.id !== id) }); setFormSnapshot(null); navigate("/client", { replace: true }); }} />;
  }
  return <Dashboard company={data.company} applications={data.applications} onNew={() => { setSelection(null); setNeedSnapshot(null); setFormSnapshot(null); navigate("/client/new"); }} onOpen={(item) => { setFormSnapshot(null); navigate(`/client/applications/${item.id}`); }} />;
}
