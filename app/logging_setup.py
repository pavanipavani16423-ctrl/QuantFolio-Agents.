import logging
import sys

NOISY = ("httpx", "httpcore", "a2a", "mcp", "fastembed", "urllib3", "langfuse",
         "opentelemetry", "sse_starlette", "aiosqlite", "huggingface_hub", "ragas")


def setup_logging(level: str = "INFO") -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")  # Windows consoles are not UTF-8
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )
    for name in NOISY:
        logging.getLogger(name).setLevel(logging.WARNING)
    logging.getLogger("a2a").setLevel(logging.ERROR)
