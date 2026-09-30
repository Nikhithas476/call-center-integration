# Integration Architecture

## Phase 1: Automatic Call Logging

### Approach and Service Choices

Amazon Connect publishes contact events to EventBridge.
An EventBridge rule selects COMPLETED events from the three
team instances and sends them to an SQS call queue.

A Lambda worker processes the queued messages and creates
an interaction record in ServiceNow through its API.

I chose SQS to separate call completion from ServiceNow
availability. If ServiceNow is temporarily unavailable,
messages remain available for retry. Lambda provides a
worker without requiring a continuously running server.

The COMPLETED event includes the end of after-contact work
when applicable. If the business needs a record immediately
at disconnect, I would create a preliminary record earlier
and update it when completion data arrives.

### Processing Steps

1. Validate the event type and required identifiers.
2. Identify the Connect instance and the initial contact ID.
3. Build a stable external key for the interaction.
4. Claim the work in DynamoDB using a conditional write.
5. Look for a ServiceNow interaction with that external key.
6. Create the interaction if it does not already exist.
7. Save the returned ServiceNow record ID in DynamoDB.
8. Acknowledge successful processing so the queue message
   can be removed.

The DynamoDB record tracks processing status and the
ServiceNow record ID. ServiceNow must also enforce a unique
external key because a local processing record alone cannot
prevent every duplicate external write.

### Call Transfers

My proposed business rule is one interaction per customer
call journey. A transfer between queues updates the existing
interaction with the additional queue and agent information.

Some transfer types create related contact IDs. I would use
Connect's initial and related contact identifiers to link
those segments, and validate the behavior with sample calls
before rollout.

A separate customer callback creates a new interaction,
linked to the previous interaction when that relationship
is known.

### Errors and Retries

- Temporary timeouts, rate limits, and server errors are retried
  with increasing delays and jitter.
- Retry-After is respected when the external API provides it.
- Invalid events and permanent validation errors are
  quarantined for investigation.
- Worker concurrency is limited to avoid overwhelming
  ServiceNow.
- Messages that repeatedly fail move to a dead-letter queue.
- For a batch of messages, only failed items are returned
  for retry.

If a create request times out, ServiceNow may still have
created the interaction. Before another create attempt,
the worker looks up the external key. The unique constraint
protects against a duplicate if the first request succeeded.

An EventBridge delivery dead-letter queue also captures
events that cannot be delivered to the main SQS queue.
This is separate from the worker's processing dead-letter queue.

### Simplified Processing Example

The following is pseudocode describing the intended behavior:

```text
receive completed contact event

validate event
resolve initial contact ID
build key from Connect instance + initial contact ID

claim processing key using a conditional DynamoDB write
if another worker owns an active claim:
    retry this message later

look up ServiceNow interaction by external key

if interaction exists:
    update it with any newer transfer or completion data
else:
    create interaction using the unique external key

    if create outcome is uncertain:
        look up the external key before trying another create

save ServiceNow record ID and mark processing complete
acknowledge the queue message
```

### Reconciliation

A scheduled reconciliation process compares completed
Connect contact records with recorded ServiceNow interactions
over a bounded time window.

This detects missed events and incomplete writes.
Missing records are sent through the same idempotent
processing path. Suspected duplicate records are reviewed
rather than automatically deleted.
## Phase 2: Real-Time Routing Enrichment

### Approach and Service Choices

The inbound Connect contact flow invokes a customer-context
Lambda before selecting a queue.

The Lambda retrieves a small customer summary containing:

- Open ticket count.
- SLA tier.
- Account health.
- The time the information was last refreshed.

An SLA tier represents the customer's agreed service level.
Routing rules may use it to select an appropriate queue,
subject to business-approved policies.

I chose a separate Lambda for routing because this request
has a short response deadline, unlike background call logging.

### Customer Identification

The lookup uses a verified customer or account identifier
collected through the contact flow.

A phone number alone is not sufficient proof of identity.
If the customer cannot be identified reliably, the call follows
the normal routing path without customer-specific enrichment.

### Cache Strategy

DynamoDB stores the minimal customer summary with an
application-level expires_at timestamp.

The Lambda first checks the cache. A fresh entry is returned
without calling ServiceNow.

The initial freshness window is five minutes. This is a starting
assumption to confirm with business owners, particularly for
SLA changes and sensitive routing decisions.

DynamoDB TTL may clean up old entries, but the application
checks expires_at because expired items may remain in the table.

ServiceNow change notifications can invalidate affected cache
entries before their normal expiry. Cache misses may also
schedule a background refresh.

### Lookup Deadline and Fallback

On a cache miss, the Lambda makes a bounded ServiceNow lookup.
An initial proposal is a 700-millisecond API deadline within
a two-second overall routing budget.

These values must be tested and adjusted for the contact flow
and observed API latency. The full request must fit within the
configured Connect invocation timeout.

If the lookup is slow, fails, or returns unusable data, the
Lambda returns context_status=unavailable and a default
routing decision.

The contact flow also has an explicit error and timeout branch
that sends the caller through the existing normal routing path.

I would avoid repeated API retries during this live lookup:
the caller should not wait through a background-style retry cycle.

### Protecting ServiceNow

The integration limits concurrent API lookups.

A circuit breaker temporarily skips ServiceNow requests after
a sustained failure threshold. After a cooldown, a small number
of requests test whether the service has recovered.

During that period, fresh cache entries remain usable.
Calls without fresh context follow the normal routing path.

