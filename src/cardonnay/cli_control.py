import contextlib
import json
import logging
import os
import pathlib as pl
import shlex
import signal
import time
import typing as tp

from cardonnay import ca_utils
from cardonnay import colors
from cardonnay import consts
from cardonnay import helpers
from cardonnay import structs

LOGGER = logging.getLogger(__name__)

KILL_WAIT_SEC = 5


def testnet_stop(statedir: pl.Path, env: dict[str, str]) -> int:
    """Stop the testnet cluster by running the stop script.

    Returns 0 on success, 1 if the script is missing or fails.
    """
    stop_script = statedir / "stop-cluster"
    if not stop_script.exists():
        LOGGER.error(f"Stop script '{stop_script}' does not exist.")
        return 1

    ca_utils.set_env_vars(env=env)

    print(
        f"{colors.BColors.OKGREEN}Stopping the testnet cluster with "
        f"`{stop_script}`:{colors.BColors.ENDC}"
    )
    try:
        helpers.run_command(command=[str(stop_script)], workdir=statedir)
    except (RuntimeError, OSError):
        LOGGER.exception("Failed to stop the testnet cluster")
        return 1

    return 0


def pid_exists(pid: int) -> bool:
    """Check if a process with the given PID exists and can be signaled by this user."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def wait_pid_gone(pid: int, timeout: float) -> bool:
    """Wait until the process exits; return True when it is gone before the timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_exists(pid):
            return True
        time.sleep(0.1)
    return False


def read_valid_pid(pidfile: pl.Path) -> int:
    """Read a PID from the file; return 0 when it is unreadable or invalid."""
    try:
        pid = int(helpers.read_from_file(pidfile))
    except (OSError, ValueError) as excp:
        LOGGER.warning(f"Cannot read PID from '{pidfile}': {excp}")
        return 0

    if pid <= 0:
        # Never signal PID <= 0: 0 targets the whole process group, negative values
        # target other process groups.
        LOGGER.warning(f"Invalid PID {pid} in '{pidfile}'.")
        return 0

    return pid


def kill_starting_testnet(pidfile: pl.Path, statedir: pl.Path) -> bool:
    """Kill the start script process recorded in the PID file, best-effort.

    The recorded PID is trusted only while the instance is still starting. Once
    `STATUS_STARTED` exists, the start script has finished and its PID may have been
    recycled by the kernel, so the stale PID file is only removed. Escalates to
    SIGKILL when the process does not exit within `KILL_WAIT_SEC` seconds.

    Returns False when a live process could not be signaled or did not exit.
    """
    if not pidfile.exists():
        return True

    if (statedir / ca_utils.STATUS_STARTED).exists():
        pidfile.unlink(missing_ok=True)
        return True

    pid = read_valid_pid(pidfile=pidfile)
    if not pid:
        pidfile.unlink(missing_ok=True)
        return True

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pid = 0  # The process has already exited
    except OSError as excp:
        LOGGER.error(f"Failed to kill the starting testnet process {pid}: {excp}")  # noqa: TRY400
        return False

    if pid and not wait_pid_gone(pid=pid, timeout=KILL_WAIT_SEC):
        LOGGER.warning(f"Process {pid} did not exit after SIGTERM, sending SIGKILL.")
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGKILL)
        if not wait_pid_gone(pid=pid, timeout=1):
            LOGGER.error(f"Process {pid} is still alive after SIGKILL.")
            return False

    pidfile.unlink(missing_ok=True)
    return True


def kill_and_stop_testnet(instance_num: int, workdir: pl.Path) -> int:
    """Kill the start script process of a starting instance and stop the testnet cluster.

    The stop script is run even when the start script process could not be killed.
    Returns 0 on success, 1 when either step failed.
    """
    statedir = workdir / f"{ca_utils.STATE_CLUSTER_PREFIX}{instance_num}"
    env = ca_utils.create_env_vars(workdir=workdir, instance_num=instance_num)

    kill_ok = kill_starting_testnet(
        pidfile=workdir / f"start_cluster{instance_num}.pid", statedir=statedir
    )
    run_retval = testnet_stop(statedir=statedir, env=env)
    if not kill_ok:
        run_retval = 1

    return run_retval


