# Monitoring and Alerts

## Approach

Use Amazon CloudWatch for AWS metrics, structured logs,
dashboards, and alarms.

Combine infrastructure monitoring with reconciliation checks.
A healthy worker invocation does not prove that every call
was recorded or every ticket was synchronized correctly.

Dashboards separate results by Connect instance, team,
integration phase, and deployed version.

## Call Logging Metrics

- Number of completed call journeys observed.
- Number successfully recorded in ServiceNow.
- Time from contact completion to successful logging.
- Oldest message age and queue backlog.
- Failed processing attempts and external API errors.
- Dead-letter queue message count.
- Missing records found by reconciliation.
- Unique-key conflicts and confirmed duplicate records.

Counts are compared using the same call-journey grouping and
time window. Transfer segments must not inflate the expected
number of ServiceNow interactions.

## Routing Metrics

- Total customer-context requests.
- Cache hit rate and context freshness.
- Lookup latency, including p95.
- ServiceNow timeout and error rate.
- Percentage of calls using fallback routing.
- Circuit breaker state.
- Routing errors by queue and team.

The p95 latency is the time within which 95% of measured
requests finish. It helps reveal slow requests that an
average might hide.

Fallback routing is an expected recovery behavior, but a
sustained increase may indicate an outage or identity problem.

## Synchronization Metrics

- Events received and successfully processed.
- Time from source change to destination update.
- Queue age and dead-letter queue messages.
- Missing or inconsistent ServiceNow-to-Jira links.
- Conflicts awaiting review.
- Ignored duplicate and echo events.
- Unexpected update amplification.

Repeated updates to the same linked pair without a genuine
source change are investigated as a possible synchronization loop.

## Initial Alarm Settings

| Signal | Initial threshold | Response |
| --- | --- | --- |
| Oldest queued message | More than 5 minutes for 10 minutes | Investigate worker health and upstream availability |
| Processing DLQ messages | At least 1 message for 5 minutes | Triage failure and plan controlled replay |
| EventBridge delivery failures | Failed delivery or delivery DLQ messages | Check rule targets and permissions |
| External API failure rate | Above 2% for 10 minutes with at least 50 attempts | Check outage, throttling, and credentials |
| Routing p95 latency | Above 1 second for 10 minutes | Check cache and lookup deadline |
| Routing fallback rate | Above 5% with at least 50 requests in the window | Check identity lookup and ServiceNow health |
| Reconciliation gaps | Missing record older than 15 minutes | Investigate and backfill safely |
| Unlinked Jira issues | At least 1 unresolved item after reconciliation | Repair link or send for review |
| Sync conflicts | New unresolved conflicts | Notify the responsible record owner |

These are proposed starting values, not established service
commitments. They are adjusted using traffic baselines,
business requirements, and low-volume queue behavior.

## Structured Logs

Each processing attempt records:

- Correlation ID and source event ID.
- Integration phase and direction.
- Scoped or hashed contact/account identifier.
- Processing action and outcome.
- Attempt number and elapsed time.
- External HTTP status or sanitized error category.
- Application version.

Credentials, phone numbers, full ticket descriptions, and
unnecessary customer information are excluded.

Log retention and access permissions follow the organization's
data policies.

## End-to-End Verification

A scheduled reconciliation job checks whether completed
call journeys have matching ServiceNow interactions.

For linked technical issues, it checks that both systems
contain the expected links and approved status mappings.

Synthetic tests in staging exercise the full path:

1. Complete a test call.
2. Verify one ServiceNow interaction.
3. Classify it as a technical issue.
4. Verify one linked Jira issue.
5. Resolve Jira and verify the approved ServiceNow update.
6. Repeat notifications and confirm no duplicate side effects.

Any production synthetic tests require an approved test account
and clearly labeled records.

## Alert Ownership

Alerts identify the affected team, phase, dashboard, and runbook.

Customer-impacting routing failures go to the on-call team.
Record conflicts and permanent validation failures go to
the relevant ServiceNow or Jira owner.

After recovery, reconciliation confirms that the backlog
and missing records have been resolved.