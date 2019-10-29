# -*- coding: utf-8 -*-

import time
import psutil
from collections import defaultdict
import inspect

from twisted.internet import defer

from ._base import SQLBaseStore

from synapse.util.caches.descriptors import cached, cachedInlineCallbacks
from synapse.api.constants import EventTypes, JoinRules
from synapse.storage.engines import PostgresEngine, Sqlite3Engine
from synapse.types import get_domain_from_id, get_localpart_from_id


def _caller_name():
    '''returns the name of the function calling the one calling this one'''
    try:
        return inspect.stack()[2][3]
    except IndexError:
        # seems to happen (related to iPython install ?)
        return "<unknown function>"


class VerificationStore(SQLBaseStore):

    def _execute_sql(self, sql, *args):
        return self._execute(
            _caller_name(),
            None, sql, *args)

    @defer.inlineCallbacks
    def verification_history(self):
        now = int(round(time.time() * 1000))

        verification_messages = yield self._execute_sql("""
        SELECT rowid, message, signature FROM verification_messages
        ORDER BY rowid ASC;
        """)

        result = yield (verification_messages)

        defer.returnValue(result)

    @defer.inlineCallbacks
    def post_message(self, message, signature):
        now = int(round(time.time() * 1000))
        result = yield self._execute_sql("INSERT INTO verification_messages (message,signature) VALUES(%s)" % ('"'+message+'","'+signature+'"',))
        defer.returnValue(result)