def testnet_restart_nodes(statedir: pl.Path, env: dict[str, str]) -> int:
    """Restart the `nodes:` supervisor group of the testnet instance.

    Returns 0 on success, 1 if the script is missing or fails.
    """
    script = statedir / "supervisorctl_restart_nodes"
    if not script.exists():
        LOGGER.error(f"Restart nodes script '{script}' does not exist.")
        return 1

    ca_utils.set_env_vars(env=env)

    print(
        f"{colors.BColors.OKGREEN}Restarting the testnet cluster nodes "
        f"with `{script}`:{colors.BColors.ENDC}"
    )
    try:
        helpers.run_command(command=[str(script)], workdir=statedir)
    except (RuntimeError, OSError):
        LOGGER.exception("Failed to restart the testnet cluster nodes")
        return 1

    return 0


def testnet_restart_all(statedir: pl.Path, env: dict[str, str]) -> int:
    """Restart all supervisor-managed services of the testnet instance.

    Runs `supervisorctl restart all` for this one instance (nodes and auxiliary
    services). Does not restart the supervisord daemon itself.
    Returns 0 on success, 1 if the script is missing or fails.
    """
    script = statedir / "supervisorctl_local"
    if not script.exists():
        LOGGER.error(f"The supervisorctl script '{script}' does not exist.")
        return 1

    ca_utils.set_env_vars(env=env)

    cmd = [str(script), "restart", "all"]
    print(
        f"{colors.BColors.OKGREEN}Restarting the testnet cluster with "
        f"`{shlex.join(cmd)}`:{colors.BColors.ENDC}"
    )
    try:
        helpers.run_command(command=cmd, workdir=statedir)
    except (RuntimeError, OSError):
        LOGGER.exception("Failed to restart the testnet cluster")
        return 1

    return 0


def load_testnet_info(statedir: pl.Path) -> dict[str, tp.Any]:
    """Load info from the instance `testnet.json`; return empty dict when missing or invalid."""
    tfile = statedir / ca_utils.TESTNET_JSON
    try:
        with open(tfile, encoding="utf-8") as fp_in:
            loaded = json.load(fp_in)
    except FileNotFoundError:
        # The file is not written yet while the instance is starting
        return {}
    except (OSError, ValueError) as excp:
        LOGGER.warning(f"Cannot read '{tfile}': {excp}")
        return {}

    if not isinstance(loaded, dict):
        LOGGER.warning(f"Unexpected content of '{tfile}'")
        return {}

    return loaded


def print_instances(workdir: pl.Path) -> None:
    """Print a JSON summary of running testnet instances.

    Instances whose `testnet.json` is missing or unreadable are reported with
    type "unknown".
    """
    running_instances = sorted(ca_utils.get_running_instances(workdir=workdir))
    out_list: list[structs.InstanceSummary] = []

    for i in running_instances:
        statedir = workdir / f"{ca_utils.STATE_CLUSTER_PREFIX}{i}"
        testnet_info = load_testnet_info(statedir=statedir)

        testnet_name = str(testnet_info.get("name") or "unknown")
        comment = testnet_info.get("comment")

        testnet_state = (
            consts.States.STARTED
            if (statedir / ca_utils.STATUS_STARTED).exists()
            else consts.States.STARTING
        )

        out_list.append(
            structs.InstanceSummary(
                instance=i,
                type=testnet_name,
                state=testnet_state,
                comment=str(comment) if comment is not None else None,
            )
        )

    helpers.print_json(data=[item.model_dump(mode="json") for item in out_list])


def print_env_sh(env: dict[str, str]) -> None:
    """Print environment variables in a shell-compatible format."""
    content = [f"export {var_name}={shlex.quote(val)}" for var_name, val in env.items()]
    print("\n".join(content))


