import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client.js";
import { Accordion } from "@alfalab/core-components-accordion";
import { Alert, Button, EmptyState, Field, Skeleton, StatusBadge, Toast } from "../components/UI.jsx";
import { approvalBlockReason, latestComplianceReview, requiresComplianceReview } from "../domain/pipeline.js";

const filters = ["", "UNDER_REVIEW", "NEEDS_INFO", "APPROVED", "REJECTED"];
const recommendationLabels = { APPROVE: "Положительная рекомендация скоринга", REVIEW: "Нужно дополнительное рассмотрение", DECLINE: "Отрицательная рекомендация скоринга", REQUEST_INFO: "Нужно запросить сведения" };
const riskLabels = { LOW: "Низкий", MEDIUM: "Средний", HIGH: "Высокий", UNKNOWN: "Не определён" };
const assessmentStatuses = { COMPLETED: "Оценка завершена", INSUFFICIENT_DATA: "Недостаточно данных" };
const underwritingLabels = { PASS: "Проверки пройдены", REVIEW: "Нужна ручная проверка", REJECT: "Есть стоп-фактор" };
const outcomeLabels = { PASS: "Пройдено", REVIEW: "Требует внимания", REJECT: "Не пройдено" };
const reportStatusLabels = { AVAILABLE: "Данные получены", NO_HISTORY: "Истории нет", UNAVAILABLE: "Источник недоступен", ERROR: "Техническая ошибка", CLEAR: "Совпадений нет", POTENTIAL_MATCH: "Возможное совпадение", CONFIRMED_MATCH: "Совпадение подтверждено" };
const complianceOutcomeLabels = { CLEAR: "Совпадение снято", CONFIRMED_MATCH: "Совпадение подтверждено" };
const factorLabels = { BUSINESS_AGE: "Срок работы бизнеса", OPERATING_MARGIN: "Операционная маржа", DEBT_BURDEN: "Долговая нагрузка", PAYMENT_HISTORY: "Платёжная история" };
const checkLabels = { company_registry: "Проверка компании", credit_history: "Кредитная история" };
const checkStatuses = { PASS: "Пройдена", FAIL: "Не пройдена", UNKNOWN: "Нет данных" };
const checkReasonLabels = { SYNTHETIC_COMPANY_MATCH: "Данные компании совпали с демо-реестром", NO_DEMO_DELINQUENCIES: "В демо-истории просрочек нет", POSITIVE_HISTORY: "Положительная кредитная история", MINOR_DELAY_HISTORY: "Были отдельные задержки платежей до 7 дней", NO_CREDIT_HISTORY: "Кредитная история отсутствует", AVAILABLE: "Данные доступны", ACTIVE: "Компания действует", INACTIVE: "Компания не действует", UNAVAILABLE: "Данные временно недоступны", TIMEOUT: "Источник не ответил вовремя", CONSENT_REQUIRED: "Клиент не дал согласие на запрос кредитной истории", PROVIDER_UNAVAILABLE: "Источник временно недоступен", SYNTHETIC_PROVIDER_ERROR: "Техническая ошибка демо-источника", UNSUPPORTED_SUBJECT_TYPE: "Тип клиента не поддерживается проверкой" };
const reasonCodeLabels = { AMOUNT_OUT_OF_RANGE: "Сумма не входит в условия продукта.", TERM_OUT_OF_RANGE: "Срок не входит в условия продукта.", BUSINESS_TOO_YOUNG: "Бизнес работает меньше требуемого срока.", NON_POSITIVE_OPERATING_PROFIT: "Доход после расходов не позволяет обслуживать кредит.", EXCESSIVE_DEBT_BURDEN: "Долговая нагрузка превышает лимит продукта.", CURRENT_OVERDUE: "Есть текущая просроченная задолженность.", SEVERE_OVERDUE_HISTORY: "Срок прошлых просрочек превышает лимит продукта.", CHECKS_INCOMPLETE: "Не все обязательные проверки завершены.", SCORE_SUFFICIENT: "Балл достаточен для рассмотрения заявки.", MANUAL_REVIEW: "Требуется дополнительная оценка сотрудником.", LOW_SCORE: "Балл ниже минимального порога продукта." };
const underwritingRuleLabels = { SYNTHETIC_INTERNAL_BLACKLIST: "Внутренний стоп-фактор", SYNTHETIC_INTERNAL_WHITELIST: "Внутренний белый список", MIN_BUSINESS_AGE: "Возраст бизнеса", PRODUCT_AMOUNT_LIMIT: "Лимит продукта", DEBT_BURDEN: "Долговая нагрузка", BKI_AVAILABILITY: "Доступность БКИ", BKI_HISTORY: "Кредитная история", CURRENT_OVERDUE: "Текущая просрочка", COMPLIANCE_CLEAR: "Комплаенс-проверка", COMPLIANCE_POTENTIAL_MATCH: "Возможное совпадение в комплаенс-проверке", COMPLIANCE_CONFIRMED_MATCH: "Подтверждённое совпадение в комплаенс-проверке", COMPLIANCE_ERROR: "Ошибка комплаенс-проверки" };
const auditLabels = { APPLICATION_CREATED: "Заявка создана", BKI_CHECK: "Проверка БКИ", COMPLIANCE_CHECK: "Комплаенс-проверка", UNDERWRITING_EVALUATED: "Правила кредитования проверены", SCORING_COMPLETED: "Скоринг завершён", APPLICATION_SUBMITTED: "Заявка отправлена", APPLICATION_UPDATED: "Анкета обновлена", AI_SCORING_EXPLANATION: "ИИ-анализ скоринга", COMPLIANCE_REVIEW: "Ручной разбор комплаенс-проверки", REVIEW_ACTION: "Решение сотрудника", ALTERNATIVES_GENERATED: "Рассчитаны альтернативы", ALTERNATIVE_OFFERED: "Альтернатива предложена", ALTERNATIVE_ACCEPTED: "Клиент принял альтернативу", ALTERNATIVE_DECLINED: "Клиент отклонил альтернативу", ALTERNATIVE_SUPERSEDED: "Альтернатива закрыта", PIPELINE_ERROR: "Техническая ошибка конвейера" };
const auditSourceLabels = { applications: "Заявка", synthetic_bki: "Демо-БКИ", synthetic_bki_fixture: "Демо-БКИ", synthetic_compliance: "Демо-реестр", synthetic_compliance_fixture: "Демо-реестр", underwriting_rules: "Правила кредитования", scoring: "Скоринг", local_ollama: "Локальная Ollama", employee_compliance: "Сотрудник банка", employee_review: "Сотрудник банка", client_alternatives: "Клиент", alternative_engine: "Подбор условий" };
const alternativeStatusLabels = { GENERATED: "Рассчитан", OFFERED: "Ожидает ответа", ACCEPTED: "Клиент принял", DECLINED: "Клиент отказался", SUPERSEDED: "Закрыт после решения" };

