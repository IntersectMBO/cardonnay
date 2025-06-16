import contextlib
import json
import logging
import os
import pathlib as pl
import signal
import time

from cardonnay import ca_utils
from cardonnay import colors
from cardonnay import consts
from cardonnay import helpers
from cardonnay import structs

LOGGER = logging.getLogger(__name__)


def testnet_stop(statedir: pl.Path, env: dict) -> int:
    """Stop the testnet cluster by running the stop script."""
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
        helpers.run_command(str(stop_script), workdir=statedir)
    except RuntimeError:
        LOGGER.exception("Failed to stop the testnet cluster")
        return 1

    return 0


def kill_starting_testnet(pidfile: pl.Path) -> None:
    """Kill a starting testnet process if the PID file exists."""
    if not pidfile.exists():
        return

    with contextlib.suppress(Exception):
        pid = int(helpers.read_from_file(pidfile))
        os.kill(pid, signal.SIGTERM)
        time.sleep(0.5)

    pidfile.unlink()


def testnet_restart_nodes(statedir: pl.Path, env: dict) -> int:
    """Restart the testnet cluster nodes by running the restart script."""
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
        helpers.run_command(str(script), workdir=statedir)
    except RuntimeError:
        LOGGER.exception("Failed to restart the testnet cluster nodes")
        return 1

    return 0


def testnet_restart_all(statedir: pl.Path, env: dict) -> int:
    """Restart the entire testnet cluster by running the supervisorctl command."""
    script = statedir / "supervisorctl"
    if not script.exists():
        LOGGER.error(f"The supervisorctl script '{script}' does not exist.")
        return 1

    ca_utils.set_env_vars(env=env)

    cmd = f"{script} restart all"
    print(
        f"{colors.BColors.OKGREEN}Restarting the testnet cluster with `{cmd}`:{colors.BColors.ENDC}"
    )
    try:
        helpers.run_command(cmd, workdir=statedir)
    except RuntimeError:
        LOGGER.exception("Failed to restart the testnet cluster")
        return 1

    return 0


def print_instances(workdir: pl.Path) -> None:
    """Print the list of running testnet instances."""
    running_instances = sorted(ca_utils.get_running_instances(workdir=workdir))
    out_list: list[structs.InstanceSummary] = []

    for i in running_instances:
        statedir = workdir / f"state-cluster{i}"

        with (
            contextlib.suppress(Exception),
            open(statedir / ca_utils.TESTNET_JSON, encoding="utf-8") as fp_in,
        ):
            testnet_info = json.load(fp_in) or {}

        testnet_info = testnet_info if "testnet_info" in locals() else {}
        testnet_name = testnet_info.get("name") or "unknown"

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
                comment=testnet_info.get("comment"),
            )
        )

    helpers.print_json(data=[item.model_dump(mode="json") for item in out_list])


def print_env_sh(env: dict[str, str]) -> None:
    """Print environment variables in a shell-compatible format."""
    content = [f'export {var_name}="{val}"' for var_name, val in env.items()]
    print("\n".join(content))


def cmd_print_env(
    workdir: str,
    instance_num: int,
) -> int:
    """Print environment variables for the specified testnet instance."""
    workdir_pl = ca_utils.get_workdir(workdir=workdir).absolute()

    if instance_num < 0:
        LOGGER.error("Valid instance number is required.")
        return 1

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
    """Perform actions on a testnet instance."""
    workdir_pl = ca_utils.get_workdir(workdir=workdir).absolute()

    if instance_num < 0:
        LOGGER.error("Valid instance number is required.")
        return 1

    statedir = workdir_pl / f"state-cluster{instance_num}"
    env = ca_utils.create_env_vars(workdir=workdir_pl, instance_num=instance_num)

    if instance_num not in ca_utils.get_running_instances(workdir=workdir_pl):
        LOGGER.error("Instance is not running.")
        return 1

    if not ca_utils.has_supervisorctl():
        return 1

    if stop:
        kill_starting_testnet(pidfile=workdir_pl / f"start_cluster{instance_num}.pid")
        testnet_stop(statedir=statedir, env=env)
    elif restart:
        testnet_restart_all(statedir=statedir, env=env)
    elif restart_nodes:
        testnet_restart_nodes(statedir=statedir, env=env)
    else:
        LOGGER.error("No valid action was selected.")
        return 1

    return 0


def cmd_stopall(workdir: str) -> int:
    """Stop all running testnet instances."""
    workdir_pl = ca_utils.get_workdir(workdir=workdir).absolute()
    for i in ca_utils.get_running_instances(workdir=workdir_pl):
        kill_starting_testnet(pidfile=workdir_pl / f"start_cluster{i}.pid")
        statedir = workdir_pl / f"state-cluster{i}"
        env = ca_utils.create_env_vars(workdir=workdir_pl, instance_num=i)
        testnet_stop(statedir=statedir, env=env)
    return 0
