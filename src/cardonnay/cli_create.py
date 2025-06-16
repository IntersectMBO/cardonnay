import json
import logging
import pathlib as pl
import shutil

import cardonnay_scripts
from cardonnay import ca_utils
from cardonnay import colors
from cardonnay import helpers
from cardonnay import inspect_instance
from cardonnay import local_scripts

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


def testnet_start(
    testnetdir: pl.Path,
    workdir: pl.Path,
    env: dict,
    instance_num: int,
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

        statedir = workdir / f"state-cluster{instance_num}"
        helpers.wait_for_file(file=statedir / "supervisord.sock", timeout=10)

        pidfile = workdir / f"start_cluster{instance_num}.pid"
        pidfile.unlink(missing_ok=True)
        pidfile.write_text(str(start_process.pid))

        helpers.print_json(inspect_instance.get_testnet_info(statedir=statedir))
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

    avail_instances_gen = ca_utils.get_available_instances(workdir=workdir_abs)
    if instance_num < 0:
        try:
            instance_num = next(avail_instances_gen)
        except StopIteration:
            LOGGER.error("All instances are already in use.")  # noqa: TRY400
            return 1
    elif instance_num not in avail_instances_gen:
        LOGGER.error(f"Instance number {instance_num} is already in use.")
        return 1
    destdir = workdir_pl / f"cluster{instance_num}_{testnet_variant}"
    destdir_abs = destdir.absolute()

    if not keep:
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

    if comment:
        add_comment(destdir=destdir_abs, comment=comment)

    env = ca_utils.create_env_vars(workdir=workdir_abs, instance_num=instance_num)
    write_env_vars(env=env, workdir=workdir_abs, instance_num=instance_num)

    LOGGER.debug(f"Testnet files generated to {destdir}")

    if generate_only:
        print(
            f"🚀 {colors.BColors.OKGREEN}You can now start the testnet cluster "
            f"with:{colors.BColors.ENDC}"
        )
        print(f"source {workdir_pl}/.source_cluster{instance_num}")
        print(f"{destdir}/start-cluster")
    else:
        run_retval = testnet_start(
            testnetdir=destdir_abs,
            workdir=workdir_abs,
            env=env,
            instance_num=instance_num,
            background=background,
        )
        if run_retval > 0:
            return run_retval

    return 0
