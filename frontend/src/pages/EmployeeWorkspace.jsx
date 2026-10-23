import { useEffect, useState } from "react";
import { api } from "../api/client.js";
import { Alert, Button, EmptyState, Field, Skeleton, StatusBadge } from "../components/UI.jsx";

const filters = ["", "UNDER_REVIEW", "NEEDS_INFO", "APPROVED", "REJECTED"];

function hasChangedApprovedTerms(item) {
  return item?.approved_amount !== null && item?.approved_amount !== undefined
    && (Number(item.approved_amount) !== Number(item.requested_amount)
      || Number(item.approved_term_months) !== Number(item.term_months));
}

function formatAlternativeMoneyValue(value) {
  if (value === null || value === undefined || value === "" || !Number.isFinite(Number(value))) return "—";
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(Number(value));
}

function BankApplicationAmount({ item }) {
  if (!hasChangedApprovedTerms(item)) {
    return <strong>{item.requested_amount ? `${Number(item.requested_amount).toLocaleString("ru-RU")} ₽` : "—"}</strong>;
  }
  return <span className="bank-table__amount-change">
    <span className="bank-table__amount-change-original"><strong><s>{formatAlternativeMoneyValue(item.requested_amount)} ₽</s></strong><small><s>{item.term_months} мес.</s></small></span>
    <b aria-hidden="true">→</b>
    <span className="bank-table__amount-change-approved"><strong>{formatAlternativeMoneyValue(item.approved_amount)} ₽</strong><small>{item.approved_term_months} мес.</small></span>
  </span>;
}

export default function EmployeeWorkspace({ pathname, navigate }) {
  const [filter, setFilter] = useState(""); const [items, setItems] = useState(null); const [unavailable, setUnavailable] = useState(false); const [error, setError] = useState("");
  async function load() { setError(""); try { const result = await api.bankApplications(filter); setItems(result.items || result); setUnavailable(false); } catch (err) { if (err.status === 404 || err.status === 405) { setUnavailable(true); setItems([]); } else setError(err.message); } }
  useEffect(() => { load(); }, [filter]);
  const applicationMatch = pathname.match(/^\/employee\/applications\/([^/]+)$/);
  if (applicationMatch) return <ApplicationReview id={applicationMatch[1]} onBack={() => { navigate("/employee/queue", { replace: true }); load(); }} unavailable={unavailable} />;
  return <div className="content"><div className="employee-heading"><div><span className="eyebrow eyebrow--red">Рабочее место сотрудника</span><h1>Очередь заявок</h1><p>Рассмотрение, скоринг и дальнейшее действие — в одной карточке.</p></div><div className="employee-metric"><span>В работе</span><b>{items?.filter((item) => item.status === "UNDER_REVIEW").length || 0}</b></div></div>
    {unavailable && <Alert title="Backend обработки ещё не подключён">Интерфейс готов к маршрутам задачи №5. Когда появится `/api/v1/bank/applications`, очередь загрузится автоматически.</Alert>}
    {error && <Alert type="error">{error}</Alert>}
    <div className="filters">{filters.map((status) => <button key={status || "all"} className={filter === status ? "is-active" : ""} onClick={() => setFilter(status)}>{status ? <StatusBadge status={status} /> : "Все"}</button>)}</div>
    {items === null ? <Skeleton rows={5} /> : items.length ? <div className="bank-table"><div className="bank-table__head"><span>Клиент и цель</span><span>Сумма</span><span>Риск</span><span>Статус</span><span /></div>{items.map((item) => <button key={item.id} onClick={() => navigate(`/employee/applications/${item.id}`)}><span><b>{item.company?.name || item.company_name || "Компания"}</b><small>{item.purpose || "Цель не указана"}</small></span><BankApplicationAmount item={item} /><span className={`risk risk--${String(item.risk_level || "unknown").toLowerCase()}`}>{item.risk_level || "—"}</span><StatusBadge status={item.status} /><i>→</i></button>)}</div> : <EmptyState icon="✓" title={unavailable ? "Ожидаем API обработки" : "В очереди пусто"}>Новых заявок с выбранным статусом нет.</EmptyState>}
  </div>;
}

