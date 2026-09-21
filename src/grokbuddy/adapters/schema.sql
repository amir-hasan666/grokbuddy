CREATE TABLE IF NOT EXISTS actors (id TEXT PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)),
 role TEXT GENERATED ALWAYS AS (json_extract(data,'$.role')) STORED NOT NULL CHECK(role IN ('BUILDER','REVIEWER','HUMAN','SYSTEM')),
 provider_id TEXT GENERATED ALWAYS AS (json_extract(data,'$.provider_id')) STORED NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)),
 state TEXT GENERATED ALWAYS AS (json_extract(data,'$.state')) STORED NOT NULL CHECK(state IN ('NEW','PLANNING','PLAN_REVIEW_PENDING','PLAN_REVIEWING','PLAN_CHANGES_REQUIRED','PLAN_HUMAN_REVIEW','PLAN_APPROVED','EXECUTING','SELF_TESTING','FINAL_REVIEW_PENDING','FINAL_REVIEWING','FINAL_CHANGES_REQUIRED','FINAL_HUMAN_REVIEW','AWAITING_HUMAN_APPROVAL','BLOCKED','ESCALATED','FAILED','CANCELLED','DONE')),
 version INTEGER GENERATED ALWAYS AS (json_extract(data,'$.version')) STORED NOT NULL CHECK(version >= 0),
 owner_id TEXT GENERATED ALWAYS AS (json_extract(data,'$.owner_id')) STORED NOT NULL REFERENCES actors(id),
 CHECK(json_type(data,'$.revision_round') IS NULL OR
       (json_type(data,'$.revision_round')='integer' AND
        json_extract(data,'$.revision_round')>=0)),
 CHECK(json_extract(data,'$.completion_basis') IS NULL OR
       json_extract(data,'$.completion_basis') IN ('FINAL_REVIEW_PASS','HUMAN_OVERRIDE')));
-- Expression indexes also apply to existing v3 databases without rewriting tasks.
CREATE UNIQUE INDEX IF NOT EXISTS one_active_conversation_task
 ON tasks(json_extract(data,'$.conversation_id'))
 WHERE json_extract(data,'$.conversation_id') IS NOT NULL
   AND json_extract(data,'$.state') NOT IN ('DONE','CANCELLED','FAILED');
CREATE UNIQUE INDEX IF NOT EXISTS one_trigger_message_per_conversation
 ON tasks(json_extract(data,'$.conversation_id'),json_extract(data,'$.trigger_message_id'))
 WHERE json_extract(data,'$.conversation_id') IS NOT NULL
   AND json_extract(data,'$.trigger_message_id') IS NOT NULL;
CREATE TABLE IF NOT EXISTS artifacts (id TEXT PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)),
 task_id TEXT GENERATED ALWAYS AS (json_extract(data,'$.task_id')) STORED NOT NULL REFERENCES tasks(id));
CREATE TABLE IF NOT EXISTS review_profiles (id TEXT PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)));
CREATE TABLE IF NOT EXISTS review_requests (id TEXT PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)),
 task_id TEXT GENERATED ALWAYS AS (json_extract(data,'$.task_id')) STORED NOT NULL REFERENCES tasks(id),
 status TEXT GENERATED ALWAYS AS (json_extract(data,'$.status')) STORED NOT NULL CHECK(status IN ('PENDING','IN_PROGRESS','COMPLETED','FAILED','TIMED_OUT','ESCALATED')),
 review_id TEXT GENERATED ALWAYS AS (json_extract(data,'$.review_id')) STORED NOT NULL UNIQUE,
 review_type TEXT GENERATED ALWAYS AS (json_extract(data,'$.review_type')) STORED NOT NULL CHECK(review_type IN ('PLAN_REVIEW','FINAL_REVIEW')),
 review_round INTEGER GENERATED ALWAYS AS (json_extract(data,'$.review_round')) STORED NOT NULL CHECK(review_round>0),
 input_artifact_id TEXT GENERATED ALWAYS AS (json_extract(data,'$.input_artifact_id')) STORED NOT NULL REFERENCES artifacts(id),
 UNIQUE(task_id,review_type,review_round));
