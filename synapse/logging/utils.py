# Copyright 2014-2016 OpenMarket Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import logging
from functools import wraps
from inspect import getcallargs

# watcha+
from enum import Enum
from typing import Dict
from inspect import stack

# +watcha

_TIME_FUNC_ID = 0


def _log_debug_as_f(f, msg, msg_args):
    name = f.__module__
    logger = logging.getLogger(name)

    if logger.isEnabledFor(logging.DEBUG):
        lineno = f.__code__.co_firstlineno
        pathname = f.__code__.co_filename

        record = logger.makeRecord(
            name=name,
            level=logging.DEBUG,
            fn=pathname,
            lno=lineno,
            msg=msg,
            args=msg_args,
            exc_info=None,
        )

        logger.handle(record)


def log_function(f):
    """Function decorator that logs every call to that function."""
    func_name = f.__name__

    @wraps(f)
    def wrapped(*args, **kwargs):
        name = f.__module__
        logger = logging.getLogger(name)
        level = logging.DEBUG

        if logger.isEnabledFor(level):
            bound_args = getcallargs(f, *args, **kwargs)

            def format(value):
                r = str(value)
                if len(r) > 50:
                    r = r[:50] + "..."
                return r

            func_args = ["%s=%s" % (k, format(v)) for k, v in bound_args.items()]

            msg_args = {"func_name": func_name, "args": ", ".join(func_args)}

            _log_debug_as_f(f, "Invoked '%(func_name)s' with args: %(args)s", msg_args)

        return f(*args, **kwargs)

    wrapped.__name__ = func_name
    return wrapped


class ActionStatus(Enum):
    """Enum to define the status of a logged action"""

    FAILED = "failed"
    SUCCESS = "success"


# watcha+
def build_log_message(
    action: str = None,
    status: ActionStatus = ActionStatus.FAILED,
    log_vars: Dict = None,
):
    """Build log message to correspond with Watcha format : "[prefix] <action to log> - <status of action> - <collection of variables to logs>"

    Args:
        action: action to log, if it not specified, correspond to caller function name
        status: status of the logged action
        log_vars:  collection of variables to log
    """

    def _get_action_from_caller_function():
        """Get human readable action name from caller function"""
        FUNCTION_NAME_INDEX = 3
        CALLER_FUNCTION_INDEX = 2  # correspond to grand mother function

        function_name = stack()[CALLER_FUNCTION_INDEX][FUNCTION_NAME_INDEX]
        action = " ".join(function_name.split("_")).strip()
        return action

    if action is None:
        action = _get_action_from_caller_function()

    message = f"[watcha] {action} - {status.value}"
    return message if log_vars is None else f"{message} {log_vars}"


# +watcha