function ApplicationReview({ id, onBack, unavailable }) {
  const [record, setRecord] = useState(null); const [alternatives, setAlternatives] = useState(null); const [error, setError] = useState(""); const [comment, setComment] = useState(""); const [actionMode, setActionMode] = useState(null); const [busy, setBusy] = useState(false);
  async function refreshAlternatives() { setAlternatives(await api.bankAlternatives(id)); }
  useEffect(() => { if (!unavailable) Promise.all([api.bankApplication(id), api.bankAssessments(id), api.bankAlternatives(id)]).then(([application, assessments, alternativeSet]) => { setRecord({ ...application, assessments }); setAlternatives(alternativeSet); }).catch((err) => setError(err.message)); }, [id, unavailable]);
  async function generateAlternatives() {
    setBusy(true); setError("");
    try { setAlternatives(await api.generateAlternatives(id)); }
    catch (err) {
      if (err.code === "ASSESSMENT_CONTEXT_UNAVAILABLE") {
        setAlternatives({
          status: "BLOCKED",
          reason: "Эта оценка создана до сохранения отчётов БКИ и Compliance. Для безопасного подбора клиенту нужно отправить актуальную заявку заново.",
          alternatives: [],
        });
      } else setError(err.message);
    }
    finally { setBusy(false); }
  }
  async function sendAlternative(offerId) {
    setBusy(true); setError("");
    try { await api.offerAlternative(id, offerId); await refreshAlternatives(); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  async function action(type) {
    const message = comment.trim();
    if (type === "info" && !message) { setError("Напишите, какие сведения нужно предоставить."); return; }
    setBusy(true); setError("");
    try {
      if (type === "info") await api.requestInfo(id, { comment: message });
      else await api.decide(id, { decision: type === "approve" ? "APPROVED" : "REJECTED", ...(type === "reject" && message ? { comment: message } : {}) });
      onBack();
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  function openAction(mode) { setError(""); setComment(""); setActionMode(mode); }
  useEffect(() => {
    if (record?.status !== "UNDER_REVIEW") return undefined;
    const timer = window.setInterval(async () => {
      if (document.visibilityState !== "visible") return;
      try { setAlternatives(await api.bankAlternatives(id)); } catch { /* Keep the last known proposal while the API retries. */ }
    }, 5000);
    return () => window.clearInterval(timer);
  }, [id, record?.status]);
  return <div className="content content--wide"><button className="back-link" onClick={onBack}>← К очереди</button>{error && <Alert type="error">{error}</Alert>}{!record ? <Skeleton rows={6} /> : <div className="review-layout"><main><div className="page-heading"><div><span className="eyebrow eyebrow--red">Заявка {String(id).slice(0, 8)}</span><h1>{record.company?.name || "Компания"}</h1><p>{record.purpose}</p></div><StatusBadge status={record.status} /></div><section className="panel"><h2>Параметры и финансы</h2><dl className="facts"><div><dt>Сумма</dt><dd>{formatMoneyValue(record.requested_amount)} ₽</dd></div><div><dt>Срок</dt><dd>{record.term_months} мес.</dd></div><div><dt>Выручка</dt><dd>{formatMoneyValue(record.average_monthly_revenue)} ₽/мес.</dd></div><div><dt>Расходы</dt><dd>{formatMoneyValue(record.average_monthly_operating_expenses)} ₽/мес.</dd></div></dl></section><AssessmentSummary assessment={record.assessments?.[0]} title="Исходный скоринг" /><AlternativePanel application={record} alternativeSet={alternatives} busy={busy} onGenerate={generateAlternatives} onOffer={sendAlternative} /></main><aside className="panel sticky-card"><span className="eyebrow">Решение</span><h3>Следующее действие</h3>{actionMode ? <><Field label={actionMode === "info" ? "Какие сведения нужно предоставить клиенту?" : "Причина отказа — необязательно"} hint={actionMode === "reject" ? "Можно оставить пустым, например, для технического или очевидного отказа." : undefined}><textarea rows="5" maxLength="1000" value={comment} onChange={(e) => setComment(e.target.value)} autoFocus /></Field><Button busy={busy} onClick={() => action(actionMode)}>{actionMode === "info" ? "Отправить запрос" : "Подтвердить отказ"}</Button><Button disabled={busy} variant="ghost" onClick={() => { setActionMode(null); setComment(""); setError(""); }}>Отмена</Button></> : <><Button busy={busy} onClick={() => action("approve")}>Одобрить</Button><Button busy={busy} variant="secondary" onClick={() => openAction("info")}>Запросить сведения</Button><Button busy={busy} variant="ghost" onClick={() => openAction("reject")}>Отказать</Button></>}</aside></div>}</div>;
}

function AlternativePanel({ application, alternativeSet, busy, onGenerate, onOffer }) {
  const result = application.assessments?.[0]?.result || {};
  const hardStops = result.hard_stops || [];
  const underwritingRules = result.underwriting?.rules || [];
  const debtBurdenExceeded = hardStops.includes("EXCESSIVE_DEBT_BURDEN")
    || underwritingRules.some((rule) => rule.code === "DEBT_BURDEN" && rule.outcome === "REJECT");
  const bki = result.check_reports?.bki;
  const currentOverdue = Number(bki?.current_overdue_amount || 0);
  const overdueStop = hardStops.includes("CURRENT_OVERDUE") || hardStops.includes("SEVERE_OVERDUE_HISTORY");
  const generated = alternativeSet?.status && alternativeSet.status !== "NOT_GENERATED";
  const accepted = alternativeSet?.alternatives?.find((item) => item.status === "ACCEPTED");
  const activeOffer = alternativeSet?.active_offer;
  const canGenerate = application.status === "UNDER_REVIEW" && !accepted && !activeOffer;
  return <section className="panel alternatives"><div className="alternatives__heading"><div><h2>Альтернативные условия</h2><p>Клиент запрашивает кредит на {formatMoneyValue(application.requested_amount)} ₽ сроком {application.term_months} мес.</p><p>{debtBurdenExceeded ? "Система выявила превышение допустимой долговой нагрузки. Если остальные обязательные проверки это позволяют, она предложит меньшую сумму или более долгий срок." : "Система проверит, можно ли снизить ежемесячную нагрузку меньшей суммой или более долгим сроком."}</p><small>Расчётные варианты не являются одобрением. Итоговое решение принимает сотрудник.</small></div>{canGenerate && <Button busy={busy} variant="secondary" onClick={onGenerate}>{generated ? "Пересчитать варианты" : "Рассчитать варианты"}</Button>}</div>
    {(currentOverdue > 0 || overdueStop) && <Alert title="Просрочка в БКИ не устраняется изменением условий">Система не предложит альтернативу, пока не будет проверена текущая или длительная просрочка.</Alert>}
    {accepted && <Alert title="Клиент принял условия">Можно принять итоговое решение по сумме {formatAlternativeMoneyValue(accepted.amount)} ₽ на {accepted.term_months} мес.</Alert>}
    {activeOffer && <Alert title="Предложение отправлено клиенту">Ожидаем ответ по сумме {formatMoneyValue(activeOffer.amount)} ₽ на {activeOffer.term_months} мес.</Alert>}
    {generated && !alternativeSet.alternatives?.length && <p className="muted">{alternativeSet.reason || "Подходящие варианты не найдены."}</p>}
    {alternativeSet?.alternatives?.length > 0 && <div className="alternatives__list">{alternativeSet.alternatives.map((item) => <article className="alternative-card" key={item.id}><div className="alternative-card__top"><strong>{formatAlternativeMoneyValue(item.amount)} ₽</strong><span>{item.term_months} мес.</span></div><dl><div><dt>Ставка</dt><dd>{formatCalcPercent(Number(item.annual_interest_rate) / 100)}</dd></div><div><dt>Платёж в месяц</dt><dd>{formatAlternativeMoneyValue(item.monthly_payment)} ₽</dd></div><div><dt>Долговая нагрузка</dt><dd>{formatCalcPercent(item.debt_burden)}</dd></div></dl><p>{item.reason}</p><small>Скоринг: {recommendationLabels[item.evaluation?.scoring?.recommendation] || "—"}; underwriting: {item.evaluation?.underwriting?.status || "—"}.</small>{item.status === "GENERATED" && <Button busy={busy} onClick={() => onOffer(item.id)}>Предложить клиенту</Button>}{item.status === "OFFERED" && <span className="alternative-status">Ожидает ответа</span>}{item.status === "ACCEPTED" && <span className="alternative-status alternative-status--accepted">Клиент принял</span>}{item.status === "DECLINED" && <span className="alternative-status">Клиент отказался</span>}</article>)}</div>}
    {!generated && result.underwriting?.status !== "PASS" && application.status === "UNDER_REVIEW" && <p className="muted">Можно проверить, устраняются ли причины отказа изменением суммы или срока.</p>}
    {accepted && <AcceptedAlternativeReview application={application} offer={accepted} originalAssessment={application.assessments?.[0]} />}
  </section>;
}

const recommendationLabels = {
  APPROVE: "Рекомендуется одобрить",
  REVIEW: "Нужно дополнительное рассмотрение",
  DECLINE: "Рекомендуется отказ",
  REQUEST_INFO: "Нужно запросить сведения",
};
const riskLabels = { LOW: "Низкий", MEDIUM: "Средний", HIGH: "Высокий", UNKNOWN: "Не определён" };
const assessmentStatuses = { COMPLETED: "Оценка завершена", INSUFFICIENT_DATA: "Недостаточно данных" };
const factorLabels = {
  BUSINESS_AGE: "Срок работы бизнеса",
  OPERATING_MARGIN: "Операционная маржа",
  DEBT_BURDEN: "Долговая нагрузка",
  PAYMENT_HISTORY: "Платёжная история",
};
const checkLabels = { company_registry: "Проверка компании", credit_history: "Кредитная история" };
const checkStatuses = { PASS: "Пройдена", FAIL: "Не пройдена", UNKNOWN: "Нет данных" };
const fieldLabels = {
  requested_amount: "Сумма кредита",
  term_months: "Срок кредита",
  purpose: "Цель кредита",
  average_monthly_revenue: "Выручка в месяц",
  average_monthly_operating_expenses: "Операционные расходы",
  existing_monthly_debt_payment: "Платежи по текущим кредитам",
  "checks.company_registry": "Проверка компании",
  "checks.credit_history": "Кредитная история",
};
const checkReasonLabels = {
  SYNTHETIC_COMPANY_MATCH: "Данные компании совпали с демо-реестром",
  NO_DEMO_DELINQUENCIES: "В демо-истории просрочек нет",
  ACTIVE: "Компания активна",
  AVAILABLE: "Данные доступны",
  UNAVAILABLE: "Данные временно недоступны",
};

function AcceptedAlternativeReview({ application, offer, originalAssessment }) {
  const original = originalAssessment?.result || {};
  const originalFeatures = original.features || {};
  const rescored = offer.evaluation?.scoring || {};
  const rescoredAssessment = { result: rescored, input_snapshot: rescored.input_snapshot };
  const originalPayment = originalFeatures.new_monthly_payment;
  const originalBurden = originalFeatures.debt_burden;
  return <>
    <section className="panel accepted-review">
      <div className="accepted-review__heading"><span className="eyebrow eyebrow--red">Клиент принял предложение</span><h2>Новые условия для итогового решения</h2><p>Сотрудник увидит исходные условия и вариант, который выбрал клиент.</p></div>
      <div className="accepted-review__comparison">
        <div className="accepted-review__side accepted-review__side--original"><small>Исходная заявка</small><strong><s>{formatAlternativeMoneyValue(application.requested_amount)} ₽</s></strong><span><s>{application.term_months} мес.</s></span><dl><div><dt>Ежемесячный платёж</dt><dd><s>{formatAlternativeMoneyValue(originalPayment)} ₽</s></dd></div><div><dt>Долговая нагрузка</dt><dd><s>{formatCalcPercent(originalBurden)}</s></dd></div><div><dt>Балл</dt><dd><s>{original.score ?? "—"} / 100</s></dd></div></dl></div>
        <span className="accepted-review__arrow" aria-hidden="true">→</span>
        <div className="accepted-review__side accepted-review__side--accepted"><small>Принятый вариант</small><strong>{formatAlternativeMoneyValue(offer.amount)} ₽</strong><span>{offer.term_months} мес.</span><dl><div><dt>Ежемесячный платёж</dt><dd>{formatAlternativeMoneyValue(offer.monthly_payment)} ₽</dd></div><div><dt>Долговая нагрузка</dt><dd>{formatCalcPercent(offer.debt_burden)}</dd></div><div><dt>Балл после пересчёта</dt><dd>{rescored.score ?? "—"} / 100</dd></div></dl><small>Ставка {formatCalcPercent(Number(offer.annual_interest_rate) / 100)} годовых</small></div>
      </div>
    </section>
    <AssessmentSummary assessment={rescoredAssessment} title="Скоринг по принятым условиям" />
    {offer.evaluation?.underwriting && <section className="panel accepted-review__underwriting"><h2>Проверки новых условий</h2><p>Underwriting: <strong>{offer.evaluation.underwriting.status === "PASS" ? "Пройден" : offer.evaluation.underwriting.status}</strong></p></section>}
  </>;
}

function AssessmentSummary({ assessment, title = "Оценка системы" }) {
  if (!assessment) return <section className="panel"><h2>{title}</h2><p className="muted">Оценка пока не сформирована.</p></section>;
  const result = assessment.result || {};
  const features = result.features || {};
  const inputData = assessment.input_snapshot?.input_data || result.input_snapshot?.input_data || {};
  const checks = assessment.input_snapshot?.checks || result.input_snapshot?.checks || [];
  const missingFields = result.missing_fields || [];
  const validationErrors = result.validation_errors || [];
  return <section className="panel assessment"><div className="assessment__heading"><div><h2>{title}</h2><p className="muted">Демонстрационная оценка по данным заявки. Итоговое решение принимает сотрудник.</p></div><span>{assessmentStatuses[result.assessment_status] || "Статус неизвестен"}</span></div>
    <div className="assessment__summary"><div className="assessment__score"><small>Балл</small><strong>{result.score ?? "—"}<span>{result.score === null || result.score === undefined ? "" : " / 100"}</span></strong><small>Риск: {riskLabels[result.risk_level] || "Не определён"}</small></div><div><small>Рекомендация системы</small><strong>{recommendationLabels[result.recommendation] || "Не сформирована"}</strong></div></div>
    {result.reasons?.length > 0 && <div className="assessment__section"><h3>Почему система дала такую рекомендацию</h3><ul>{result.reasons.map((reason, index) => <li key={`${reason.code || "reason"}-${index}`}>{reason.message || reason.code}</li>)}</ul></div>}
    {result.factors?.length > 0 && <div className="assessment__section"><h3>Из чего сложился балл</h3><div className="assessment__factors">{result.factors.map((factor) => <article key={factor.code}><div><strong>{factorLabels[factor.code] || factor.code}</strong><b>{factor.points} из {factor.max_points}</b></div><p>{factor.explanation}</p>{factor.code === "OPERATING_MARGIN" && <AssessmentFormula title="Расчёт операционной маржи" formula="(выручка − операционные расходы) / выручка" values={`(${formatCalcMoney(inputData.average_monthly_revenue)} − ${formatCalcMoney(inputData.average_monthly_operating_expenses)}) / ${formatCalcMoney(inputData.average_monthly_revenue)} = ${formatCalcPercent(features.operating_margin)}`} />}{factor.code === "DEBT_BURDEN" && <AssessmentFormula title="Расчёт долговой нагрузки" formula="(текущие платежи + платёж нового кредита) / прибыль после расходов" values={`(${formatCalcMoney(inputData.existing_monthly_debt_payment)} + ${formatCalcMoney(features.new_monthly_payment)}) / ${formatCalcMoney(features.monthly_operating_profit)} = ${formatCalcPercent(features.debt_burden)}`} note="Платёж нового кредита рассчитан по аннуитетной формуле." />}</article>)}</div><small className="assessment__formula-note">Проценты показаны с округлением до 2 знаков; скоринг использует точные значения.</small></div>}
    {checks.length > 0 && <div className="assessment__section"><h3>Проверки</h3><div className="assessment__checks">{checks.map((check) => <div key={check.source}><strong>{checkLabels[check.source] || check.source}</strong><span className={`assessment__check assessment__check--${String(check.status).toLowerCase()}`}>{checkStatuses[check.status] || check.status}</span><small>{checkReasonLabels[check.reason_code] || check.reason_code}</small></div>)}</div></div>}
    {result.hard_stops?.length > 0 && <div className="assessment__stops"><strong>Обязательные ограничения</strong><ul>{result.hard_stops.map((code) => <li key={code}>{result.reasons?.find((reason) => reason.code === code)?.message || code}</li>)}</ul></div>}
    {(missingFields.length > 0 || validationErrors.length > 0) && <div className="assessment__section"><h3>Что нужно уточнить</h3><ul>{missingFields.map((field) => <li key={field}>{fieldLabels[field] || field}</li>)}{validationErrors.map((item, index) => <li key={`${item.field || "validation"}-${index}`}>{item.message || fieldLabels[item.field] || item.field}</li>)}</ul></div>}
  </section>;
}

function AssessmentFormula({ title, formula, values, note }) {
  return <div className="assessment__calculation"><strong>{title}</strong><span>{formula}</span><b>{values}</b>{note && <small>{note}</small>}</div>;
}

function formatCalcMoney(value) {
  if (value === null || value === undefined || value === "" || !Number.isFinite(Number(value))) return "—";
  return `${formatMoneyValue(value)} ₽`;
}

function formatMoneyValue(value) {
  if (value === null || value === undefined || value === "" || !Number.isFinite(Number(value))) return "—";
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(value));
}

function formatCalcPercent(value) {
  if (value === null || value === undefined || value === "" || !Number.isFinite(Number(value))) return "не рассчитывается";
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(value) * 100)}%`;
}
