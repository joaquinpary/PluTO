import logging
import os

import uvicorn

from api import app

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("coord_transform_main")


def main():
    logger.info("Starting coordinates transformation engine...")
    # uvicorn handles SIGTERM itself and returns.
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("TRANSFORM_PORT", "8000")), log_level="info")


if __name__ == "__main__":
    main()