CREATE UNIQUE INDEX IF NOT EXISTS one_active_request ON review_requests(task_id) WHERE status IN ('PENDING','IN_PROGRESS');
CREATE INDEX IF NOT EXISTS request_status ON review_requests(status);
CREATE TABLE IF NOT EXISTS review_rounds (id TEXT PRIMARY KEY REFERENCES review_requests(id), data TEXT NOT NULL CHECK(json_valid(data)));
CREATE TABLE IF NOT EXISTS reviews (id TEXT PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)),
 request_id TEXT GENERATED ALWAYS AS (json_extract(data,'$.review_request_id')) STORED NOT NULL UNIQUE REFERENCES review_requests(id));
CREATE TABLE IF NOT EXISTS review_findings (id TEXT PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)),
 task_id TEXT GENERATED ALWAYS AS (json_extract(data,'$.task_id')) STORED NOT NULL REFERENCES tasks(id),
 review_id TEXT GENERATED ALWAYS AS (json_extract(data,'$.review_id')) STORED NOT NULL REFERENCES reviews(id),
 external_key TEXT GENERATED ALWAYS AS (json_extract(data,'$.external_finding_key')) STORED NOT NULL,
 status TEXT GENERATED ALWAYS AS (json_extract(data,'$.status')) STORED NOT NULL CHECK(status IN ('OPEN','ACCEPTED','REJECTED_WITH_EVIDENCE','FIXED','VERIFIED','WAIVED_BY_HUMAN')),
 UNIQUE(review_id,external_key));
CREATE INDEX IF NOT EXISTS finding_task_status ON review_findings(task_id,status);
CREATE TABLE IF NOT EXISTS human_approvals (id TEXT PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)),
 task_id TEXT GENERATED ALWAYS AS (json_extract(data,'$.task_id')) STORED NOT NULL REFERENCES tasks(id),
 status TEXT GENERATED ALWAYS AS (json_extract(data,'$.status')) STORED NOT NULL CHECK(status IN ('PENDING','APPROVED','REJECTED','EXPIRED','CONSUMED')));
CREATE TABLE IF NOT EXISTS outbox_events (id TEXT PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)),
 request_id TEXT GENERATED ALWAYS AS (json_extract(data,'$.review_request_id')) STORED NOT NULL UNIQUE REFERENCES review_requests(id));
CREATE TABLE IF NOT EXISTS inbox_events (id TEXT PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)));
CREATE TABLE IF NOT EXISTS processed_events (id TEXT PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)));
CREATE TABLE IF NOT EXISTS command_receipts (id TEXT PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)));
CREATE TABLE IF NOT EXISTS mock_jobs (id TEXT PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)));
CREATE TABLE IF NOT EXISTS task_events (id TEXT PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)),
 task_id TEXT GENERATED ALWAYS AS (json_extract(data,'$.task_id')) STORED NOT NULL REFERENCES tasks(id));
CREATE TABLE IF NOT EXISTS finding_events (id TEXT PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)),
 finding_id TEXT GENERATED ALWAYS AS (json_extract(data,'$.finding_id')) STORED NOT NULL REFERENCES review_findings(id));
CREATE TABLE IF NOT EXISTS approval_events (id TEXT PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)),
 approval_id TEXT GENERATED ALWAYS AS (json_extract(data,'$.approval_id')) STORED NOT NULL REFERENCES human_approvals(id));
CREATE TABLE IF NOT EXISTS audit_logs (id TEXT PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)));
CREATE TABLE IF NOT EXISTS github_bindings (id TEXT PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)),
 repository_id INTEGER GENERATED ALWAYS AS (json_extract(data,'$.repository_id')) STORED NOT NULL,
 pull_request_number INTEGER GENERATED ALWAYS AS (json_extract(data,'$.pull_request_number')) STORED NOT NULL,
 task_id TEXT GENERATED ALWAYS AS (json_extract(data,'$.task_id')) STORED NOT NULL UNIQUE REFERENCES tasks(id),
 UNIQUE(repository_id,pull_request_number));
