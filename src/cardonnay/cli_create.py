import contextlib
import json
import logging
import pathlib as pl
import shutil

import filelock

import cardonnay_scripts
from cardonnay import ca_utils
from cardonnay import colors
from cardonnay import helpers
from cardonnay import local_scripts
from cardonnay import structs

LOGGER = logging.getLogger(__name__)


def write_env_vars(env: dict[str, str], workdir: pl.Path, instance_num: int) -> None:
    """Write environment variables to a file for sourcing later."""
    sfile = workdir / f".source_cluster{instance_num}"
    content = [f'export {var_name}="{val}"' for var_name, val in env.items()]
    sfile.write_text("\n".join(content))


def print_available_testnets(scripts_base: pl.Path, verbose: bool) -> int:
    """Print available testnet variants."""
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

    if verbose:
        out_list = []
        for d in avail_scripts:
            try:
                with open(scripts_base / d / ca_utils.TESTNET_JSON, encoding="utf-8") as fp_in:
                    testnet_info = json.load(fp_in) or {}
            except Exception:
                testnet_info = {"name": d}
            out_list.append(testnet_info)
        helpers.print_json(data=out_list)
    else:
        helpers.print_json(data=avail_scripts)
    return 0


def get_start_info(statedir: pl.Path, testnet_variant: str) -> structs.StartInfo:
    """Get information about the starting testnet instance."""
    instance_num = int(statedir.name[ca_utils.STATE_CLUSTER_PREFIX_LEN :])
    workdir = statedir.parent

    start_pid = -1
    pidfile = workdir / f"start_cluster{instance_num}.pid"
    if pidfile.exists():
        pid = 0
        with contextlib.suppress(Exception):
            pid = int(helpers.read_from_file(pidfile))
        if pid:
            start_pid = pid

    start_logfile = None
    logfile = workdir / f"start_cluster{instance_num}.log"
    if logfile.exists():
        start_logfile = logfile

    start_info = structs.StartInfo(
        instance=instance_num,
        type=testnet_variant,
        dir=statedir,
        start_pid=start_pid if start_pid > 0 else None,
        start_logfile=start_logfile,
    )

    return start_info


def testnet_start(
    testnetdir: pl.Path,
    workdir: pl.Path,
    env: dict,
    instance_num: int,
    testnet_variant: str,
    background: bool,
) -> int:
    """Start the testnet cluster using the start script."""
    if not ca_utils.check_env_sanity():
        return 1

    start_script = testnetdir / "start-cluster"
    if not start_script.exists():
        LOGGER.error(f"Start script '{start_script}' does not exist.")
        return 1

    ca_utils.set_env_vars(env=env)

    logfile = workdir / f"start_cluster{instance_num}.log"
    logfile.unlink(missing_ok=True)

    if background:
        start_process = helpers.run_detached_command(
            command=str(start_script), logfile=logfile, workdir=workdir
        )

        pidfile = workdir / f"start_cluster{instance_num}.pid"
        pidfile.unlink(missing_ok=True)
        pidfile.write_text(str(start_process.pid))

        statedir = workdir / f"{ca_utils.STATE_CLUSTER_PREFIX}{instance_num}"
        helpers.print_json(get_start_info(statedir=statedir, testnet_variant=testnet_variant))
    else:
        print(
            f"{colors.BColors.OKGREEN}Starting the testnet cluster with "
            f"`{start_script}`:{colors.BColors.ENDC}"
        )
        try:
            helpers.run_command(command=str(start_script), workdir=workdir)
        except RuntimeError:
            LOGGER.exception("Failed to start the testnet cluster")
            return 1

    return 0


def add_comment(destdir: pl.Path, comment: str) -> None:
    """Add a comment to the testnet info file in the destination directory."""
    testnet_file = destdir / ca_utils.TESTNET_JSON
    try:
        with open(testnet_file, encoding="utf-8") as fp_in:
            testnet_info: dict = json.load(fp_in) or {}
    except Exception:
        testnet_info = {}

    testnet_info["comment"] = comment
    helpers.write_json(out_file=testnet_file, content=testnet_info)


