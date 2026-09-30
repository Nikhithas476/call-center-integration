"""Local call-logging demonstration.

No real AWS or ServiceNow requests are made.
The dictionaries simulate stored records for this single-process demo.
Production requires durable storage, conditional claims, and API clients.
"""

import logging
import random
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


class TemporaryError(Exception):
    """A temporary failure that may succeed on retry."""


class MockServiceNow:
    def __init__(self):
        self.records = {}
        self.timeout_after_create = False

    def find(self, external_key):
        return self.records.get(external_key)

    def create(self, external_key):
        # Simulates destination-side uniqueness.
        if external_key not in self.records:
            self.records[external_key] = {
                "sys_id": f"SN-{len(self.records) + 1}",
                "contact_ids": set(),
            }

        if self.timeout_after_create:
            self.timeout_after_create = False
            raise TemporaryError("Record created, but response timed out")

        return self.records[external_key]


def process_call(event, service_now, ledger, max_attempts=3):
    required = ("instance_id", "initial_contact_id", "contact_id")
    if any(not event.get(field) for field in required):
        raise ValueError("Missing required contact identifiers")

    key = f"{event['instance_id']}#{event['initial_contact_id']}"

    for attempt in range(1, max_attempts + 1):
        try:
            # Check the destination before every create attempt.
            record = service_now.find(key)
            if record is None:
                record = service_now.create(key)
                logger.info("Created interaction %s", record["sys_id"])
            else:
                logger.info("Reusing interaction %s", record["sys_id"])

            # A set prevents a repeated transfer segment being added twice.
            record["contact_ids"].add(event["contact_id"])
            ledger[key] = record["sys_id"]
            return record["sys_id"]

        except TemporaryError as error:
            logger.warning("Attempt %s failed: %s", attempt, error)
            if attempt == max_attempts:
                logger.error("Retry limit reached; queue retry or DLQ required")
                raise

            delay = 0.1 * (2 ** (attempt - 1))
            time.sleep(delay + random.uniform(0, 0.05))


def main():
    service_now = MockServiceNow()
    ledger = {}

    call = {
        "instance_id": "support-instance",
        "initial_contact_id": "call-001",
        "contact_id": "call-001",
    }

    first_id = process_call(call, service_now, ledger)
    repeated_id = process_call(call, service_now, ledger)
    assert first_id == repeated_id
    assert len(service_now.records) == 1
    print("PASS: repeated event creates no duplicate")

    transferred_call = {**call, "contact_id": "transfer-001"}
    transfer_id = process_call(transferred_call, service_now, ledger)
    assert transfer_id == first_id
    assert len(service_now.records) == 1
    print("PASS: transfer reuses the original interaction")

    another_call = {
        "instance_id": "sales-instance",
        "initial_contact_id": "call-002",
        "contact_id": "call-002",
    }
    service_now.timeout_after_create = True
    recovered_id = process_call(another_call, service_now, ledger)
    assert recovered_id == "SN-2"
    assert len(service_now.records) == 2
    assert len(ledger) == 2
    print("PASS: timeout recovery finds the existing record")


if __name__ == "__main__":
    main()