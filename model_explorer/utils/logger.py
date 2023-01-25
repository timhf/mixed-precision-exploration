import os
import logging

LOGGER_NAME = "exploration_logger"
LOG_DIR = "results"
LOG_FILE = "exploration_run.log"

if not os.path.exists(LOG_DIR):
    os.mkdir(LOG_DIR)

logger = logging.getLogger(LOGGER_NAME)
logger.propagate = False
logger.setLevel(logging.DEBUG)

# log to console
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
ch.propagate = False

# log to file
fh = logging.FileHandler(os.path.join(LOG_DIR, LOG_FILE))
fh.setLevel(logging.DEBUG)

formatter_file = logging.Formatter(
    "[%(asctime)s] {%(filename)s:%(lineno)d} %(levelname)s - %(message)s"
)
formatter_console = logging.Formatter(
    "[%(asctime)s] %(levelname)-8s - %(message)s"
)

fh.setFormatter(formatter_file)
ch.setFormatter(formatter_console)

logger.addHandler(fh)
logger.addHandler(ch)