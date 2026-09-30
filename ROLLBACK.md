# Rollback and Recovery

## Principles

Rollback stops harmful behavior and restores the previous
application or contact-flow version.

It does not automatically reverse external data changes.

Queued messages, processing records, and cross-system links
are preserved for investigation and controlled recovery.
Existing customer records are not automatically deleted.

The release manifest identifies the previous working artifacts,
flow versions, and feature-flag settings.

## Phase 1: Call Logging Rollback

### Possible Problems

- ServiceNow becomes unavailable.
- Incorrect field mappings produce bad records.
- Duplicate records appear.
- The new worker fails repeatedly.

### Immediate Steps

1. Disable call-logging writes for the affected team or queue.
2. Pause worker consumption when continued processing is unsafe.
3. Keep collecting completion events into SQS.
4. Record the cutoff time and coordinate temporary manual logging.
5. Restore the last working Lambda version if the release caused
   the problem.

Queue retention and backlog are monitored during the pause.
If the outage may exceed retention, preserve events in approved
durable storage for later replay.

### Recovery

Correct the problem and test the fix in staging.

Check ServiceNow for existing external call keys before replay.
If agents logged calls manually during the outage, reconcile
those records before creating missing interactions.

Replay through the same idempotent worker at controlled
concurrency. Investigate suspected duplicates individually.

Incorrect records receive reviewed corrections with audit notes.

## Phase 2: Routing Rollback

### Possible Problems

- Customer lookup latency increases.
- Context-based routing selects the wrong queue.
- Cached customer information is incorrect.

### Immediate Steps

1. Disable context-based routing using its feature flag.
2. Route calls through the existing normal path.
3. Restore the previous Connect flow version if necessary.
4. Invalidate affected cache entries.
5. Verify new calls reach the expected queues.

### Recovery

Validate customer identity, cache freshness, and routing rules.

Test the correction in staging and then in display-only mode.
Reenable routing for one queue before expanding.

## Phase 3: Synchronization Rollback

### Possible Problems

- Updates repeatedly bounce between ServiceNow and Jira.
- Jira issues are created without links in ServiceNow.
- Status mappings overwrite valid user changes.
- One system is unavailable during a multi-step update.

### Immediate Steps

1. Disable outbound synchronization in both directions.
2. Pause workers while retaining incoming events where safe.
3. Record affected event IDs, record IDs, and release versions.
4. Restore the previous worker version if appropriate.
5. Quarantine unresolved conflicts for owner review.

### Recovery

For a Jira issue created without a ServiceNow link, search by
the external correlation key, save the existing Jira key,
and repair the ServiceNow link.

For an incorrect status update, compare audit history and
current state before applying a reviewed compensating update.

For an update loop, fix echo detection, field ownership, or
version handling before replaying messages.

Reenable one direction and a small record group first.
Verify link integrity and event volume before expanding.

## Infrastructure Rollback

Review a Terraform plan before applying infrastructure changes
to restore a previous configuration.

Do not blindly apply an older configuration that would destroy
queues, tables, or data required by in-flight work.

Keep additive schema changes until old and new workers no
longer depend on them.

## Verification Before Reenablement

- Normal call routing works.
- New interactions have the expected fields.
- Repeated events produce no additional records.
- Queue age decreases during controlled replay.
- ServiceNow and Jira links reconcile.
- No unexpected event amplification appears.
- Conflicts have clear owners and resolution records.

## Operational Ownership

The runbook records the responsible on-call team, system owners,
flag locations, dashboards, rollback artifacts, and replay procedure.

Recovery actions are documented in the incident or change record.