def cmd_print_env(
    workdir: str,
    instance_num: int,
) -> int:
    """Print environment variables for the specified testnet instance.

    The instance is not required to exist or be running; a warning is logged
    when it is not running.
    """
    workdir_pl = ca_utils.get_workdir(workdir=workdir).absolute()

    if instance_num < 0:
        LOGGER.error("Valid instance number is required.")
        return 1

    if instance_num not in ca_utils.get_running_instances(workdir=workdir_pl):
        LOGGER.warning(f"Instance {instance_num} is not running.")

    env = ca_utils.create_env_vars(workdir=workdir_pl, instance_num=instance_num)
    print_env_sh(env=env)

    return 0


def cmd_ls(workdir: str) -> int:
    """List all running testnet instances."""
    workdir_pl = ca_utils.get_workdir(workdir=workdir).absolute()
    print_instances(workdir=workdir_pl)
    return 0


def cmd_actions(
    workdir: str,
    instance_num: int,
    stop: bool = False,
    restart: bool = False,
    restart_nodes: bool = False,
) -> int:
    """Perform a single action on a running testnet instance.

    When multiple action flags are set, precedence is stop > restart > restart_nodes.
    The instance is delayed for the duration of the action and the command fails
    when the instance was recently started/stopped.
    Returns 0 on success, 1 on failure.
    """
    workdir_pl = ca_utils.get_workdir(workdir=workdir).absolute()

    if instance_num < 0:
        LOGGER.error("Valid instance number is required.")
        return 1

    if not (stop or restart or restart_nodes):
        LOGGER.error("No valid action was selected.")
        return 1

    if not ca_utils.has_supervisorctl():
        return 1

    statedir = workdir_pl / f"{ca_utils.STATE_CLUSTER_PREFIX}{instance_num}"
    env = ca_utils.create_env_vars(workdir=workdir_pl, instance_num=instance_num)

    if not ca_utils.delay_instance(instance_num=instance_num, workdir=workdir_pl):
        return 1

    try:
        # Check the running state only while the instance is delayed, so it cannot
        # be stopped and re-created by another process in the meantime.
        if instance_num not in ca_utils.get_running_instances(workdir=workdir_pl):
            LOGGER.error("Instance is not running.")
            return 1

        if stop:
            run_retval = kill_and_stop_testnet(instance_num=instance_num, workdir=workdir_pl)
        elif restart:
            run_retval = testnet_restart_all(statedir=statedir, env=env)
        else:
            run_retval = testnet_restart_nodes(statedir=statedir, env=env)
    except Exception:
        LOGGER.exception(f"Unexpected error while acting on instance {instance_num}")
        run_retval = 1
    finally:
        # Best-effort: a failed undelay expires on its own
        ca_utils.undelay_instance(instance_num=instance_num, workdir=workdir_pl)

    return run_retval


def stop_instance(instance_num: int, workdir: pl.Path) -> int:
    """Delay, stop and undelay a single running testnet instance.

    Unexpected errors are logged and reported as failure so `cmd_stopall` can
    continue with the remaining instances.
    Returns 0 on success, 1 on failure.
    """
    if not ca_utils.delay_instance(instance_num=instance_num, workdir=workdir):
        return 1

    try:
        run_retval = kill_and_stop_testnet(instance_num=instance_num, workdir=workdir)
    except Exception:
        LOGGER.exception(f"Unexpected error while stopping instance {instance_num}")
        run_retval = 1
    finally:
        # Best-effort: a failed undelay expires on its own
        ca_utils.undelay_instance(instance_num=instance_num, workdir=workdir)

    return run_retval


def cmd_stopall(workdir: str) -> int:
    """Stop all running testnet instances, best-effort.

    An instance that cannot be delayed or stopped is skipped and the remaining
    instances are still processed.
    Returns 0 only when every instance stopped cleanly, 1 otherwise.
    """
    workdir_pl = ca_utils.get_workdir(workdir=workdir).absolute()

    if not ca_utils.has_supervisorctl():
        return 1

    run_retval = 0
    for i in sorted(ca_utils.get_running_instances(workdir=workdir_pl)):
        run_retval = stop_instance(instance_num=i, workdir=workdir_pl) or run_retval

    return run_retval