def cmd_create(  # noqa: PLR0911, C901
    testnet_variant: str,
    comment: str,
    listit: bool,
    background: bool,
    generate_only: bool,
    keep: bool,
    stake_pools_num: int,
    ports_base: int,
    workdir: str,
    instance_num: int,
    verbose: int,
) -> int:
    """Create a testnet cluster with the specified parameters."""
    scripts_base = pl.Path(str(cardonnay_scripts.SCRIPTS_ROOT))

    if listit or not testnet_variant:
        return print_available_testnets(scripts_base=scripts_base, verbose=bool(verbose))

    scriptsdir = scripts_base / testnet_variant
    if not scriptsdir.exists():
        LOGGER.error(f"Testnet variant '{testnet_variant}' does not exist in '{scripts_base}'.")
        return 1

    if instance_num > ca_utils.MAX_INSTANCES:
        LOGGER.error(
            f"Instance number {instance_num} exceeds maximum allowed {ca_utils.MAX_INSTANCES}."
        )
        return 1

    if workdir and (
        run_inst_default := ca_utils.get_running_instances(workdir=ca_utils.get_workdir(workdir=""))
    ):
        run_insts_str = ",".join(sorted(str(i) for i in run_inst_default))
        LOGGER.error(f"Instances running in the default workdir '{workdir}': {run_insts_str}")
        LOGGER.error("Stop them first before using custom work dir.")
        return 1

    workdir_pl = ca_utils.get_workdir(workdir=workdir)
    workdir_abs = workdir_pl.absolute()

    lockfile = str(workdir_abs / ca_utils.DELAY_LOCK)
    with filelock.FileLock(lock_file=lockfile, timeout=2):
        avail_instances_gen = ca_utils.get_available_instances(workdir=workdir_abs)
        delay_instances = ca_utils.get_delay_instances(workdir=workdir_abs)
        if instance_num < 0:
            for _ in range(ca_utils.MAX_INSTANCES + 1):
                try:
                    instance_num = next(avail_instances_gen)
                except StopIteration:
                    LOGGER.error("All instances are already in use.")  # noqa: TRY400
                    return 1
                if instance_num not in delay_instances:
                    break
        elif instance_num not in avail_instances_gen:
            LOGGER.error(f"Instance number {instance_num} is already in use.")
            return 1
        elif instance_num in delay_instances:
            LOGGER.error(
                f"There was a recent attempt to start/stop the instance number {instance_num}. "
                "Re-try later."
            )
            return 1

        ca_utils.create_delay_file(instance_num=instance_num, workdir=workdir_abs)

    destdir = workdir_pl / f"cluster{instance_num}_{testnet_variant}"
    destdir_abs = destdir.absolute()

    def _undelay() -> None:
        ca_utils.undelay_instance(instance_num=instance_num, workdir=workdir_abs)

    if not keep:
        shutil.rmtree(destdir_abs, ignore_errors=True)

    if destdir.exists():
        LOGGER.error(f"Destination directory '{destdir}' already exists.")
        _undelay()
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
        _undelay()
        return 1

    if comment:
        add_comment(destdir=destdir_abs, comment=comment)

    env = ca_utils.create_env_vars(workdir=workdir_abs, instance_num=instance_num)
    write_env_vars(env=env, workdir=workdir_abs, instance_num=instance_num)

    LOGGER.debug(f"Testnet files generated to {destdir}")

    run_retval = 0
    if generate_only:
        print(
            f"🚀 {colors.BColors.OKGREEN}You can now start the testnet cluster "
            f"with:{colors.BColors.ENDC}"
        )
        print(f"source {workdir_pl}/.source_cluster{instance_num}")
        print(f"{destdir}/start-cluster")
        _undelay()
    else:
        run_retval = testnet_start(
            testnetdir=destdir_abs,
            workdir=workdir_abs,
            env=env,
            instance_num=instance_num,
            testnet_variant=testnet_variant,
            background=background,
        )
        if not background:
            _undelay()

    return run_retval
