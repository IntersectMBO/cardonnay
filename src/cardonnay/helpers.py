import datetime as dt
import json
import logging
import os
import pathlib as pl
import subprocess
import sys
import time
import typing as tp

import pydantic
import pygments
from pygments.formatters import terminal as pterminal
from pygments.lexers import data as pdata

from cardonnay import ttypes

LOGGER = logging.getLogger(__name__)


class CustomEncoder(json.JSONEncoder):
    # pyrefly: ignore  # bad-override
    def default(self, obj: tp.Any) -> tp.Any:  # noqa: ANN401
        if isinstance(obj, pl.Path):
            return str(obj)
        if isinstance(obj, dt.datetime):
            return obj.isoformat()
        return super().default(obj)


def should_use_color() -> bool:
    if "NO_COLOR" in os.environ:
        return False
    if os.environ.get("CLICOLOR_FORCE") == "1":
        return True
    if sys.stdout.isatty():
        return os.environ.get("CLICOLOR", "1") != "0"
    return False


def write_json(out_file: pl.Path, content: dict) -> pl.Path:
    """Write dictionary content to JSON file."""
    with open(out_file, "w", encoding="utf-8") as out_fp:
        out_fp.write(json.dumps(content, indent=4))
    return out_file


def print_json_str(data: str) -> None:
    """Print JSON string to stdout in a pretty format."""
    if should_use_color():
        print(
            pygments.highlight(
                code=data, lexer=pdata.JsonLexer(), formatter=pterminal.TerminalFormatter()
            )
        )
    else:
        print(data)


def print_json(data: dict | list | pydantic.BaseModel) -> None:
    """Print JSON data to stdout in a pretty format."""
    if isinstance(data, pydantic.BaseModel):
        json_str = data.model_dump_json(indent=2)
    else:
        json_str = json.dumps(data, cls=CustomEncoder, indent=2)
    print_json_str(data=json_str)


def run_command(
    command: str | list,
    workdir: ttypes.FileType = "",
    ignore_fail: bool = False,
    shell: bool = False,
) -> int:
    """Run command and stream output live."""
    if isinstance(command, str):
        cmd = command if shell else command.split()
        cmd_str = command
    else:
        cmd = command
        cmd_str = " ".join(command)

    LOGGER.debug("Running `%s`", cmd_str)

    p = subprocess.Popen(
        cmd,
        cwd=workdir or None,
        shell=shell,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,  # Line-buffered
    )

    if p.stdout is not None:
        for line in p.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
        p.stdout.close()  # Properly close the stream
    else:
        p.wait()  # Still wait if no stdout
        if not ignore_fail and p.returncode != 0:
            err = f"An error occurred while running `{cmd_str}` (no output captured)"
            raise RuntimeError(err)
        return p.returncode

    p.wait()

    if not ignore_fail and p.returncode != 0:
        msg = f"An error occurred while running `{cmd_str}`"
        raise RuntimeError(msg)

    return p.returncode


def run_detached_command(
    command: str | list[str],
    logfile: pl.Path,
    workdir: str | pl.Path = "",
) -> subprocess.Popen:
    """Start command in background, detached from the current process.

    Args:
        command: Command to run.
        workdir: Optional working directory.
        logfile: File where both stdout and stderr are redirected.
    """
    cmd = command.split() if isinstance(command, str) else command

    # Full detachment on Unix-like systems
    with open(logfile, "a") as logout:
        p = subprocess.Popen(
            cmd,
            cwd=pl.Path(workdir) if workdir else None,
            stdout=logout,
            stderr=logout,
            stdin=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )

    return p


def read_from_file(file: ttypes.FileType) -> str:
    """Read address stored in file."""
    with open(pl.Path(file), encoding="utf-8") as in_file:
        return in_file.read().strip()


def wait_for_file(
    file: ttypes.FileType,
    timeout: float,
    poll_interval: float = 0.2,
) -> bool:
    """Wait for a file to appear within a time limit.

    Args:
        file: Path to the target file.
        timeout: Time limit in seconds.
        poll_interval: Time between checks (default 0.2s).

    Returns:
        True if file appeared in time, False otherwise.
    """
    file = pl.Path(file)
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        try:
            if file.is_file():
                return True
        except FileNotFoundError:
            pass  # Any parent component may not exist yet

        time.sleep(poll_interval)

    return False
