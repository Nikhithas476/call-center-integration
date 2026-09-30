# Idempotency and Duplicate Prevention

## Goal

Processing the same call event multiple times should produce
one ServiceNow interaction for the same customer call journey.

Retries are expected. The integration must handle them safely
rather than assume that each event arrives only once.

## Stable Call Key

The interaction key combines:

- The Amazon Connect instance ARN.
- The initial contact ID for the call journey.

Example:

```text
instance-identifier#initial-contact-123
```

Using both values separates calls from the three team instances.
Transfer segments belonging to the same journey use the same
interaction key after their contact relationships are resolved.

A later customer callback has a new initial contact ID and
creates a separate interaction.

## DynamoDB Processing Ledger

A processing ledger is a table that records the progress of
each interaction.

| Field | Purpose |
| --- | --- |
| interaction_key | Identifies the call journey |
| status | PROCESSING, COMPLETED, or REVIEW |
| lease_owner | Identifies the worker currently processing it |
| lease_expires_at | Allows recovery if that worker stops |
| service_now_id | Identifies the created ServiceNow interaction |
| last_applied_version | Helps reject stale updates |
| updated_at | Records the last processing change |

A worker claims a key using a conditional write. Two workers
cannot both acquire the same active claim.

If the claim expires, another worker may take over. It must
still check ServiceNow before attempting a new create.

## ServiceNow Protection

ServiceNow stores the same interaction key in a custom external
key field with a unique constraint.

The DynamoDB ledger prevents competing workers from normally
processing the same call at the same time. The ServiceNow
unique constraint prevents duplicate creates at the destination.

DynamoDB alone cannot guarantee a single external record:
ServiceNow may accept a request before the worker crashes
or fails to update the ledger.

## Timeout Recovery

1. The worker sends a create request to ServiceNow.
2. ServiceNow creates the interaction, but the response times out.
3. The worker leaves the message available for retry.
4. On retry, it searches ServiceNow using the interaction key.
5. If a record exists, it saves that record ID in DynamoDB
   and completes processing.
6. If no record is found, it may retry the create using the
   same unique key.

A unique-key conflict also triggers a lookup of the existing
record. An unresolved or inconsistent result is sent for review.

## Transfers and Out-of-Order Events

Related transfer contact IDs are mapped to the initial contact
ID. Queue and agent history is merged into the existing
interaction.

Repeated updates must not append the same transfer information
twice. Each segment is identified by its contact ID.

Updates are applied only when their source version is newer.
If no reliable version is available, the worker reads the
latest authoritative contact data before applying an update.

Transfer relationships and timestamps must be verified with
sample Connect records during implementation.

## Jira Duplicate Prevention

The ServiceNow record ID is the stable correlation key for
creating a Jira issue.

The integration stores the ServiceNow-to-Jira link in DynamoDB
and checks for an existing link or Jira correlation key before
creating an issue.

If Jira creation succeeds but link-back fails, retrying searches
for the existing Jira issue and repairs the link.

If Jira cannot enforce uniqueness for that key, creation is
serialized per ServiceNow record. Uncertain create outcomes
are reconciled or reviewed before another create attempt.

## Retention and Replay

Ledger records are retained beyond the agreed event replay
window. ServiceNow retains the unique external key even if
an old DynamoDB ledger entry is removed.

Messages replayed from a dead-letter queue use the same keys
and processing logic as normal messages.