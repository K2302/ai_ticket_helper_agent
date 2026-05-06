## Plan: Human-First Fintech Triage v1

Make deterministic decision tree and hard policy rules the primary fintech decision engine, keep LLM strictly assistive for extraction/explanation only, and default uncertain/high-risk cases to human escalation with auditable reason codes and policy versions for replay.

**Steps**
1. Phase 0 - Lock human-first decision contract (blocks all implementation). Define canonical outputs in triage path: `APPROVE`, `REVIEW`, `BLOCK`; require `reason_code`, `risk_score`, `rule_version`, `prompt_version`, `model_version`, `feature_snapshot_hash` on every decision.
2. Phase 1 - Build deterministic-first policy engine (depends on 1). Add Tier-0 hard rules executed before LLM: sanctions/watchlist hits, impossible travel, velocity caps, auth-failure bursts, device compromise indicators. Tier-0 may directly return `BLOCK`/`REVIEW` and skip LLM.
3. Phase 2 - Keep LLM assistive only (depends on 1, parallel with 2). Limit LLM responsibility to structured classification/explanation features; never allow direct final decision write. Enforce strict schema validation and enum-only output; invalid response auto-fallback to rules.
4. Phase 3 - Human-first routing matrix (depends on 2 and 3). Replace single threshold with decision matrix using segment-aware thresholds and operating mode. Default mode for fintech v1: `strict_review` where uncertainty and high-value/high-risk segments bias to `REVIEW`.
5. Phase 3.5 - Config-driven 6-node hierarchical decision tree (LLM prompt injection). Replace flat if-else classifier with a versioned tree (`triage_tree.py`). Tree JSON injected verbatim into the LLM system message so the model follows the same node sequence as deterministic rules. LLM must return `decision_path` (list of visited node ids) as an auditable reasoning trace. Invalid/hallucinated `decision_path` triggers rules-only fallback. Deterministic `evaluate_tree()` used in `TicketClassifier.classify_with_tree()` for the LLM-unavailable path. `RoutingEngine` accepts `target_team_hint` from tree leaf for config-driven team assignment.
6. Phase 4 - Structured human review reasons and learning loop (depends on 4). Expand review flow so each manual decision records standardized `reason_code` and override metadata; store correction deltas for threshold tuning and prompt/rule updates.
7. Phase 5 - Audit and replay integrity (depends on 1, parallel with 4-5). Persist immutable decision evidence including input feature hash, policy versions, and reviewer actions so compliance can replay any case.
8. Phase 6 - Reliability fail-safe modes (depends on 2-4). If LLM timeout/parse error/rate limit, force rules-only degraded mode with increased review bias. Add explicit backlog guardrails: when queue latency breaches SLA, auto-route defined low-risk segments while preserving strict review for high-risk segments.
9. Phase 7 - Controlled rollout for policy and threshold changes (depends on 3-6). Run shadow mode on live traffic, compare disagreement vs baseline, then canary by segment with rollback triggers tied to false-positive proxy and review queue growth.

**Decision Tree Design (Phase 3.5)**

The tree is defined as a versioned JSON config (`TRIAGE_TREE` in `triage_tree.py`) and injected into the LLM system prompt unchanged. This makes the prompt config-driven — updating the tree updates both the LLM prompt and the deterministic fallback simultaneously.

```
Node 1  Identity & Access          — locked out / password reset / MFA / 403
         YES → Account Support (terminal)
         NO  → Node 2

Node 2  Financial / Commercial     — refund / invoice / pricing / subscription
         YES → Node 3
         NO  → Node 4

Node 3  Billing Depth (child of 2) — failed payment / overcharge
         YES → Billing Support, Priority HIGH (revenue at risk, terminal)
         NO  → Billing Support, Priority MEDIUM (terminal)

Node 4  System Health              — 500 error / system down / API timeout / latency
         YES → Engineering L1, Priority HIGH (critical, terminal)
         NO  → Node 5

Node 5  Product / Feature          — how-to / feature request / documentation
         YES → Product & Success, Priority LOW (terminal)
         NO  → Node 6

Node 6  Sentiment / Urgency filter — cancel / furious / legal action / leaving
         YES → EscalationRisk.HIGH override regardless of category (terminal)
         NO  → maintain default routing (terminal)
```

**Audit trail**: the LLM returns `decision_path` (e.g. `[1, 2, 3]`) which is stored in `audit_logs.details` and `human_review_queue.triage_snapshot` on every processed ticket. Invalid paths → rules fallback; the fallback also records its own deterministic path.

**Relevant files**
- `services/ai-triage/app/services/triage_tree.py` — tree config dict (`TRIAGE_TREE`), deterministic `evaluate_tree()`, `validate_decision_path()`, `TreeDecision` dataclass.
- `services/ai-triage/app/services/classifier.py` — `TicketClassifier.classify_with_tree()` uses `evaluate_tree()`; `classify()` kept for back-compat.
- `services/ai-triage/app/services/openrouter_triage.py` — tree JSON injected in system message; `decision_path` added to required schema; `LlmTriageFeatures.decision_path` field.
- `services/ai-triage/app/services/routing.py` — `route()` accepts `target_team_hint` from tree leaf; validated against known team set before use.
- `services/ai-triage/app/services/triage_service.py` — rules path calls `classify_with_tree()`; `decision_path` propagated to audit log and human review snapshot.
- `services/ai-triage/app/services/confidence.py` — segment-aware thresholds and strict_review bias.
- `services/ai-triage/app/services/policy_engine.py` — Tier-0 and Tier-1 hard rules (run before / after tree).
- `services/ai-triage/app/services/risk_service.py` — fuses signals into APPROVE/REVIEW/BLOCK with full evidence.
- `services/ai-triage/app/infrastructure/repositories.py` — persists evidence fields including `rule_version`, `prompt_version`.
- `schema/phase2_3.sql` — triage_results, risk_decisions, human_review_queue tables.
- `schema/phase4.sql` — feedback_corrections, audit_logs, threshold_config, kill_switch, replay tables.

**Verification**
1. Deterministic precedence: Tier-0 hard rules always override tree output and LLM output.
2. Decision path validation: LLM-reported paths with invalid node order or out-of-range ids must trigger rules fallback.
3. Tree consistency: `evaluate_tree()` and LLM path should agree on the same leaf for canonical test cases.
4. Human-first behavior: strict_review mode sends ambiguous/high-risk segment cases to REVIEW at expected rates.
5. Degraded mode: LLM outage keeps system operating via `evaluate_tree()` with elevated review bias.

**Decisions**
- Included: fintech v1 human-first governance where automation assists and humans arbitrate uncertain/high-risk cases.
- Excluded: fully autonomous LLM approve/block pipeline.
- Excluded: tree nodes that mutate state or write decisions (LLM is feature-extraction only).
- Assumption: compliance requires reproducible evidence for every automated and human-adjusted decision.
- Assumption: v1 can accept higher review volume to reduce high-severity misses.

**Further Considerations**
1. Tree versioning: bump `TREE_VERSION` and `PROMPT_VERSION` together whenever a node changes; old decisions remain replayable against the version they were made with.
2. Node expansion: adding nodes (e.g. regulatory/KYC node between 2 and 3) requires updating `TRIAGE_TREE`, `validate_decision_path()` valid set, and the deterministic keyword sets.
3. Review capacity policy: choose hard cap and overflow strategy before rollout.
4. Segment defaults: start strict for new accounts/high-value/cross-border, then relax only after calibration evidence.
