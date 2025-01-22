import logging
from dotenv import load_dotenv
import os

load_dotenv(override=False)


def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(os.getenv("LOG_LEVEL"))
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


log = setup_logging()
