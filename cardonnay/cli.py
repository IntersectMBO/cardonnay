"""Cardonnay - Cardano local testnets."""

import argparse
import logging
import os
import pathlib as pl
import shutil

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


def get_args() -> argparse.Namespace:
    """Get command line arguments."""
    # Arguments shared by multiple subparsers. Not using parent parser, because these options
    # should go last in the `--help` output, and there's no possibility to influence options
    # order with parent parsers.
    shared_args: list[tuple[tuple, dict]] = [
        (("-w", "--work-dir"), {"default": "", "help": "Path to working directory."}),
        (
            ("-i", "--instance-num"),
            {
                "type": int,
                "default": 0,
                "help": "Instance number in the sequence of cluster instances (default: 0).",
            },
        ),
    ]

    def add_shared_args(parser: argparse.ArgumentParser) -> None:
        for flags, kwargs in shared_args:
            parser.add_argument(*flags, **kwargs)

    parser = argparse.ArgumentParser(description=__doc__.split("\n", maxsplit=1)[0])
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate_parser = subparsers.add_parser("generate", help="Generate local testnet configuration")
    generate_parser.add_argument(
        "-t",
        "--testnet-variant",
        help="Testnet variant to use.",
    )
    generate_parser.add_argument(
        "-l",
        "--list",
        action="store_true",
        help="List available testnet variants and exit.",
    )
    generate_parser.add_argument(
        "-r",
        "--run",
        action="store_true",
        help="Run the testnet immediately (default: false).",
    )
    generate_parser.add_argument(
        "-c",
        "--clean",
        action="store_true",
        help="Delete the destination directory if it already exists (default: false).",
    )
    generate_parser.add_argument(
        "-s",
        "--stake-pools-num",
        type=int,
        default=3,
        help="Number of stake pools to create (default: 3).",
    )
    generate_parser.add_argument(
        "-p",
        "--ports-base",
        type=int,
        default=23000,
        help="Base port number (default: 23000).",
    )
    add_shared_args(generate_parser)

    control_parser = subparsers.add_parser("control", help="Control existing testnets.")
    control_parser.add_argument(
        "-l",
        "--list",
        action="store_true",
        help="List running testnet instances.",
    )
    control_parser.add_argument(
        "-s",
        "--stop",
        action="store_true",
        help="Stop the running testnet.",
    )
    control_parser.add_argument(
        "-r",
        "--restart",
        action="store_true",
        help="Restart processes of the running testnet.",
    )
    control_parser.add_argument(
        "-n",
        "--restart-nodes",
        action="store_true",
        help="Restart nodes of the running testnet.",
    )
    add_shared_args(control_parser)

    return parser.parse_args()


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


def cmd_generate(args: argparse.Namespace) -> int:
    scripts_base = pl.Path(__file__).parent / "cardonnay_scripts"
    scripts_name = args.testnet_variant

    if args.list or not scripts_name:
        return list_available_testnets(scripts_base=scripts_base)

    scriptsdir = pl.Path(__file__).parent / "cardonnay_scripts" / scripts_name

    instance_num = args.instance_num
    num_pools = args.stake_pools_num
    ports_base = args.ports_base
    workdir = get_workdir(workdir=args.work_dir)
    workdir_abs = workdir.absolute()
    destdir = workdir / f"cluster{instance_num}_{scripts_name}"
    destdir_abs = destdir.absolute()

    if args.clean:
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
            num_pools=num_pools,
            ports_base=ports_base,
        )
    except Exception:
        LOGGER.exception("Failure")
        return 1

    env = create_env_vars(workdir=workdir_abs, instance_num=instance_num)
    write_env_vars(env=env, workdir=workdir_abs, instance_num=instance_num)

    LOGGER.info(f"Testnet files generated to {destdir}")

    if args.run:
        run_retval = testnet_start(testnetdir=destdir_abs, workdir=workdir_abs, env=env)
        if run_retval > 0:
            return run_retval
    else:
        LOGGER.info("You can start the testnet with:")
        LOGGER.info(f"source {workdir}/.source_cluster{instance_num}")
        LOGGER.info(f"{destdir}/start-cluster")

    return 0


def cmd_control(args: argparse.Namespace) -> int:
    instance_num = args.instance_num
    workdir = get_workdir(workdir=args.work_dir)
    workdir_abs = workdir.absolute()
    statedir = workdir_abs / f"state-cluster{instance_num}"
    env = create_env_vars(workdir=workdir_abs, instance_num=instance_num)

    def _list_instances() -> None:
        running_instances = get_running_instances(workdir=workdir_abs)
        LOGGER.info(f"Running instances: {running_instances}")

    if args.list:
        _list_instances()
        return 0

    if args.stop:
        testnet_stop(statedir=statedir, env=env)
    elif args.restart:
        testnet_restart_all(statedir=statedir, env=env)
    elif args.restart_nodes:
        testnet_restart_nodes(statedir=statedir, env=env)
    else:
        _list_instances()

    return 0


def main() -> int:
    logging.basicConfig(format="%(message)s", level=logging.INFO)
    args = get_args()

    if args.command == "generate":
        return cmd_generate(args=args)
    if args.command == "control":
        return cmd_control(args=args)

    return 0
