"""Local ServiceNow-Jira synchronization demonstration.

No external requests or credentials are required.
Production needs durable event storage, per-record serialization,
authenticated webhooks, and conditional destination updates.
"""


class TemporaryError(Exception):
    """A failure that allows the queued event to be retried."""


class MockJira:
    def __init__(self):
        self.issues = {}

    def find_by_service_now_id(self, service_now_id):
        matches = [
            issue
            for issue in self.issues.values()
            if issue["service_now_id"] == service_now_id
        ]
        if len(matches) > 1:
            raise ValueError("Multiple Jira matches require manual review")
        return matches[0] if matches else None

    def create(self, service_now_id):
        # Caller checks for an existing issue first.
        # Production must serialize creation for each ServiceNow record.
        key = f"ENG-{len(self.issues) + 1}"
        issue = {
            "key": key,
            "service_now_id": service_now_id,
            "status": "Open",
        }
        self.issues[key] = issue
        return issue


class SyncDemo:
    def __init__(self):
        self.jira = MockJira()
        self.service_now = {
            "SN-100": {
                "jira_key": None,
                "engineering_status": "Pending",
            }
        }
        self.processed_events = set()
        self.last_jira_version = {}
        self.expected_echoes = set()
        self.fail_link_once = False

    def create_linked_issue(self, event_id, service_now_id):
        event_key = ("servicenow", event_id)
        if event_key in self.processed_events:
            return "duplicate"

        record = self.service_now[service_now_id]

        # Reconcile the remote record before creating another issue.
        issue = self.jira.find_by_service_now_id(service_now_id)
        if issue is None:
            issue = self.jira.create(service_now_id)

        # Simulate Jira creation succeeding but link storage failing.
        if self.fail_link_once:
            self.fail_link_once = False
            raise TemporaryError("Jira created; saving the link failed")

        record["jira_key"] = issue["key"]

        # Mark complete only after the link is successfully stored.
        self.processed_events.add(event_key)
        return issue["key"]

    def apply_jira_resolution(self, event_id, jira_key, version):
        event_key = ("jira", event_id)
        if event_key in self.processed_events:
            return "duplicate"

        if version <= self.last_jira_version.get(jira_key, 0):
            self.processed_events.add(event_key)
            return "stale"

        issue = self.jira.issues[jira_key]
        record = self.service_now[issue["service_now_id"]]

        if record["jira_key"] != jira_key:
            raise ValueError("Missing or conflicting link requires review")

        if issue["status"] != "Resolved":
            raise ValueError("This example handles resolved issues only")

        # Update the engineering field; customer closure is a separate rule.
        record["engineering_status"] = "Resolved"

        # Only this specific write's echo should be suppressed.
        echo_token = f"{jira_key}:{version}:engineering_status"
        self.expected_echoes.add(echo_token)

        self.last_jira_version[jira_key] = version
        self.processed_events.add(event_key)
        return echo_token

    def handle_service_now_notification(self, echo_token=None):
        if echo_token in self.expected_echoes:
            return "integration echo ignored"
        return "genuine change requires normal processing"


def main():
    demo = SyncDemo()

    demo.fail_link_once = True
    try:
        demo.create_linked_issue("event-001", "SN-100")
    except TemporaryError:
        print("Simulated failure: link storage failed; retrying")

    jira_key = demo.create_linked_issue("event-001", "SN-100")
    assert jira_key == "ENG-1"
    assert len(demo.jira.issues) == 1
    assert demo.service_now["SN-100"]["jira_key"] == jira_key
    print("PASS: retry repairs the link without another Jira issue")

    result = demo.create_linked_issue("event-001", "SN-100")
    assert result == "duplicate"
    assert len(demo.jira.issues) == 1
    print("PASS: repeated event is ignored")

    demo.jira.issues[jira_key]["status"] = "Resolved"
    token = demo.apply_jira_resolution("event-002", jira_key, version=2)
    assert demo.service_now["SN-100"]["engineering_status"] == "Resolved"
    print("PASS: Jira resolution updates ServiceNow")

    result = demo.apply_jira_resolution("event-003", jira_key, version=1)
    assert result == "stale"
    print("PASS: older Jira event is ignored")

    result = demo.handle_service_now_notification(echo_token=token)
    assert result == "integration echo ignored"
    result = demo.handle_service_now_notification()
    assert result == "genuine change requires normal processing"
    print("PASS: integration echo is ignored; genuine changes remain eligible")


if __name__ == "__main__":
    main()