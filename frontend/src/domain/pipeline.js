const COMPLIANCE_RULES = new Set([
  "COMPLIANCE_POTENTIAL_MATCH",
  "COMPLIANCE_CONFIRMED_MATCH",
  "COMPLIANCE_ERROR",
]);

export function requiresComplianceReview(assessment) {
  const rules = assessment?.result?.underwriting?.rules || [];
  return rules.some((rule) => COMPLIANCE_RULES.has(rule.code));
}

export function latestComplianceReview(audit, assessmentId) {
  return [...(audit?.records || [])].reverse().find((record) => (
    record.event_type === "COMPLIANCE_REVIEW"
      && (!assessmentId || record.payload?.assessment_id === assessmentId)
  )) || null;
}

export function approvalBlockReason(application, assessment, complianceReview) {
  if (application?.status !== "UNDER_REVIEW") return "Решение уже принято или заявка ожидает действий клиента.";
  if (!assessment) return "Нет актуальной оценки заявки.";
  const result = assessment.result || {};
  if (result.assessment_status !== "COMPLETED" || result.missing_fields?.length) {
    return "Оценка не завершена: сначала нужно получить недостающие данные.";
  }
  if (result.hard_stops?.length) return "Есть обязательное ограничение, которое не позволяет одобрить заявку.";
  const underwriting = result.underwriting || {};
  if (underwriting.status === "PASS") return "";
  const reviewRules = (underwriting.rules || []).filter((rule) => rule.outcome === "REVIEW");
  const hasReject = (underwriting.rules || []).some((rule) => rule.outcome === "REJECT");
  const onlyComplianceReview = reviewRules.length > 0
    && reviewRules.every((rule) => COMPLIANCE_RULES.has(rule.code));
  if (!hasReject && onlyComplianceReview && complianceReview?.payload?.outcome === "CLEAR") return "";
  if (requiresComplianceReview(assessment) && complianceReview?.payload?.outcome !== "CLEAR") {
    return "Сначала завершите ручной разбор Compliance с исходом «Совпадение снято».";
  }
  return "Underwriting не пройден: одобрение недоступно до устранения причин.";
}
