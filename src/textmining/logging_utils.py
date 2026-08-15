import logging
import sys
from pathlib import Path
from datetime import datetime

def setup_logging(output_dir: Path, run_name: str, level=logging.DEBUG) -> Path:
    output_dir = output_dir / 'logs'
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = output_dir / f"{run_name}_{timestamp}.log"

    root = logging.getLogger("textmining")
    root.setLevel(level)
    root.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )

    file_handler = logging.FileHandler(log_path)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(fmt)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.INFO)  # keep console less noisy than the file
    console_handler.setFormatter(fmt)

    root.addHandler(file_handler)
    root.addHandler(console_handler)
    return log_path