CREATE TABLE IF NOT EXISTS grok_reviewer_routes (id TEXT PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)),
 task_id TEXT GENERATED ALWAYS AS (json_extract(data,'$.task_id')) STORED NOT NULL UNIQUE REFERENCES tasks(id),
 reviewer_actor_id TEXT GENERATED ALWAYS AS (json_extract(data,'$.reviewer_actor_id')) STORED NOT NULL REFERENCES actors(id));
CREATE TABLE IF NOT EXISTS github_events (id TEXT PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)),
 delivery_id TEXT GENERATED ALWAYS AS (json_extract(data,'$.delivery_id')) STORED NOT NULL UNIQUE,
 event_name TEXT GENERATED ALWAYS AS (json_extract(data,'$.event_name')) STORED NOT NULL,
 raw_sha256 TEXT GENERATED ALWAYS AS (json_extract(data,'$.raw_sha256')) STORED NOT NULL,
 canonical_key TEXT GENERATED ALWAYS AS (json_extract(data,'$.canonical_key')) STORED NOT NULL,
 status TEXT GENERATED ALWAYS AS (json_extract(data,'$.status')) STORED NOT NULL);
CREATE INDEX IF NOT EXISTS github_events_canonical_key ON github_events(canonical_key);
CREATE INDEX IF NOT EXISTS github_events_status ON github_events(status);
CREATE TABLE IF NOT EXISTS github_comment_projections (id TEXT PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)),
 review_id TEXT GENERATED ALWAYS AS (json_extract(data,'$.review_id')) STORED NOT NULL UNIQUE REFERENCES reviews(id),
 task_id TEXT GENERATED ALWAYS AS (json_extract(data,'$.task_id')) STORED NOT NULL REFERENCES tasks(id),
 status TEXT GENERATED ALWAYS AS (json_extract(data,'$.status')) STORED NOT NULL);
CREATE INDEX IF NOT EXISTS github_comment_projection_status ON github_comment_projections(status);
-- Step 6.2: a Worker assignment belongs to the same Task without transferring owner_id.
CREATE TABLE IF NOT EXISTS worker_assignments (id TEXT PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)),
 task_id TEXT GENERATED ALWAYS AS (json_extract(data,'$.task_id')) STORED NOT NULL REFERENCES tasks(id),
 generation INTEGER GENERATED ALWAYS AS (json_extract(data,'$.generation')) STORED NOT NULL CHECK(generation>0),
 status TEXT GENERATED ALWAYS AS (json_extract(data,'$.status')) STORED NOT NULL
   CHECK(status IN ('OFFERED','CLAIMED','COMPLETED','FROZEN','CANCELLED')),
 worker_principal_id TEXT GENERATED ALWAYS AS (json_extract(data,'$.worker_principal_id')) STORED REFERENCES actors(id),
 lease_generation INTEGER GENERATED ALWAYS AS (json_extract(data,'$.lease_generation')) STORED NOT NULL CHECK(lease_generation>=0),
 lease_until INTEGER GENERATED ALWAYS AS (json_extract(data,'$.lease_until')) STORED NOT NULL CHECK(lease_until>=0),
 approved_plan_artifact_id TEXT GENERATED ALWAYS AS (json_extract(data,'$.approved_plan_artifact_id')) STORED NOT NULL REFERENCES artifacts(id),
 approved_plan_hash TEXT GENERATED ALWAYS AS (json_extract(data,'$.approved_plan_hash')) STORED NOT NULL CHECK(length(approved_plan_hash)=64),
 approved_scope_hash TEXT GENERATED ALWAYS AS (json_extract(data,'$.approved_scope_hash')) STORED NOT NULL CHECK(length(approved_scope_hash)=64),
 completion_artifact_id TEXT GENERATED ALWAYS AS (json_extract(data,'$.completion_artifact_id')) STORED REFERENCES artifacts(id),
 CHECK(COALESCE(json_type(data,'$.approved_scope'),'')='object'),
 CHECK(json_type(data,'$.lease_token') IS NULL OR json_type(data,'$.lease_token') IN ('null','text')),
 CHECK((completion_artifact_id IS NULL AND json_extract(data,'$.completion_hash') IS NULL) OR
       (completion_artifact_id IS NOT NULL AND length(json_extract(data,'$.completion_hash'))=64)),
 UNIQUE(task_id,generation));
