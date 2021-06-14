from unittest.mock import Mock, patch

from synapse.logging.utils import build_log_message, ActionStatus
from tests import unittest

LOG_PREFIX = "[watcha]"

class LogMessageTestCase(unittest.HomeserverTestCase):
    def test_build_log_message(self):
        log_message = build_log_message()
        self.assertEquals(
            log_message,
            f"{LOG_PREFIX} test build log message - {ActionStatus.FAILED.value}",
        )

    def test_build_log_message_with_action(self):
        action = "get log message"
        log_message = build_log_message(action=action)
        self.assertEquals(
            log_message, f"{LOG_PREFIX} {action} - {ActionStatus.FAILED.value}"
        )

    def test_build_log_message_with_status(self):
        status = ActionStatus.SUCCESS
        log_message = build_log_message(status=status)
        self.assertEquals(
            log_message, f"{LOG_PREFIX} test build log message with status - {status.value}"
        )

    def test_build_log_message_with_log_vars(self):
        log_vars = {"user_id": "@creator:test", "email": "creator@test.com"}
        action = "register user"
        log_message = build_log_message(action=action, log_vars=log_vars)
        self.assertEquals(
            log_message,
            f"{LOG_PREFIX} {action} - {ActionStatus.FAILED.value} {log_vars}",
        )