### Handling Stale Context

Stale information is not used for entitlement or priority
decisions unless the business explicitly approves that policy.

If stale information is shown to agents, it is labeled with
its refresh time so they understand its limitations.

### Simplified Routing Example

The following is pseudocode:

```text
identify and verify customer

if identity is unavailable:
    return normal route with context_status=unverified

read customer summary from cache

if cached summary is fresh:
    return approved routing decision using that summary

if ServiceNow circuit breaker is open:
    return normal route with context_status=unavailable

try ServiceNow lookup within the API deadline

if lookup succeeds:
    save minimal summary and expiry in cache
    return approved routing decision
else:
    schedule a background refresh where appropriate
    return normal route with context_status=unavailable
```

### Privacy and Validation

Only fields needed for routing are returned to the contact flow.
Credentials, full ticket descriptions, and unnecessary personal
information are excluded.

Routing behavior is tested first in display-only mode:
agents can see the context while actual queue selection follows
the existing rules. Routing changes are enabled gradually after
the results are verified.
## Phase 3: Bidirectional ServiceNow and Jira Synchronization

### Approach and Service Choices

ServiceNow and Jira send change notifications to an
authenticated webhook endpoint.

The endpoint validates each notification, places it in an
SQS synchronization queue, and acknowledges it only after
the message has been accepted by the queue.

A synchronization Lambda processes the messages.
DynamoDB stores record links, processed event IDs,
processing claims, and the last applied source versions.

I chose queued processing because ticket synchronization
can tolerate a short delay. An outage in one system should
not prevent the other system from accepting normal user edits.

### ServiceNow to Jira

When a ServiceNow record is marked as a technical issue:

1. Validate that the record meets the agreed creation criteria.
2. Claim processing for that ServiceNow record.
3. Check for an existing ServiceNow-to-Jira link.
4. If there is no link, search Jira using the ServiceNow
   record ID as the external correlation key.
5. Create a Jira issue only when no existing issue is found.
6. Store the Jira issue key in DynamoDB.
7. Update ServiceNow with the Jira issue key and link.

The exact field mappings and required Jira fields are
confirmed with both system owners.

### Jira to ServiceNow

When a linked Jira issue is resolved:

1. Validate the notification and find its ServiceNow link.
2. Read the relevant current record state.
3. Apply the agreed resolution mapping to ServiceNow.
4. Save the applied Jira version and processing result.

Jira resolution does not automatically close every customer
interaction. The business must approve which ServiceNow
status transition is appropriate.

Reopened Jira issues require an explicit transition rule
rather than silently overwriting a closed customer record.

### Preventing Update Loops

An update from the integration may generate another webhook.

Each integration write includes an origin marker and
correlation ID where the destination supports them.
Notifications that only echo the integration's own changes
are ignored.

A notification containing a genuine user change is still
processed, even if the record was previously integration-updated.

The worker also:

- Deduplicates source event IDs.
- Compares source versions to reject stale updates.
- Writes only when the mapped destination value differs.
- Synchronizes only explicitly owned fields.

These protections work together. An origin marker alone
is not sufficient to prevent every loop.

### Field Ownership and Conflicts

| Information | Owning system |
| --- | --- |
| Customer and account information | ServiceNow |
| Customer-facing priority and classification | ServiceNow |
| Engineering status and resolution | Jira |
| Cross-system links and processing metadata | Integration |

Changes to different owned fields can be applied independently.

For the same field, the worker checks the latest state and
uses a conditional update or a scoped API that enforces the
expected version.

If the destination changed unexpectedly, the worker
re-reads and evaluates the update. Conflicts that cannot be
resolved by the ownership rules are sent for manual review.

I would not use unconditional last-write-wins for priority,
resolution, or customer-facing closure.

### Errors and Recovery

Temporary API failures are retried with increasing delays
and jitter. Rate limits respect Retry-After.

Permanent validation failures are quarantined.
Repeated processing failures move to a dead-letter queue.

If Jira creation succeeds but updating ServiceNow fails,
the retry searches for the existing Jira issue and repairs
the link instead of creating another issue.

If a create request has an uncertain outcome, the worker
reconciles it before another create attempt. Where Jira
cannot enforce uniqueness, unresolved outcomes require
review rather than a blind retry.

Events are serialized per linked record, or protected by
conditional claims and version checks, so concurrent workers
cannot overwrite newer synchronization state.

### Reliable Change Capture

A webhook alone may miss changes if delivery fails.

Where supported, ServiceNow records an outbound event in
an outbox as part of the same transaction as the record change.
A separate sender delivers that event and retries failures.

For Jira, the implementation verifies available webhook
retry behavior and supplements it with periodic reconciliation.

The reconciler checks recently changed linked records in
both systems to identify missing links and status differences.

### Simplified Synchronization Example

The following is pseudocode:

```text
receive and validate change notification

if event was already processed:
    acknowledge without repeating the update

claim the event and linked record

if notification is only an echo of our own update:
    mark event processed
    acknowledge

if ServiceNow record becomes a technical issue:
    find existing Jira link or issue by correlation key
    create only if no issue exists and creation is safe
    save the link
    update ServiceNow with the Jira issue key

if Jira issue is resolved:
    read the linked ServiceNow record
    verify source version and allowed transition
    update Jira-owned resolution fields conditionally
    send unresolved conflicts for review

mark event processed only after the required writes succeed

on temporary failure:
    leave the event available for retry
```