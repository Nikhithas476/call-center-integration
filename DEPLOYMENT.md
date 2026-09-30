# Deployment Strategy

## Tool Choice

I would use Terraform to define the new AWS infrastructure:
EventBridge rules, SQS queues, dead-letter queues, DynamoDB
tables, Lambda functions, IAM permissions, and monitoring.

Terraform provides reviewable plans and repeatable environment
setup. Its plans would run through the existing custom
deployment system rather than introducing a competing
production deployment process.

Connect contact flows and ServiceNow/Jira configuration would
use the existing system's supported deployment mechanisms,
with versioned configuration and documented rollback steps.

## Discover the Existing Environment

Before deployment, I would review:

- Existing Connect flows, queue routing, and Lambda integrations.
- ServiceNow business rules and required interaction fields.
- Jira workflows, required fields, and existing automations.
- Existing webhooks and their authentication.
- API quotas, ownership, and permitted network access.
- The custom deployment system's promotion and rollback hooks.

New resources would use separate names and scoped permissions.
Existing shared resources would be referenced or explicitly
imported where appropriate, rather than recreated.

The integration would avoid modifying unrelated flows,
business rules, or automations.

## Environments

| Environment | Purpose |
| --- | --- |
| Development | Build examples and test individual behaviors |
| Staging | Validate the complete integration with test systems |
| Production | Process real calls after staged verification |

Separate AWS accounts are preferred for isolation.
If that is not available, environments use separate resources
and permissions.

ServiceNow and Jira testing uses sandbox environments.
Production customer data is not copied into testing without
approved sanitization.

## Secrets and Permissions

API credentials are stored in AWS Secrets Manager and retrieved
by the integration at runtime.

Secrets are excluded from source code, Terraform variables
committed to Git, logs, and deployment artifacts.

IAM roles grant only the queue, table, secret, and logging
permissions needed by each worker.

ServiceNow and Jira use dedicated integration identities
with limited access. Credential rotation and authentication
failure alerts are included in the operational plan.

## Deployment Pipeline

1. Check documentation, Python syntax, and relevant unit tests.
2. Validate and review Terraform changes.
3. Build versioned Lambda deployment artifacts.
4. Deploy to staging through the custom deployment system.
5. Run integration and failure-recovery tests.
6. Review the production Terraform plan and release manifest.
7. Deploy with integration side effects disabled.
8. Enable features gradually after verification.

The release manifest records artifact versions, configuration,
Connect flow versions, feature flags, and the rollback target.

Terraform state uses an encrypted remote backend with
appropriate locking and restricted access.

## Tests Before Production

Staging tests cover:

- A completed call creates one ServiceNow interaction.
- Repeating an event does not create another interaction.
- Related transfers update the existing interaction.
- A timeout after a successful create is reconciled safely.
- ServiceNow downtime leaves work available for retry.
- Routing lookup failures use the normal routing path.
- A technical issue creates one linked Jira issue.
- Integration-generated updates do not create an echo loop.
- Concurrent edits follow field ownership or enter review.
- Dead-letter queue replay preserves idempotency.
- Rollback restores the previous routing behavior.

## Phased Rollout

### Stage 1: Observe Without Writing

Collect production contact events with external writes disabled.

Verify event counts, identifiers, transfer relationships,
permissions, and monitoring across a full business cycle.

### Stage 2: One Support Queue

Enable automatic call logging for one low-risk Support queue,
selected with the Support owner.

Support is the proposed first team because it exercises both
interaction logging and technical escalation. The specific
queue must be chosen based on operational risk and readiness.

During the initial verification window, coordinate any manual
logging so it does not create duplicate records.

### Stage 3: Expand Call Logging

Expand to the remaining Support queues, then Sales and
Technical Account Management.

Proceed only when record completeness, duplicate checks,
queue backlog, and error rates meet agreed acceptance criteria.

### Stage 4: Enable Routing Context

Start in display-only mode, then enable context-based routing
for one queue after validating the customer data and decisions.

Expand gradually while monitoring latency and fallback rates.

### Stage 5: Enable Jira Synchronization

Enable ServiceNow-to-Jira creation for a small technical category.

After link creation and loop prevention are verified, enable
Jira-to-ServiceNow resolution updates and expand gradually.

## Feature Flags and Compatibility

Feature flags control call logging, context-based routing,
and each synchronization direction independently.

Flags are scoped by team or queue where applicable.
Turning off routing enrichment restores the existing route.

Schema changes are additive first. Previous application versions
must remain compatible with queued events during rollback.

A release does not drop tables, delete queues, or remove fields
needed by in-flight work.