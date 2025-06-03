import json
import logging
import pathlib as pl
import shutil

import cardonnay_scripts
from cardonnay import cli_utils
from cardonnay import helpers
from cardonnay import local_scripts

LOGGER = logging.getLogger(__name__)


def write_env_vars(env: dict[str, str], workdir: pl.Path, instance_num: int) -> None:
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

    print("Available testnet variants:")
    if verbose:
        out_list = []
        for d in avail_scripts:
            try:
                with open(scripts_base / d / "testnet.json", encoding="utf-8") as fp_in:
                    testnet_info = json.load(fp_in)
            except Exception:
                testnet_info = {"name": d}
            out_list.append(testnet_info)
        print(json.dumps(out_list, indent=2))
    else:
        for d in avail_scripts:
            print(f"  - {d}")
    return 0


def testnet_start(testnetdir: pl.Path, workdir: pl.Path, env: dict) -> int:
    if not cli_utils.check_env_sanity():
        return 1

    start_script = testnetdir / "start-cluster"
    if not start_script.exists():
        LOGGER.error(f"Start script '{start_script}' does not exist.")
        return 1

    cli_utils.set_env_vars(env=env)

    LOGGER.info(f"Starting cluster with `{start_script}`.")
    try:
        helpers.run_command(str(start_script), workdir=workdir)
    except RuntimeError:
        LOGGER.exception("Failed to start testnet")
        return 1

    return 0


def cmd_generate(  # noqa: PLR0911, C901
    testnet_variant: str,
    listit: bool,
    run: bool,
    keep: bool,
    stake_pools_num: int,
    ports_base: int,
    work_dir: str,
    instance_num: int,
    verbose: int,
) -> int:
    scripts_base = pl.Path(str(cardonnay_scripts.SCRIPTS_ROOT))

    if listit or not testnet_variant:
        return print_available_testnets(scripts_base=scripts_base, verbose=bool(verbose))

    scriptsdir = scripts_base / testnet_variant
    if not scriptsdir.exists():
        LOGGER.error(f"Testnet variant '{testnet_variant}' does not exist in '{scripts_base}'.")
        return 1

    workdir = cli_utils.get_workdir(workdir=work_dir)
    workdir_abs = workdir.absolute()
    destdir = workdir / f"cluster{instance_num}_{testnet_variant}"
    destdir_abs = destdir.absolute()

    if instance_num > cli_utils.MAX_INSTANCES:
        LOGGER.error(
            f"Instance number {instance_num} exceeds maximum allowed {cli_utils.MAX_INSTANCES}."
        )
        return 1

    avail_instances_gen = cli_utils.get_available_instances(workdir=workdir_abs)
    if instance_num < 0:
        try:
            instance_num = next(avail_instances_gen)
        except StopIteration:
            LOGGER.error("All instances are already in use.")  # noqa: TRY400
            return 1
    elif instance_num not in avail_instances_gen:
        LOGGER.error(f"Instance number {instance_num} is already in use.")
        return 1

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

    env = cli_utils.create_env_vars(workdir=workdir_abs, instance_num=instance_num)
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
