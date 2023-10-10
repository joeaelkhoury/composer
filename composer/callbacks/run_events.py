# Copyright 2022 MosaicML Composer authors
# SPDX-License-Identifier: Apache-2.0

"""Log model run events"""

import time
from datetime import datetime

from composer.core import Callback, State
from composer.loggers import Logger

__all__ = ['RunEventsCallback']


class RunEventsCallback(Callback):
    """Log model run events"""

    def after_load(self, state: State, logger: Logger):
        logger.log_metrics({'model_initialized_dt': datetime.fromtimestamp(time.time())})
