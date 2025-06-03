import json
import logging
import pathlib as pl

from cardonnay import cli_utils
from cardonnay import helpers

LOGGER = logging.getLogger(__name__)

STATUS_STARTED = "status_started"


def testnet_stop(statedir: pl.Path, env: dict) -> int:
    if not cli_utils.check_env_sanity():
        return 1

    stop_script = statedir / "stop-cluster"
    if not stop_script.exists():
        LOGGER.error(f"Stop script '{stop_script}' does not exist.")
        return 1

    cli_utils.set_env_vars(env=env)

    LOGGER.info(f"Stopping testnet with `{stop_script}`.")
    try:
        helpers.run_command(str(stop_script), workdir=statedir)
    except RuntimeError:
        LOGGER.exception("Failed to stop testnet")
        return 1

    return 0


def testnet_restart_nodes(statedir: pl.Path, env: dict) -> int:
    if not cli_utils.check_env_sanity():
        return 1

    script = statedir / "supervisorctl_restart_nodes"
    if not script.exists():
        LOGGER.error(f"Restart nodes script '{script}' does not exist.")
        return 1

    cli_utils.set_env_vars(env=env)

    LOGGER.info(f"Restarting testnet nodes with `{script}`.")
    try:
        helpers.run_command(str(script), workdir=statedir)
    except RuntimeError:
        LOGGER.exception("Failed to restart testnet nodes")
        return 1

    return 0


def testnet_restart_all(statedir: pl.Path, env: dict) -> int:
    if not cli_utils.check_env_sanity():
        return 1

    script = statedir / "supervisorctl"
    if not script.exists():
        LOGGER.error(f"The supervisorctl script '{script}' does not exist.")
        return 1

    cli_utils.set_env_vars(env=env)

    cmd = f"{script} restart all"
    LOGGER.info(f"Restarting testnet with `{cmd}`.")
    try:
        helpers.run_command(cmd, workdir=statedir)
    except RuntimeError:
        LOGGER.exception("Failed to restart testnet")
        return 1

    return 0


def print_instances(workdir: pl.Path) -> None:
    running_instances = sorted(cli_utils.get_running_instances(workdir=workdir))

    print("Running instances:")
    out_list = []
    for i in running_instances:
        statedir = workdir / f"state-cluster{i}"
        try:
            with open(statedir / cli_utils.TESTNET_JSON, encoding="utf-8") as fp_in:
                testnet_info = json.load(fp_in) or {}
        except Exception:
            testnet_info = {}
        testnet_name = testnet_info.get("name") or "unknown"
        testnet_status = "started" if (statedir / STATUS_STARTED).exists() else "starting"
        instance_info = {"instance": i, "type": testnet_name, "status": testnet_status}
        testnet_comment = testnet_info.get("comment")
        if testnet_comment:
            instance_info["comment"] = testnet_comment
        out_list.append(instance_info)
    print(json.dumps(out_list, indent=2))


def print_env_sh(env: dict[str, str]) -> None:
    content = [f'export {var_name}="{val}"' for var_name, val in env.items()]
    print("\n".join(content))


def cmd_control(
    work_dir: str,
    instance_num: int,
    stop: bool = False,
    restart: bool = False,
    restart_nodes: bool = False,
    inspect: bool = False,
    print_env: bool = False,
) -> int:
    workdir = cli_utils.get_workdir(workdir=work_dir)
    workdir_abs = workdir.absolute()

    if instance_num < 0:
        LOGGER.error("Valid instance number is required.")
        return 1

    statedir = workdir_abs / f"state-cluster{instance_num}"
    env = cli_utils.create_env_vars(workdir=workdir_abs, instance_num=instance_num)

    if stop:
        testnet_stop(statedir=statedir, env=env)
    elif restart:
        testnet_restart_all(statedir=statedir, env=env)
    elif restart_nodes:
        testnet_restart_nodes(statedir=statedir, env=env)
    elif print_env:
        print_env_sh(env=env)
    elif inspect:
        pass
    else:
        LOGGER.error("No valid action was selected.")
        return 1

    return 0


def cmd_ls(work_dir: str) -> int:
    workdir = cli_utils.get_workdir(workdir=work_dir)
    workdir_abs = workdir.absolute()

    print_instances(workdir=workdir_abs)
    return 0
