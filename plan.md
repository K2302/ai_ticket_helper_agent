## Plan: Human-First Fintech Triage v1

Make deterministic decision tree and hard policy rules the primary fintech decision engine, keep LLM strictly assistive for extraction/explanation only, and default uncertain/high-risk cases to human escalation with auditable reason codes and policy versions for replay.

**Steps**
1. Phase 0 - Lock human-first decision contract (blocks all implementation). Define canonical outputs in triage path: `APPROVE`, `REVIEW`, `BLOCK`; require `reason_code`, `risk_score`, `rule_version`, `prompt_version`, `model_version`, `feature_snapshot_hash` on every decision.
2. Phase 1 - Build deterministic-first policy engine (depends on 1). Add Tier-0 hard rules executed before LLM: sanctions/watchlist hits, impossible travel, velocity caps, auth-failure bursts, device compromise indicators. Tier-0 may directly return `BLOCK`/`REVIEW` and skip LLM.
3. Phase 2 - Keep LLM assistive only (depends on 1, parallel with 2). Limit LLM responsibility to structured classification/explanation features; never allow direct final decision write. Enforce strict schema validation and enum-only output; invalid response auto-fallback to rules.
4. Phase 3 - Human-first routing matrix (depends on 2 and 3). Replace single threshold with decision matrix using segment-aware thresholds and operating mode. Default mode for fintech v1: `strict_review` where uncertainty and high-value/high-risk segments bias to `REVIEW`.
5. Phase 4 - Structured human review reasons and learning loop (depends on 4). Expand review flow so each manual decision records standardized `reason_code` and override metadata; store correction deltas for threshold tuning and prompt/rule updates.
6. Phase 5 - Audit and replay integrity (depends on 1, parallel with 4-5). Persist immutable decision evidence including input feature hash, policy versions, and reviewer actions so compliance can replay any case.
7. Phase 6 - Reliability fail-safe modes (depends on 2-4). If LLM timeout/parse error/rate limit, force rules-only degraded mode with increased review bias. Add explicit backlog guardrails: when queue latency breaches SLA, auto-route defined low-risk segments while preserving strict review for high-risk segments.
8. Phase 7 - Controlled rollout for policy and threshold changes (depends on 3-6). Run shadow mode on live traffic, compare disagreement vs baseline, then canary by segment with rollback triggers tied to false-positive proxy and review queue growth.

**Relevant files**
- /home/kaushik.deka@psnet.com/prod-grad/ai-huamn-checker/services/ai-triage/app/services/triage_service.py — enforce deterministic-before-LLM orchestration and final decision contract writes.
- /home/kaushik.deka@psnet.com/prod-grad/ai-huamn-checker/services/ai-triage/app/services/confidence.py — replace single cutoff with human-first matrix and segment thresholds.
- /home/kaushik.deka@psnet.com/prod-grad/ai-huamn-checker/services/ai-triage/app/services/escalation.py — promote fintech risk triggers into explicit review/block reasons.
- /home/kaushik.deka@psnet.com/prod-grad/ai-huamn-checker/services/ai-triage/app/services/openrouter_triage.py — strict LLM schema validation, enum constraints, timeout/fallback telemetry.
- /home/kaushik.deka@psnet.com/prod-grad/ai-huamn-checker/services/ai-triage/app/services/human_review_service.py — enforce reviewer reason codes and override governance.
- /home/kaushik.deka@psnet.com/prod-grad/ai-huamn-checker/services/ai-triage/app/services/feedback_service.py — capture correction taxonomy for calibration loop.
- /home/kaushik.deka@psnet.com/prod-grad/ai-huamn-checker/services/ai-triage/app/infrastructure/repositories.py — persist evidence fields, reason codes, and replay metadata.
- /home/kaushik.deka@psnet.com/prod-grad/ai-huamn-checker/services/ai-triage/app/infrastructure/kafka_consumer.py — degraded-mode handling and queue/backlog metrics.
- /home/kaushik.deka@psnet.com/prod-grad/ai-huamn-checker/schema/phase2_3.sql — add risk decision, reason codes, policy/version/evidence columns.
- /home/kaushik.deka@psnet.com/prod-grad/ai-huamn-checker/schema/phase4.sql — strengthen immutable audit trail and retention controls.

**Verification**
1. Deterministic precedence tests: ensure Tier-0 hard rules always override LLM outputs.
2. Schema validation tests: malformed/out-of-enum LLM JSON must never produce direct decisions.
3. Human-first behavior tests: strict mode sends ambiguous/high-risk segment cases to `REVIEW` at expected rates.
4. Calibration tests: per-segment thresholds improve reviewer-corrected precision without breaching false-negative guardrails.
5. Degraded-mode tests: LLM outages keep system operating with rules-only + elevated review bias.
6. Shadow/canary tests: new policy rollout must pass disagreement, queue-SLA, and false-positive proxy gates before promotion.

**Decisions**
- Included: fintech v1 human-first governance where automation assists and humans arbitrate uncertain/high-risk cases.
- Excluded: fully autonomous LLM approve/block pipeline.
- Assumption: compliance requires reproducible evidence for every automated and human-adjusted decision.
- Assumption: v1 can accept higher review volume to reduce high-severity misses.

**Further Considerations**
1. Review capacity policy: choose hard cap and overflow strategy (`auto-approve low risk` vs `defer non-critical`) before rollout.
2. Reason code taxonomy owner: assign risk-ops owner to maintain enum stability across rules, LLM prompt, and reviewer UI.
3. Segment defaults: start strict for new accounts/high-value/cross-border, then relax only after calibration evidence.