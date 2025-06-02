import logging
import os
import pathlib as pl
import shutil

import cardonnay_scripts
from cardonnay import helpers
from cardonnay import local_scripts
from cardonnay import ttypes

LOGGER = logging.getLogger(__name__)


def create_env_vars(workdir: pl.Path, instance_num: int) -> dict[str, str]:
    env = {"CARDANO_NODE_SOCKET_PATH": f"{workdir}/state-cluster{instance_num}/bft1.socket"}
    return env


def write_env_vars(env: dict[str, str], workdir: pl.Path, instance_num: int) -> None:
    sfile = workdir / f".source_cluster{instance_num}"
    content = [f'export {var_name}="{val}"' for var_name, val in env.items()]
    sfile.write_text("\n".join(content))


def set_env_vars(env: dict[str, str]) -> None:
    for var_name, val in env.items():
        os.environ[var_name] = val


def list_available_testnets(scripts_base: pl.Path) -> int:
    """List available script directories."""
    if not scripts_base.exists():
        LOGGER.error(f"Scripts directory '{scripts_base}' does not exist.")
        return 1
    avail_scripts = sorted(
        d.name
        for d in scripts_base.iterdir()
        if d.is_dir()
        if not ("egg-info" in d.name or d.name == "common")
    )
    if not avail_scripts:
        LOGGER.error(f"No script directories found in '{scripts_base}'.")
        return 1
    LOGGER.info("Available testnet variants:")
    for script in avail_scripts:
        LOGGER.info(f"  - {script}")
    return 0


def check_env_sanity() -> bool:
    retval = True
    bins = ["jq", "supervisord", "supervisorctl", "cardano-node", "cardano-cli"]
    for b in bins:
        if not shutil.which(b):
            LOGGER.error(f"Required binary '{b}' is not found in PATH.")
            retval = False
    return retval


def testnet_start(testnetdir: pl.Path, workdir: pl.Path, env: dict) -> int:
    if not check_env_sanity():
        return 1

    start_script = testnetdir / "start-cluster"
    if not start_script.exists():
        LOGGER.error(f"Start script '{start_script}' does not exist.")
        return 1

    set_env_vars(env=env)

    LOGGER.info(f"Starting cluster with `{start_script}`.")
    try:
        helpers.run_command(str(start_script), workdir=workdir)
    except RuntimeError:
        LOGGER.exception("Failed to start testnet")
        return 1

    return 0


def testnet_stop(statedir: pl.Path, env: dict) -> int:
    if not check_env_sanity():
        return 1

    stop_script = statedir / "stop-cluster"
    if not stop_script.exists():
        LOGGER.error(f"Stop script '{stop_script}' does not exist.")
        return 1

    set_env_vars(env=env)

    LOGGER.info(f"Stopping testnet with `{stop_script}`.")
    try:
        helpers.run_command(str(stop_script), workdir=statedir)
    except RuntimeError:
        LOGGER.exception("Failed to stop testnet")
        return 1

    return 0


def testnet_restart_nodes(statedir: pl.Path, env: dict) -> int:
    if not check_env_sanity():
        return 1

    script = statedir / "supervisorctl_restart_nodes"
    if not script.exists():
        LOGGER.error(f"Restart nodes script '{script}' does not exist.")
        return 1

    set_env_vars(env=env)

    LOGGER.info(f"Restarting testnet nodes with `{script}`.")
    try:
        helpers.run_command(str(script), workdir=statedir)
    except RuntimeError:
        LOGGER.exception("Failed to restart testnet nodes")
        return 1

    return 0


def testnet_restart_all(statedir: pl.Path, env: dict) -> int:
    if not check_env_sanity():
        return 1

    script = statedir / "supervisorctl"
    if not script.exists():
        LOGGER.error(f"The supervisorctl script '{script}' does not exist.")
        return 1

    set_env_vars(env=env)

    cmd = f"{script} restart all"
    LOGGER.info(f"Restarting testnet with `{cmd}`.")
    try:
        helpers.run_command(cmd, workdir=statedir)
    except RuntimeError:
        LOGGER.exception("Failed to restart testnet")
        return 1

    return 0


def get_running_instances(workdir: pl.Path) -> list[int]:
    instances = sorted(
        int(s.parent.name.replace("state-cluster", ""))
        for s in workdir.glob("state-cluster*/supervisord.sock")
    )
    return instances


def get_workdir(workdir: ttypes.FileType) -> pl.Path:
    if workdir != "":
        return pl.Path(workdir)

    if pl.Path("cardonnay.py").is_file():
        return pl.Path() / "run_workdir"

    return pl.Path("/var/tmp/cardonnay")


def cmd_generate(
    testnet_variant: str,
    list: bool,
    run: bool,
    clean: bool,
    stake_pools_num: int,
    ports_base: int,
    work_dir: str,
    instance_num: int,
) -> int:
    scripts_base = pl.Path(str(cardonnay_scripts.SCRIPTS_ROOT))

    if list or not testnet_variant:
        return list_available_testnets(scripts_base=scripts_base)

    scriptsdir = scripts_base / testnet_variant
    workdir = get_workdir(workdir=work_dir)
    workdir_abs = workdir.absolute()
    destdir = workdir / f"cluster{instance_num}_{testnet_variant}"
    destdir_abs = destdir.absolute()

    if clean:
        shutil.rmtree(destdir_abs, ignore_errors=True)

    if destdir.exists():
        LOGGER.error(f"Destination directory '{destdir}' already exists.")
        return 1

    destdir_abs.mkdir(parents=True)

    try:
        local_scripts.prepare_scripts_files(
            destdir=destdir_abs,
            scriptsdir=scriptsdir,
            instance_num=instance_num,
            num_pools=stake_pools_num,
            ports_base=ports_base,
        )
    except Exception:
        LOGGER.exception("Failure")
        return 1

    env = create_env_vars(workdir=workdir_abs, instance_num=instance_num)
    write_env_vars(env=env, workdir=workdir_abs, instance_num=instance_num)

    LOGGER.info(f"Testnet files generated to {destdir}")

    if run:
        run_retval = testnet_start(testnetdir=destdir_abs, workdir=workdir_abs, env=env)
        if run_retval > 0:
            return run_retval
    else:
        LOGGER.info("You can start the testnet with:")
        LOGGER.info(f"source {workdir}/.source_cluster{instance_num}")
        LOGGER.info(f"{destdir}/start-cluster")

    return 0


def cmd_control(
    list: bool,
    stop: bool,
    restart: bool,
    restart_nodes: bool,
    work_dir: str,
    instance_num: int,
) -> int:
    workdir = get_workdir(workdir=work_dir)
    workdir_abs = workdir.absolute()
    statedir = workdir_abs / f"state-cluster{instance_num}"
    env = create_env_vars(workdir=workdir_abs, instance_num=instance_num)

    def _list_instances() -> None:
        running_instances = get_running_instances(workdir=workdir_abs)
        LOGGER.info(f"Running instances: {running_instances}")

    if list:
        _list_instances()
        return 0

    if stop:
        testnet_stop(statedir=statedir, env=env)
    elif restart:
        testnet_restart_all(statedir=statedir, env=env)
    elif restart_nodes:
        testnet_restart_nodes(statedir=statedir, env=env)
    else:
        _list_instances()

    return 0
