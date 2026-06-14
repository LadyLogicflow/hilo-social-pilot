# -*- coding: utf-8 -*-
import logging, os
from config import LOG_DIR

def setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(os.path.join(LOG_DIR, "hilo.log"), encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    return logging.getLogger("hilo")
