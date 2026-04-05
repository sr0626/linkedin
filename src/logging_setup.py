import logging
import os
from datetime import datetime


def setup_logging(logs_dir: str) -> logging.Logger:
    os.makedirs(logs_dir, exist_ok=True)

    log_filename = datetime.now().strftime("scraper_%Y%m%d.log")
    log_path = os.path.join(logs_dir, log_filename)

    logger = logging.getLogger("linkedin_scraper")
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        return logger

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(fmt)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    logging.getLogger().setLevel(logging.WARNING)

    return logger