function hasChangedApprovedTerms(item) {
  return item?.approved_amount !== null && item?.approved_amount !== undefined && (Number(item.approved_amount) !== Number(item.requested_amount) || Number(item.approved_term_months) !== Number(item.term_months));
}
function formatMoney(value) {
  if (value === null || value === undefined || value === "" || !Number.isFinite(Number(value))) return "—";
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(value));
}
function formatMoneyRub(value) {
  const formatted = formatMoney(value);
  return formatted === "—" ? formatted : `${formatted} ₽`;
}
function formatPercent(value) {
  if (value === null || value === undefined || value === "" || !Number.isFinite(Number(value))) return "—";
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(value) * 100)}%`;
}

function newestApplicationFirst(left, right) {
  const leftCreatedAt = Date.parse(left.created_at || "");
  const rightCreatedAt = Date.parse(right.created_at || "");
  if (!Number.isFinite(leftCreatedAt)) return Number.isFinite(rightCreatedAt) ? 1 : 0;
  if (!Number.isFinite(rightCreatedAt)) return -1;
  return rightCreatedAt - leftCreatedAt;
}

function recommendationReason(reason) {
  if (reasonCodeLabels[reason?.code]) return reasonCodeLabels[reason.code];
  if (reason?.code?.startsWith("CHECK_FAILED:")) {
    const source = reason.code.split(":")[1];
    return `${checkLabels[source] || "Обязательная проверка"} не пройдена.`;
  }
  return reason?.message || "Причина сохранена в результатах оценки.";
}

function BankApplicationAmount({ item }) {
  if (!hasChangedApprovedTerms(item)) return <strong>{formatMoneyRub(item.requested_amount)}</strong>;
  return <span className="bank-table__amount-change"><span className="bank-table__amount-change-original"><strong><s>{formatMoneyRub(item.requested_amount)}</s></strong><small><s>{item.term_months} мес.</s></small></span><b>→</b><span className="bank-table__amount-change-approved"><strong>{formatMoneyRub(item.approved_amount)}</strong><small>{item.approved_term_months} мес.</small></span></span>;
}
function ReviewValue({ original, value, money = false }) {
  return <span className="review-value"><s>{money ? formatMoneyRub(original) : original}</s><b aria-hidden="true">→</b><strong>{money ? formatMoneyRub(value) : value}</strong></span>;
}
function BankApplicationRisk({ item }) {
  if (item.status === "APPROVED" && hasChangedApprovedTerms(item) && item.approved_risk_level) return <span className="bank-table__risk-change"><s className={`risk risk--${String(item.risk_level || "unknown").toLowerCase()}`}>{riskLabels[item.risk_level] || "—"}</s><b>→</b><span className={`risk risk--${String(item.approved_risk_level).toLowerCase()}`}>{riskLabels[item.approved_risk_level]}</span></span>;
  return <span className={`risk risk--${String(item.risk_level || "unknown").toLowerCase()}`}>{riskLabels[item.risk_level] || "—"}</span>;
}

function CollapsiblePanel({ className = "", eyebrow, title, description, summary, children }) {
  return <Accordion
    className={`panel employee-accordion ${className}`.trim()}
    containerClassName="employee-accordion__trigger"
    headerClassName="employee-accordion__header"
    bodyContentClassName="employee-accordion__content"
    header={<div className="employee-accordion__heading">
      {eyebrow && <span className="eyebrow eyebrow--red">{eyebrow}</span>}
      <div className="employee-accordion__title-row"><h2>{title}</h2>{summary && <span className="employee-accordion__summary">{summary}</span>}</div>
      {description && <p>{description}</p>}
    </div>}
    defaultExpanded={false}
  >{children}</Accordion>;
}

function ApplicationTable({ title, items, navigate }) {
  if (!items.length) return null;
  return <section className="bank-queue-section" aria-label={`${title}: ${items.length}`}>
    <div className="bank-queue-section__heading"><h2>{title}</h2><span>{items.length}</span></div>
    <div className="bank-table"><div className="bank-table__head"><span>Клиент и цель</span><span>Сумма</span><span>Риск</span><span>Статус</span><span /></div>{items.map((item) => <button key={item.id} onClick={() => navigate(`/employee/applications/${item.id}`)}><span><b>{item.company?.name || "Компания"}</b><small>{item.purpose || "Цель не указана"}</small></span><BankApplicationAmount item={item} /><BankApplicationRisk item={item} /><StatusBadge status={item.status} /><i>→</i></button>)}</div>
  </section>;
}

export default function EmployeeWorkspace({ pathname, navigate }) {
  const [filter, setFilter] = useState("");
  const [items, setItems] = useState(null);
  const [openCount, setOpenCount] = useState(0);
  const [unavailable, setUnavailable] = useState(false);
  const [error, setError] = useState("");
  async function load(silent = false) {
    if (!silent) setError("");
    try {
      const [result, allResult] = await Promise.all([
        api.bankApplications(filter),
        filter ? api.bankApplications() : Promise.resolve(null),
      ]);
      const nextItems = result.items || result;
      const allItems = allResult ? (allResult.items || allResult) : nextItems;
      setItems(nextItems); setOpenCount(allItems.filter((item) => item.status === "UNDER_REVIEW").length); setUnavailable(false); setError("");
    }
    catch (err) { if (err.status === 404 || err.status === 405) { setUnavailable(true); setItems([]); } else setError(err.message); }
  }
  useEffect(() => { load(); }, [filter]);
  useEffect(() => { const timer = window.setInterval(() => { if (document.visibilityState === "visible") load(true); }, 5000); return () => window.clearInterval(timer); }, [filter]);
  const applicationMatch = pathname.match(/^\/employee\/applications\/([^/]+)$/);
  if (applicationMatch) return <ApplicationReview key={applicationMatch[1]} id={applicationMatch[1]} navigate={navigate} onBack={() => { navigate("/employee/queue", { replace: true }); load(); }} unavailable={unavailable} />;
  const sortedItems = [...(items || [])].sort(newestApplicationFirst);
  const waitingItems = sortedItems.filter((item) => ["SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO"].includes(item.status));
  const reviewedItems = sortedItems.filter((item) => !["SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO"].includes(item.status));
  return <div className="content"><div className="employee-heading"><div><span className="eyebrow eyebrow--red">Рабочее место сотрудника</span><h1>Очередь заявок</h1><p>Рассмотрение, проверки и решение — в одной карточке.</p></div><div className="employee-metric"><span>В работе</span><b>{openCount}</b></div></div>
    {unavailable && <Alert title="Очередь временно недоступна">Сервер не вернул данные заявок. Попробуйте обновить список.</Alert>}
    {error && <><Alert type="error">{error}</Alert><Button variant="secondary" onClick={() => load()}>Повторить</Button></>}
    <div className="filters">{filters.map((status) => <button key={status || "all"} className={filter === status ? "is-active" : ""} onClick={() => setFilter(status)}>{status ? <StatusBadge status={status} /> : "Все"}</button>)}</div>
    {items === null ? <Skeleton rows={5} /> : items.length ? <div className="bank-queue">{waitingItems.length > 0 && <ApplicationTable title="В работе" items={waitingItems} navigate={navigate} />}<ApplicationTable title="Рассмотрены" items={reviewedItems} navigate={navigate} /></div> : <EmptyState icon="✓" title={unavailable ? "Ожидаем API обработки" : "В очереди пусто"}>Новых заявок с выбранным статусом нет.</EmptyState>}
  </div>;
}

function ApplicationReview({ id, navigate, onBack, unavailable }) {
  const [record, setRecord] = useState(null);
  const [alternatives, setAlternatives] = useState(null);
  const [audit, setAudit] = useState(null);
  const [history, setHistory] = useState(null);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyOffset, setHistoryOffset] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyMoreLoading, setHistoryMoreLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [error, setError] = useState("");
  const [comment, setComment] = useState("");
  const [actionMode, setActionMode] = useState(null);
  const [busy, setBusy] = useState(false);
  const [aiAnalysis, setAiAnalysis] = useState(null);
  const [aiAnalysisError, setAiAnalysisError] = useState("");
  const [aiAnalysisBusy, setAiAnalysisBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);
  const dismissToast = useCallback(() => setToast(null), []);
  async function loadRecord(silent = false) {
    if (unavailable) return;
    if (!silent) { setLoading(true); setError(""); }
    try {
      const [application, assessments, alternativeSet, auditLog, savedAiAnalysis] = await Promise.all([
        api.bankApplication(id), api.bankAssessments(id), api.bankAlternatives(id), api.bankAudit(id), api.bankAIAnalysis(id),
      ]);
      setRecord({ ...application, assessments }); setAlternatives(alternativeSet); setAudit(auditLog);
      setAiAnalysis(savedAiAnalysis); setError("");
    } catch (err) { setError(err.message); }
    finally { if (!silent) setLoading(false); }
  }
  async function loadHistory(companyId, offset = 0, append = false) {
    if (append) setHistoryMoreLoading(true);
    else { setHistoryLoading(true); setHistoryError(""); }
    try {
      const page = await api.bankCompanyHistory(companyId, 20, offset);
      setHistory((current) => append ? [...(current || []), ...page.items] : page.items);
      setHistoryTotal(page.total);
      setHistoryOffset(offset + page.items.length);
    } catch (err) { setHistoryError(err.message); }
    finally { setHistoryLoading(false); setHistoryMoreLoading(false); }
  }
  useEffect(() => {
    setAiAnalysis(null); setAiAnalysisError("");
    loadRecord();
  }, [id, unavailable]);
  useEffect(() => {
    if (record?.company?.id) loadHistory(record.company.id);
  }, [record?.company?.id, record?.status]);
  useEffect(() => { if (!record || ["APPROVED", "REJECTED"].includes(record.status)) return undefined; const timer = window.setInterval(() => { if (document.visibilityState === "visible") loadRecord(true); }, 5000); return () => window.clearInterval(timer); }, [id, record?.status, unavailable]);
  const baseAssessment = record?.assessments?.[0];
  const acceptedAlternative = alternatives?.alternatives?.find((item) => item.status === "ACCEPTED");
  const acceptedScoring = acceptedAlternative?.evaluation?.scoring;
  const acceptedUnderwriting = acceptedAlternative?.evaluation?.underwriting;
  const assessment = acceptedAlternative && baseAssessment ? {
    ...baseAssessment,
    result: {
      ...baseAssessment.result,
      ...acceptedScoring,
      underwriting: acceptedUnderwriting,
      preliminary_decision: acceptedUnderwriting?.status === "REJECT" ? "DECLINE"
        : acceptedUnderwriting?.status === "REVIEW" ? "REVIEW"
          : acceptedScoring?.recommendation,
    },
  } : baseAssessment;
  const decisionApplication = acceptedAlternative ? {
    ...record,
    requested_amount: acceptedAlternative.amount,
    term_months: acceptedAlternative.term_months,
    preliminary_decision: assessment?.result?.preliminary_decision,
  } : record;
  const complianceReview = latestComplianceReview(audit, assessment?.id);
  const approvalReason = approvalBlockReason(decisionApplication, assessment, complianceReview);
  const reviewOpen = record?.status === "UNDER_REVIEW";
  const finalDecision = ["APPROVED", "REJECTED"].includes(record?.status);
  async function generateAlternatives() {
    setBusy(true); setError("");
    try { setAlternatives(await api.generateAlternatives(id)); }
    catch (err) { if (err.code === "ASSESSMENT_CONTEXT_UNAVAILABLE") setAlternatives({ status: "BLOCKED", reason: "В оценке нет данных для безопасного подбора. Клиенту нужно повторно отправить актуальную заявку.", alternatives: [] }); else setError(err.message); }
    finally { setBusy(false); }
  }
  async function sendAlternative(offerId) { setBusy(true); setError(""); try { await api.offerAlternative(id, offerId); await loadRecord(true); setToast({ id: Date.now(), message: "Альтернативные условия отправлены клиенту" }); } catch (err) { setError(err.message); } finally { setBusy(false); } }
  async function analyzeScoring() {
    if (aiAnalysisBusy || finalDecision) return;
    setAiAnalysisBusy(true); setAiAnalysisError(""); setAiAnalysis(null);
    try {
      setAiAnalysis(await api.analyzeBankScoring(id));
      setToast({ id: Date.now(), message: "ИИ-анализ заявки готов", position: "center" });
    }
    catch (err) { setAiAnalysisError(err.message || "Не удалось выполнить анализ. Повторите попытку."); }
    finally { setAiAnalysisBusy(false); }
  }
  async function action(type) {
    const message = comment.trim();
    if (type === "info" && !message) { setError("Напишите, какие сведения нужно предоставить."); return; }
    if (type === "approve" && approvalReason) { setError(approvalReason); return; }
    setBusy(true); setError("");
    try {
      if (type === "info") {
        await api.requestInfo(id, { comment: message });
        setAiAnalysis(null);
      }
      else {
        await api.decide(id, { decision: type === "approve" ? "APPROVED" : "REJECTED", ...(message ? { comment: message } : {}) });
        setAiAnalysisError("");
        setToast({ id: Date.now(), message: type === "approve" ? "Заявка одобрена" : "Заявка отклонена" });
      }
      setActionMode(null); setComment(""); await loadRecord(true);
    }
    catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  if (loading && !record) return <div className="content content--wide"><button className="back-link" onClick={onBack}>← К очереди</button><Skeleton rows={7} /></div>;
  if (!record) return <div className="content"><button className="back-link" onClick={onBack}>← К очереди</button><Alert type="error">{error || "Не удалось загрузить заявку."}</Alert><Button onClick={() => loadRecord()}>Повторить</Button></div>;
  return <div className="content content--wide"><button className="back-link" onClick={onBack}>← К очереди</button>{error && <Alert type="error">{error}</Alert>}<div className="review-layout"><main>
    <section className="review-hero"><div><span className="eyebrow">Заявка {String(id).slice(0, 8)}</span><h1>{record.company?.name || "Компания"}</h1><p>{record.purpose || "Цель финансирования не указана"}</p></div><StatusBadge status={record.status} /></section>
    <section className="panel"><div className="panel-title"><div><span className="eyebrow eyebrow--red">Анкета</span><h2>Параметры и финансы</h2></div></div>{acceptedAlternative && <p className="accepted-terms-note">Клиент принял альтернативу. В карточке и расчёте решения показаны новые условия; исходные сохранены ниже для сравнения.</p>}<dl className="facts facts--review"><div><dt>{acceptedAlternative ? "Сумма после альтернативы" : "Сумма"}</dt><dd>{acceptedAlternative ? <ReviewValue original={record.requested_amount} value={acceptedAlternative.amount} money /> : formatMoneyRub(record.requested_amount)}</dd></div><div><dt>{acceptedAlternative ? "Срок после альтернативы" : "Срок"}</dt><dd>{acceptedAlternative ? <ReviewValue original={`${record.term_months} мес.`} value={`${acceptedAlternative.term_months} мес.`} /> : record.term_months ? `${record.term_months} мес.` : "—"}</dd></div><div><dt>Выручка</dt><dd>{record.average_monthly_revenue === null || record.average_monthly_revenue === undefined ? "—" : `${formatMoneyRub(record.average_monthly_revenue)}/мес.`}</dd></div><div><dt>Расходы</dt><dd>{record.average_monthly_operating_expenses === null || record.average_monthly_operating_expenses === undefined ? "—" : `${formatMoneyRub(record.average_monthly_operating_expenses)}/мес.`}</dd></div><div><dt>Текущие платежи</dt><dd>{record.existing_monthly_debt_payment === null || record.existing_monthly_debt_payment === undefined ? "—" : `${formatMoneyRub(record.existing_monthly_debt_payment)}/мес.`}</dd></div><div><dt>Продукт</dt><dd>{record.product?.name || record.product_code || "—"}</dd></div></dl></section>
    <DecisionOverview application={decisionApplication} assessment={assessment} />
    <CompanyHistoryPanel
      items={history}
      total={historyTotal}
      loading={historyLoading}
      moreLoading={historyMoreLoading}
      error={historyError}
      currentApplicationId={id}
      onOpen={(applicationId) => navigate(`/employee/applications/${applicationId}`)}
      onRetry={() => loadHistory(record.company.id)}
      onLoadMore={() => loadHistory(record.company.id, historyOffset, true)}
    />
    <ChecksPanel assessment={assessment} />
    <AssessmentSummary assessment={assessment} />
    <AIAnalysisPanel result={aiAnalysis} loading={aiAnalysisBusy} error={aiAnalysisError} onAnalyze={analyzeScoring} hasAssessment={Boolean(assessment)} inactive={finalDecision} />
    {requiresComplianceReview(assessment) && <ComplianceReviewPanel application={record} review={complianceReview} busy={busy} onSaved={() => loadRecord(true)} setBusy={setBusy} setError={setError} />}
    <AlternativePanel application={record} alternativeSet={alternatives} busy={busy} onGenerate={generateAlternatives} onOffer={sendAlternative} />
    <AuditPanel id={id} audit={audit} onError={setError} />
  </main><aside className="panel sticky-card decision-card"><span className="eyebrow">Итоговое решение</span><h3>{reviewOpen ? "Следующее действие" : finalDecision ? "Рассмотрение завершено" : "Ожидаем клиента"}</h3>
    {!reviewOpen ? <><StatusBadge status={record.status} /><p className="muted">{finalDecision ? "Итог зафиксирован. Действия по заявке завершены." : "Банк запросил сведения. Действия снова станут доступны после ответа клиента."}</p></> : actionMode ? <><Field label={actionMode === "info" ? "Какие сведения нужно предоставить клиенту?" : "Комментарий к отказу — необязательно"}><textarea rows="5" maxLength="1000" value={comment} onChange={(event) => setComment(event.target.value)} autoFocus /></Field><Button busy={busy} onClick={() => action(actionMode)}>{actionMode === "info" ? "Отправить запрос" : "Подтвердить отказ"}</Button><Button disabled={busy} variant="ghost" onClick={() => { setActionMode(null); setComment(""); setError(""); }}>Отмена</Button></> : <><Button busy={busy} disabled={Boolean(approvalReason)} onClick={() => action("approve")}>Одобрить</Button>{approvalReason && <p className="decision-card__reason">{approvalReason}</p>}<Button busy={busy} variant="secondary" onClick={() => { setComment(""); setActionMode("info"); }}>Запросить сведения</Button><Button busy={busy} variant="ghost" onClick={() => { setComment(""); setActionMode("reject"); }}>Отказать</Button></>}
  </aside></div>{toast && <Toast key={toast.id} message={toast.message} position={toast.position || "right"} onClose={dismissToast} />}</div>;
}

function CompanyHistoryPanel({ items, total, loading, moreLoading, error, currentApplicationId, onOpen, onRetry, onLoadMore }) {
  return <CollapsiblePanel className="company-history" eyebrow="Клиент" title="История обращений" description="Заявки компании и сохранённые результаты предыдущих рассмотрений." summary={items && <span className="company-history__count">{total}</span>}>
    {error && <><Alert type="error">{error}</Alert><Button variant="secondary" onClick={onRetry}>Повторить</Button></>}
    {loading && !items ? <Skeleton rows={2} /> : items?.length ? <>
      <ol className="company-history__list">{items.map((item) => <li key={item.id}>
        <button type="button" disabled={item.id === currentApplicationId} onClick={() => onOpen(item.id)} aria-current={item.id === currentApplicationId ? "page" : undefined}>
          <span className="company-history__top"><strong>{item.product?.name || item.product_code || "Кредитная заявка"}</strong><StatusBadge status={item.status} /></span>
          <span className="company-history__dates">Создана {new Date(item.created_at).toLocaleDateString("ru-RU")}{item.submitted_at && ` · отправлена ${new Date(item.submitted_at).toLocaleDateString("ru-RU")}`}</span>
          {item.purpose && <span className="company-history__purpose">{item.purpose}</span>}
          <span className="company-history__terms"><span>Запрошено: {formatMoneyRub(item.requested_amount)} · {item.term_months || "—"} мес.</span>
            {item.status === "APPROVED" && item.approved_amount !== null && item.approved_amount !== undefined && <strong>Одобрено: {formatMoneyRub(item.approved_amount)} · {item.approved_term_months} мес.</strong>}
          </span>
          <span className="company-history__score">Оценка: {item.score === null || item.score === undefined ? "нет" : `${item.score}/100`} · риск {riskLabels[item.approved_risk_level || item.risk_level] || "не определён"}{item.id === currentApplicationId && <b>Текущая заявка</b>}</span>
          <i aria-hidden="true">→</i>
        </button>
      </li>)}</ol>
      {items.length < total && <Button variant="secondary" busy={moreLoading} onClick={onLoadMore}>Показать ещё обращения</Button>}
    </> : !error && <EmptyState icon="◷" title="Предыдущих обращений нет">Это первое отправленное обращение компании.</EmptyState>}
  </CollapsiblePanel>;
}

function DecisionOverview({ application, assessment }) {
  const result = assessment?.result || {};
  const finalDecision = application.status === "APPROVED" ? "Одобрено сотрудником" : application.status === "REJECTED" ? "Отказ сотрудника" : application.status === "NEEDS_INFO" ? "Ожидаются сведения" : "Ещё не принято";
  return <section className="panel decision-overview"><div className="panel-title"><div><span className="eyebrow eyebrow--red">Конвейер решения</span><h2>Рекомендация и решение сотрудника</h2><p>Скоринговая рекомендация помогает оценить заявку, итоговое решение принимает сотрудник.</p></div></div><div className="decision-overview__grid"><article className="decision-overview__recommendation"><small>Скоринговая рекомендация</small><strong>{recommendationLabels[result.recommendation] || "Не сформирована"}</strong><span>Балл {result.score ?? "—"} из 100 · риск {riskLabels[result.risk_level] || "—"}</span></article><article className={`decision-overview__final ${application.status === "APPROVED" ? "is-positive" : application.status === "REJECTED" ? "is-negative" : ""}`}><small>Итог сотрудника</small><strong>{finalDecision}</strong><span>{application.status === "UNDER_REVIEW" ? "Доступно после обязательных проверок" : "Текущий статус заявки"}</span></article></div></section>;
}

function ChecksPanel({ assessment }) {
  if (!assessment) return <CollapsiblePanel title="Проверки" eyebrow="Обязательные проверки"><p className="muted">Результаты ещё не сформированы.</p></CollapsiblePanel>;
  const result = assessment.result || {};
  const bki = result.check_reports?.bki;
  const compliance = result.check_reports?.compliance;
  const underwriting = result.underwriting || {};
  return <CollapsiblePanel className="checks-panel" eyebrow="Обязательные проверки" title="БКИ, комплаенс и правила кредитования" summary={<span className={`result-pill result-pill--${String(underwriting.status || "unknown").toLowerCase()}`}>{underwritingLabels[underwriting.status] || "Нет результата"}</span>}><div className="check-report-grid">
    <article><div><span>БКИ</span><b className={`result-text result-text--${reportTone(bki?.status)}`}>{reportStatusLabels[bki?.status] || "Нет результата"}</b></div><dl><div><dt>Согласие</dt><dd>{bki?.consent_confirmed ? "Получено" : "Не получено"}</dd></div><div><dt>Ежемесячный платёж по данным БКИ</dt><dd>{bki?.monthly_payment === null || bki?.monthly_payment === undefined ? "—" : `${formatMoneyRub(bki.monthly_payment)}/мес.`}</dd></div><div><dt>Текущая просрочка</dt><dd>{formatMoneyRub(bki?.current_overdue_amount || 0)}</dd></div><div><dt>Макс. просрочка</dt><dd>{bki?.max_overdue_days_12m === null || bki?.max_overdue_days_12m === undefined ? "—" : `${bki.max_overdue_days_12m} дн.`}</dd></div></dl><p>{["ERROR", "UNAVAILABLE"].includes(bki?.status) ? "Техническая недоступность требует ручной проверки и не считается отказом." : checkReasonLabels[bki?.reason_code] || "Синтетический отчёт кредитной истории."}</p></article>
    <article><div><span>Комплаенс</span><b className={`result-text result-text--${reportTone(compliance?.status)}`}>{reportStatusLabels[compliance?.status] || "Нет результата"}</b></div><dl><div><dt>Ручной разбор</dt><dd>{compliance?.requires_manual_review || compliance?.status === "ERROR" ? "Требуется" : "Не требуется"}</dd></div><div><dt>Источник</dt><dd>Синтетический реестр</dd></div></dl><p>{compliance?.explanation || (compliance?.status === "ERROR" ? "Техническая ошибка требует ручного разбора и не означает отказ." : "Совпадений в демо-реестре нет.")}</p></article>
  </div><div className="underwriting-rules"><h3>Правила кредитования</h3>{underwriting.rules?.length ? underwriting.rules.map((rule) => <div key={rule.code}><span className={`rule-outcome rule-outcome--${String(rule.outcome).toLowerCase()}`}>{outcomeLabels[rule.outcome] || "Результат"}</span><div><strong>{underwritingRuleLabels[rule.code] || "Дополнительная проверка"}</strong><p>{rule.explanation || "Результат правила сохранён в оценке."}</p></div></div>) : <p className="muted">Правила не рассчитаны.</p>}</div></CollapsiblePanel>;
}
function reportTone(status) { if (["AVAILABLE", "NO_HISTORY", "CLEAR"].includes(status)) return "pass"; if (["POTENTIAL_MATCH", "CONFIRMED_MATCH", "ERROR", "UNAVAILABLE"].includes(status)) return "review"; return "unknown"; }

function ComplianceReviewPanel({ application, review, busy, onSaved, setBusy, setError }) {
  const [outcome, setOutcome] = useState("CLEAR");
  const [comment, setComment] = useState("");
  const [localError, setLocalError] = useState("");
  async function submit(event) { event.preventDefault(); if (!comment.trim()) { setLocalError("Комментарий обязателен для ручного разбора."); return; } setBusy(true); setLocalError(""); setError(""); try { await api.complianceReview(application.id, { outcome, comment: comment.trim() }); setComment(""); await onSaved(); } catch (err) { setError(err.message); } finally { setBusy(false); } }
  return <section className="panel compliance-review"><div className="panel-title"><div><span className="eyebrow eyebrow--red">Ручная проверка</span><h2>Разбор комплаенс-проверки</h2><p>Ошибка или совпадение не превращается в автоматический отказ — исход фиксирует сотрудник.</p></div></div>{review && <Alert type={review.payload?.outcome === "CLEAR" ? "success" : "info"} title="Последний сохранённый результат">{complianceOutcomeLabels[review.payload?.outcome] || "Результат сохранён"}: {review.payload?.comment || "Комментарий не указан"}. {new Date(review.created_at).toLocaleString("ru-RU")}</Alert>}{application.status === "UNDER_REVIEW" ? <form onSubmit={submit}><div className="compliance-options"><label className={outcome === "CLEAR" ? "is-selected" : ""}><input type="radio" name="compliance-outcome" value="CLEAR" checked={outcome === "CLEAR"} onChange={(event) => setOutcome(event.target.value)} /><strong>Совпадение снято</strong><span>Идентификаторы проверены, ограничений нет</span></label><label className={outcome === "CONFIRMED_MATCH" ? "is-selected" : ""}><input type="radio" name="compliance-outcome" value="CONFIRMED_MATCH" checked={outcome === "CONFIRMED_MATCH"} onChange={(event) => setOutcome(event.target.value)} /><strong>Совпадение подтверждено</strong><span>Одобрение останется заблокировано</span></label></div><Field label="Комментарий сотрудника" error={localError}><textarea rows="4" maxLength="1000" value={comment} onChange={(event) => setComment(event.target.value)} /></Field><Button type="submit" busy={busy}>Сохранить результат</Button></form> : <p className="muted">{application.status === "NEEDS_INFO" ? "Проверка приостановлена до получения сведений от клиента." : "Рассмотрение завершено, новый результат сохранить нельзя."}</p>}</section>;
}

function AuditPanel({ id, audit, onError }) {
  const [downloading, setDownloading] = useState("");
  async function download(format) { setDownloading(format); onError(""); try { await api.downloadBankAudit(id, format); } catch (err) { onError(err.message); } finally { setDownloading(""); } }
  const records = audit?.records || [];
  return <CollapsiblePanel className="audit-panel" eyebrow="Контроль" title="Журнал аудита" description="Полный журнал доступен для выгрузки." summary={records.length ? `${records.length} событий` : "Пока нет событий"}>
    <div className="audit-panel__actions"><Button variant="secondary" busy={downloading === "json"} onClick={() => download("json")}>Скачать JSON</Button><Button variant="secondary" busy={downloading === "csv"} onClick={() => download("csv")}>Скачать CSV</Button></div>
    {records.length ? <ol>{records.slice(-12).reverse().map((record) => <li key={record.id}><i /><div><strong>{auditLabels[record.event_type] || "Событие процесса"}</strong><span>{new Date(record.created_at).toLocaleString("ru-RU")} · {auditSourceLabels[record.source] || "Внутренняя система"}</span>{record.event_type === "COMPLIANCE_REVIEW" && <p>{complianceOutcomeLabels[record.payload?.outcome] || "Результат сохранён"}: {record.payload?.comment || "Без комментария"}</p>}{record.event_type === "PIPELINE_ERROR" && <p>Техническая ошибка направлена на ручную проверку.</p>}</div></li>)}</ol> : <EmptyState icon="≡" title="Событий пока нет">Журнал заполнится после обработки заявки.</EmptyState>}
  </CollapsiblePanel>;
}

function AlternativePanel({ application, alternativeSet, busy, onGenerate, onOffer }) {
  const result = application.assessments?.[0]?.result || {};
  const debtBurdenExceeded = (result.hard_stops || []).includes("EXCESSIVE_DEBT_BURDEN") || (result.underwriting?.rules || []).some((rule) => rule.code === "DEBT_BURDEN" && rule.outcome === "REJECT");
  const alternativeNotNeeded = !(result.hard_stops || []).length
    && result.underwriting?.status === "PASS"
    && result.recommendation !== "DECLINE";
  const bki = result.check_reports?.bki;
  const overdueStop = Number(bki?.current_overdue_amount || 0) > 0;
  const generated = alternativeSet?.status && alternativeSet.status !== "NOT_GENERATED";
  const accepted = alternativeSet?.alternatives?.find((item) => item.status === "ACCEPTED");
  const activeOffer = alternativeSet?.active_offer;
  const reviewOpen = application.status === "UNDER_REVIEW";
  const isFinal = ["APPROVED", "REJECTED"].includes(application.status);
  const canGenerate = reviewOpen && !alternativeNotNeeded && !accepted && !activeOffer;
  const helperText = reviewOpen
    ? alternativeNotNeeded
      ? "Исходные условия уже проходят проверки, поэтому менять сумму или срок не требуется."
      : debtBurdenExceeded
        ? "Система может снизить долговую нагрузку меньшей суммой или более долгим сроком."
        : "Система проверит варианты с меньшей ежемесячной нагрузкой."
    : isFinal
      ? "Подбор завершён вместе с рассмотрением заявки. Ниже сохранены рассчитанные варианты."
      : "Подбор приостановлен до получения сведений от клиента.";
  return <section className="panel alternatives">
    <div className="alternatives__heading"><div><h2>Альтернативные условия</h2><p>Клиент запросил {formatMoneyRub(application.requested_amount)} на {application.term_months} мес.</p><p>{helperText}</p><small>Расчётные варианты не являются одобрением.</small></div>{canGenerate && <Button busy={busy} variant="secondary" onClick={onGenerate}>{generated ? "Пересчитать варианты" : "Рассчитать варианты"}</Button>}</div>
    {reviewOpen && alternativeNotNeeded && <Alert type="success" title="Альтернативные условия не требуются">Исходная заявка проходит скоринг и обязательные проверки. Рассчитывать дополнительные варианты не нужно.</Alert>}
    {overdueStop && <Alert title={reviewOpen ? "Просрочка в БКИ не устраняется условиями" : "На момент проверки была просрочка в БКИ"}>{reviewOpen ? "Сначала требуется проверить просрочку." : "Фактор сохранён в результатах проверки заявки."}</Alert>}
    {accepted && <Alert type={application.status === "APPROVED" ? "success" : "info"} title={reviewOpen ? "Клиент принял условия" : "Ответ клиента сохранён"}>{reviewOpen ? `Можно принять решение по сумме ${formatMoneyRub(accepted.amount)} на ${accepted.term_months} мес.` : isFinal ? `Клиент принял вариант на ${formatMoneyRub(accepted.amount)} и ${accepted.term_months} мес. Итог заявки: ${application.status === "APPROVED" ? "одобрена" : "отказ"}.` : `Клиент принял вариант на ${formatMoneyRub(accepted.amount)} и ${accepted.term_months} мес. Рассмотрение продолжится после уточнения данных.`}</Alert>}
    {reviewOpen && activeOffer && <Alert title="Предложение отправлено клиенту">Ожидаем ответ по сумме {formatMoneyRub(activeOffer.amount)}.</Alert>}
    {generated && !alternativeSet.alternatives?.length && !alternativeNotNeeded && <p className="muted">{alternativeSet.reason || "Подходящие варианты не найдены."}</p>}
    {!alternativeNotNeeded && alternativeSet?.alternatives?.length > 0 && <div className="alternatives__list">{alternativeSet.alternatives.map((item) => <article className="alternative-card" key={item.id}><div className="alternative-card__top"><strong>{formatMoneyRub(item.amount)}</strong><span>{item.term_months} мес.</span></div><dl><div><dt>Ставка</dt><dd>{formatPercent(Number(item.annual_interest_rate) / 100)}</dd></div><div><dt>Платёж</dt><dd>{formatMoneyRub(item.monthly_payment)}</dd></div><div><dt>Нагрузка</dt><dd>{formatPercent(item.debt_burden)}</dd></div></dl><p>{item.reason}</p><small>Скоринг: {recommendationLabels[item.evaluation?.scoring?.recommendation] || "—"}; правила: {underwritingLabels[item.evaluation?.underwriting?.status] || "—"}.</small>{item.status === "GENERATED" && reviewOpen && <Button busy={busy} onClick={() => onOffer(item.id)}>Предложить клиенту</Button>}{item.status !== "GENERATED" && <span className={`alternative-status ${item.status === "ACCEPTED" ? "alternative-status--accepted" : ""}`}>{isFinal && item.status === "OFFERED" ? alternativeStatusLabels.SUPERSEDED : alternativeStatusLabels[item.status] || "Статус обновлён"}</span>}</article>)}</div>}
    {accepted && <AcceptedAlternativeReview application={application} offer={accepted} originalAssessment={application.assessments?.[0]} />}
  </section>;
}

function AcceptedAlternativeReview({ application, offer, originalAssessment }) {
  const original = originalAssessment?.result || {}; const rescored = offer.evaluation?.scoring || {};
  const isFinal = ["APPROVED", "REJECTED"].includes(application.status);
  return <section className="accepted-review"><div className="accepted-review__heading"><span className="eyebrow eyebrow--red">Клиент принял предложение</span><h2>{isFinal ? "Условия, рассмотренные банком" : "Новые условия для итогового решения"}</h2></div><div className="accepted-review__comparison"><div className="accepted-review__side accepted-review__side--original"><small>Исходная заявка</small><strong><s>{formatMoneyRub(application.requested_amount)}</s></strong><span><s>{application.term_months} мес.</s></span><dl><div><dt>Платёж</dt><dd><s>{formatMoneyRub(original.features?.new_monthly_payment)}</s></dd></div><div><dt>Балл</dt><dd><s>{original.score ?? "—"} / 100</s></dd></div></dl></div><span className="accepted-review__arrow">→</span><div className="accepted-review__side accepted-review__side--accepted"><small>Принятый вариант</small><strong>{formatMoneyRub(offer.amount)}</strong><span>{offer.term_months} мес.</span><dl><div><dt>Платёж</dt><dd>{formatMoneyRub(offer.monthly_payment)}</dd></div><div><dt>Балл</dt><dd>{rescored.score ?? "—"} / 100</dd></div></dl></div></div></section>;
}

function AIAnalysisPanel({ result, loading, error, onAnalyze, hasAssessment, inactive }) {
  const mandatoryBlock = (result?.blocking_reasons || []).some((reason) => !reason.startsWith("Оценка неполная:"));
  return <section className={`panel ai-analysis${inactive ? " ai-analysis--inactive" : ""}`}>
    <div className="panel-title"><div><span className="eyebrow eyebrow--red">Локальная Ollama</span><h2>Пояснение скоринга с помощью ИИ</h2><p>Анализ опирается на текущую оценку и не меняет баллы, проверки, статус или решение сотрудника.</p></div></div>
    {inactive && <p className="ai-analysis__inactive-note">{result ? "Рассмотрение завершено. Сохранённый анализ доступен только для просмотра; повторный анализ отключён." : "Рассмотрение завершено. Новый ИИ-анализ недоступен."}</p>}
    <Button variant="secondary" busy={loading} disabled={inactive || !hasAssessment || loading || Boolean(result)} onClick={onAnalyze}>
      {inactive ? "Заявка закрыта — анализ недоступен" : loading ? "Анализируем заявку…" : result ? "Анализ уже выполнен" : "Проанализировать скоринг с помощью ИИ"}
    </Button>
    {error && !inactive && <><Alert type="error" title="Не удалось выполнить анализ">{error}</Alert><Button variant="ghost" disabled={loading} onClick={onAnalyze}>Повторить анализ</Button></>}
    {loading && !inactive && <p role="status" className="muted">Ожидаем ответ локальной модели. Повторный запуск заблокирован до завершения запроса.</p>}
    {result && <div className="ai-analysis__result">
      <p className="ai-analysis__meta">Последний анализ: {new Date(result.analyzed_at).toLocaleString("ru-RU")}</p>
      <div className={`ai-analysis__brief${mandatoryBlock ? " ai-analysis__brief--blocked" : ""}`}>
        <h3>{mandatoryBlock ? "Обязательное ограничение" : "Кратко о заявке"}</h3>
        <p>{localizeAiText(result.summary)}</p>
      </div>
    </div>}
    {!hasAssessment && <p className="muted">Для анализа нужна сохранённая оценка заявки.</p>}
  </section>;
}

const aiFactLabels = {
  LOW: "низкий", MEDIUM: "средний", HIGH: "высокий", UNKNOWN: "не определён",
  APPROVE: "положительная рекомендация скоринга, не итоговое решение", REVIEW: "нужно дополнительное рассмотрение",
  DECLINE: "отрицательная рекомендация скоринга, не итоговое решение", REQUEST_INFO: "нужно запросить сведения",
  PASS: "пройдена", FAIL: "не пройдена", CLEAR: "совпадений нет", AVAILABLE: "данные получены",
  NO_HISTORY: "кредитной истории нет", UNAVAILABLE: "источник недоступен", ERROR: "техническая ошибка источника",
  POTENTIAL_MATCH: "возможное совпадение", CONFIRMED_MATCH: "совпадение подтверждено",
  COMPLETED: "оценка завершена", INSUFFICIENT_DATA: "недостаточно данных",
};
function localizeAiText(text) {
  const translations = { ...aiFactLabels, ...reasonCodeLabels };
  const tokens = Object.keys(translations).sort((left, right) => right.length - left.length).join("|");
  return text.replace(new RegExp(`\\b(${tokens})\\b`, "g"), (token) => translations[token] || token);
}

function AssessmentSummary({ assessment }) {
  if (!assessment) return <CollapsiblePanel eyebrow="Оценка" title="Скоринг и объяснения"><p className="muted">Оценка пока не сформирована.</p></CollapsiblePanel>;
  const result = assessment.result || {}; const features = result.features || {}; const inputData = assessment.input_snapshot?.input_data || result.input_snapshot?.input_data || {}; const checks = assessment.input_snapshot?.checks || result.input_snapshot?.checks || [];
  return <CollapsiblePanel className="assessment" eyebrow="Оценка" title="Скоринг и объяснения" description="Демонстрационная оценка помогает сотруднику и не является итоговым решением." summary={<><span className="assessment__status">{assessmentStatuses[result.assessment_status] || "Статус неизвестен"}</span><b className="assessment__score-label">Балл: {result.score ?? "—"} · риск {riskLabels[result.risk_level] || "не определён"}</b></>}>
    <div className="assessment__summary"><div className="assessment__score"><small>Балл</small><strong>{result.score ?? "—"}<span>{result.score === null || result.score === undefined ? "" : " / 100"}</span></strong><small>Риск: {riskLabels[result.risk_level] || "Не определён"}</small></div><div><small>Рекомендация скоринга</small><strong>{recommendationLabels[result.recommendation] || "Не сформирована"}</strong></div></div>
    {result.reasons?.length > 0 && <div className="assessment__section"><h3>Причины рекомендации</h3><ul>{result.reasons.map((reason, index) => <li key={`${reason.code || "reason"}-${index}`}>{recommendationReason(reason)}</li>)}</ul></div>}
    {result.factors?.length > 0 && <div className="assessment__section"><h3>Факторы балла</h3><div className="assessment__factors">{result.factors.map((factor) => <article key={factor.code}><div><strong>{factorLabels[factor.code] || "Дополнительный фактор"}</strong><b>{factor.points} из {factor.max_points}</b></div><p>{factor.explanation || "Фактор учтён при расчёте балла."}</p>{factor.code === "OPERATING_MARGIN" && <AssessmentFormula title="Операционная маржа" formula="(выручка − расходы) / выручка" values={`(${formatMoney(inputData.average_monthly_revenue)} − ${formatMoney(inputData.average_monthly_operating_expenses)}) / ${formatMoney(inputData.average_monthly_revenue)} = ${formatPercent(features.operating_margin)}`} />}{factor.code === "DEBT_BURDEN" && <AssessmentFormula title="Долговая нагрузка" formula="(текущие платежи + новый платёж) / прибыль" values={formatPercent(features.debt_burden)} />}</article>)}</div></div>}
    {checks.length > 0 && <div className="assessment__section"><h3>Входные проверки скоринга</h3><div className="assessment__checks">{checks.map((check) => <div key={check.source}><strong>{checkLabels[check.source] || "Дополнительная проверка"}</strong><span className={`assessment__check assessment__check--${String(check.status).toLowerCase()}`}>{checkStatuses[check.status] || "Статус получен"}</span><small>{checkReasonLabels[check.reason_code] || "Результат проверки получен"}</small></div>)}</div></div>}
    {result.hard_stops?.length > 0 && <div className="assessment__stops"><strong>Обязательные ограничения</strong><ul>{result.hard_stops.map((code) => <li key={code}>{reasonCodeLabels[code] || recommendationReason(result.reasons?.find((reason) => reason.code === code))}</li>)}</ul></div>}
  </CollapsiblePanel>;
}
function AssessmentFormula({ title, formula, values }) { return <div className="assessment__calculation"><strong>{title}</strong><span>{formula}</span><b>{values}</b></div>; }
