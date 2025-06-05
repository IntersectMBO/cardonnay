import logging
import typing as tp

from cardonnay import colors


class ColorFormatter(logging.Formatter):
    COLORS: tp.ClassVar[dict[str, str]] = {
        "WARNING": colors.BColors.WARNING,
        "ERROR": colors.BColors.FAIL,
        "DEBUG": colors.BColors.OKBLUE,
        # Keep "INFO" uncolored
        "CRITICAL": colors.BColors.FAIL,
    }

    def format(self, record: logging.LogRecord) -> str:
        color: str | None = self.COLORS.get(record.levelname)
        if color:
            record.name = f"{color}{record.name}{colors.BColors.ENDC}"
            record.levelname = f"{color}{record.levelname}{colors.BColors.ENDC}"
            record.msg = f"{color}{record.msg}{colors.BColors.ENDC}"
        return super().format(record)


def configure_logging(fmt: str | None = None) -> None:
    fmt = fmt or "%(message)s"
    logging.setLoggerClass(logging.Logger)  # Ensure standard logger is used
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)  # Set the global log level

    # Remove existing handlers to avoid duplicates
    while root_logger.handlers:
        root_logger.handlers.pop()

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(ColorFormatter(fmt))
    root_logger.addHandler(console_handler)
