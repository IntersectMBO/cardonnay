import json
import logging
import pathlib as pl
import subprocess
import sys

from cardonnay import ttypes

LOGGER = logging.getLogger(__name__)


def write_json(out_file: pl.Path, content: dict) -> pl.Path:
    """Write dictionary content to JSON file."""
    with open(out_file.expanduser(), "w", encoding="utf-8") as out_fp:
        out_fp.write(json.dumps(content, indent=4))
    return out_file


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
