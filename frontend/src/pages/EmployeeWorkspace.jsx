import { useEffect, useState } from "react";
import { api } from "../api/client.js";
import { Alert, Button, EmptyState, Field, Skeleton, StatusBadge } from "../components/UI.jsx";

const filters = ["", "UNDER_REVIEW", "NEEDS_INFO", "APPROVED", "REJECTED"];

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
    {items === null ? <Skeleton rows={5} /> : items.length ? <div className="bank-table"><div className="bank-table__head"><span>Клиент и цель</span><span>Сумма</span><span>Риск</span><span>Статус</span><span /></div>{items.map((item) => <button key={item.id} onClick={() => navigate(`/employee/applications/${item.id}`)}><span><b>{item.company?.name || item.company_name || "Компания"}</b><small>{item.purpose || "Цель не указана"}</small></span><strong>{item.requested_amount ? `${Number(item.requested_amount).toLocaleString("ru-RU")} ₽` : "—"}</strong><span className={`risk risk--${String(item.risk_level || "unknown").toLowerCase()}`}>{item.risk_level || "—"}</span><StatusBadge status={item.status} /><i>→</i></button>)}</div> : <EmptyState icon="✓" title={unavailable ? "Ожидаем API обработки" : "В очереди пусто"}>Новых заявок с выбранным статусом нет.</EmptyState>}
  </div>;
}

function ApplicationReview({ id, onBack, unavailable }) {
  const [record, setRecord] = useState(null); const [error, setError] = useState(""); const [comment, setComment] = useState(""); const [busy, setBusy] = useState(false);
  useEffect(() => { if (!unavailable) Promise.all([api.bankApplication(id), api.bankAssessments(id)]).then(([application, assessments]) => setRecord({ ...application, assessments })).catch((err) => setError(err.message)); }, [id, unavailable]);
  async function action(type) { setBusy(true); setError(""); try { if (type === "info") await api.requestInfo(id, { comment }); else await api.decide(id, { decision: type === "approve" ? "APPROVED" : "REJECTED", comment }); onBack(); } catch (err) { setError(err.message); } finally { setBusy(false); } }
  return <div className="content content--wide"><button className="back-link" onClick={onBack}>← К очереди</button>{error && <Alert type="error">{error}</Alert>}{!record ? <Skeleton rows={6} /> : <div className="review-layout"><main><div className="page-heading"><div><span className="eyebrow eyebrow--red">Заявка {String(id).slice(0, 8)}</span><h1>{record.company?.name || "Компания"}</h1><p>{record.purpose}</p></div><StatusBadge status={record.status} /></div><section className="panel"><h2>Параметры и финансы</h2><dl className="facts"><div><dt>Сумма</dt><dd>{record.requested_amount} ₽</dd></div><div><dt>Срок</dt><dd>{record.term_months} мес.</dd></div><div><dt>Выручка</dt><dd>{record.average_monthly_revenue} ₽/мес.</dd></div><div><dt>Расходы</dt><dd>{record.average_monthly_operating_expenses} ₽/мес.</dd></div></dl></section><AssessmentSummary assessment={record.assessments?.[0]} /></main><aside className="panel sticky-card"><span className="eyebrow">Решение</span><h3>Следующее действие</h3><Field label="Комментарий клиенту"><textarea rows="5" value={comment} onChange={(e) => setComment(e.target.value)} /></Field><Button busy={busy} onClick={() => action("approve")}>Одобрить</Button><Button busy={busy} variant="secondary" onClick={() => action("info")}>Запросить сведения</Button><Button busy={busy} variant="ghost" onClick={() => action("reject")}>Отказать</Button></aside></div>}</div>;
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

function AssessmentSummary({ assessment }) {
  if (!assessment) return <section className="panel"><h2>Оценка системы</h2><p className="muted">Оценка пока не сформирована.</p></section>;
  const result = assessment.result || {};
  const features = result.features || {};
  const inputData = assessment.input_snapshot?.input_data || result.input_snapshot?.input_data || {};
  const checks = assessment.input_snapshot?.checks || result.input_snapshot?.checks || [];
  const missingFields = result.missing_fields || [];
  const validationErrors = result.validation_errors || [];
  return <section className="panel assessment"><div className="assessment__heading"><div><h2>Оценка системы</h2><p className="muted">Демонстрационная оценка по данным заявки. Итоговое решение принимает сотрудник.</p></div><span>{assessmentStatuses[result.assessment_status] || "Статус неизвестен"}</span></div>
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
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(value))} ₽`;
}

function formatCalcPercent(value) {
  if (value === null || value === undefined || value === "" || !Number.isFinite(Number(value))) return "не рассчитывается";
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(value) * 100)}%`;
}