CREATE UNIQUE INDEX IF NOT EXISTS one_live_worker_assignment ON worker_assignments(task_id)
 WHERE status IN ('OFFERED','CLAIMED');
CREATE INDEX IF NOT EXISTS worker_assignment_recovery ON worker_assignments(status,lease_until);
CREATE TABLE IF NOT EXISTS intake_receipts (id TEXT PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)),
 review_request_id TEXT GENERATED ALWAYS AS (json_extract(data,'$.review_request_id')) STORED NOT NULL REFERENCES review_requests(id),
 source TEXT GENERATED ALWAYS AS (json_extract(data,'$.source')) STORED NOT NULL,
 deduplication_key TEXT GENERATED ALWAYS AS (json_extract(data,'$.deduplication_key')) STORED NOT NULL,
 reviewer_actor_id TEXT GENERATED ALWAYS AS (json_extract(data,'$.reviewer_actor_id')) STORED NOT NULL REFERENCES actors(id),
 input_hash TEXT GENERATED ALWAYS AS (json_extract(data,'$.input_hash')) STORED NOT NULL CHECK(length(input_hash)=64),
 profile_hash TEXT GENERATED ALWAYS AS (json_extract(data,'$.profile_hash')) STORED NOT NULL CHECK(length(profile_hash)=64),
 status TEXT GENERATED ALWAYS AS (json_extract(data,'$.status')) STORED NOT NULL
   CHECK(status IN ('READY','LEASED','ACKED','UNKNOWN','FAILED')),
 lease_generation INTEGER GENERATED ALWAYS AS (json_extract(data,'$.lease_generation')) STORED NOT NULL CHECK(lease_generation>=0),
 lease_until INTEGER GENERATED ALWAYS AS (json_extract(data,'$.lease_until')) STORED NOT NULL CHECK(lease_until>=0),
 UNIQUE(source,deduplication_key));
CREATE INDEX IF NOT EXISTS intake_receipt_recovery ON intake_receipts(status,json_extract(data,'$.lease_until'));
CREATE UNIQUE INDEX IF NOT EXISTS projection_review_binding ON github_comment_projections
 (json_extract(data,'$.review_id'),json_extract(data,'$.binding_id'));
CREATE INDEX IF NOT EXISTS projection_recovery ON github_comment_projections
 (status,json_extract(data,'$.next_attempt_at'),json_extract(data,'$.lease_until'));
CREATE INDEX IF NOT EXISTS outbox_recovery ON outbox_events
 (json_extract(data,'$.status'),json_extract(data,'$.next_attempt_at'),json_extract(data,'$.lease_until'));
CREATE INDEX IF NOT EXISTS inbox_recovery ON inbox_events
 (json_extract(data,'$.status'),json_extract(data,'$.received_at'));
CREATE UNIQUE INDEX IF NOT EXISTS inbox_v2_receipt_key ON inbox_events
 (json_extract(data,'$.source'),json_extract(data,'$.deduplication_key'))
 WHERE json_extract(data,'$.receipt_key') IS NOT NULL;
CREATE INDEX IF NOT EXISTS command_receipt_actor_operation ON command_receipts
 (json_extract(data,'$.actor_id'),json_extract(data,'$.operation'));
