import test from "node:test";
import assert from "node:assert/strict";
import { approvalBlockReason, latestComplianceReview, requiresComplianceReview } from "../src/domain/pipeline.js";

test("approval waits for a current manual compliance clearance", () => {
  const application = { status: "UNDER_REVIEW" };
  const assessment = { id: "assessment-1", result: {
    assessment_status: "COMPLETED", hard_stops: [], missing_fields: [],
    underwriting: { status: "REVIEW", rules: [{ code: "COMPLIANCE_ERROR", outcome: "REVIEW" }] },
  } };
  assert.equal(requiresComplianceReview(assessment), true);
  assert.match(approvalBlockReason(application, assessment, null), /комплаенс/);
  const audit = { records: [{ event_type: "COMPLIANCE_REVIEW", payload: { assessment_id: "assessment-1", outcome: "CLEAR" } }] };
  const review = latestComplianceReview(audit, assessment.id);
  assert.equal(approvalBlockReason(application, assessment, review), "");
});

test("approval stays blocked for underwriting reject rules", () => {
  const assessment = { result: {
    assessment_status: "COMPLETED", hard_stops: [], missing_fields: [],
    underwriting: { status: "REJECT", rules: [{ code: "DEBT_BURDEN", outcome: "REJECT" }] },
  } };
  assert.match(approvalBlockReason({ status: "UNDER_REVIEW" }, assessment, null), /Правила кредитования/);
});
