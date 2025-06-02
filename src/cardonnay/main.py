"""Cardonnay CLI entry point."""

import logging
import typing as tp

import click

from cardonnay import cli

LOGGER = logging.getLogger(__name__)


def common_options(func: tp.Callable) -> tp.Callable:
    """Add shared options using a decorator."""
    func = click.option(
        "-w", "--work-dir", default="", help="Path to working directory.", type=str
    )(func)
    func = click.option(
        "-i",
        "--instance-num",
        default=0,
        help="Instance number in the sequence of cluster instances (default: 0).",
        type=int,
    )(func)
    return func


@click.group()
def main() -> None:
    """Cardonnay - Cardano local testnets."""
    logging.basicConfig(format="%(message)s", level=logging.INFO)


@main.command(help="Generate local testnet configuration")
@click.option("-t", "--testnet-variant", help="Testnet variant to use.", type=str)
@click.option("-l", "--list", is_flag=True, help="List available testnet variants and exit.")
@click.option("-r", "--run", is_flag=True, help="Run the testnet immediately (default: false).")
@click.option("-c", "--clean", is_flag=True, help="Delete destination directory if it exists.")
@click.option(
    "-s",
    "--stake-pools-num",
    type=int,
    default=3,
    help="Number of stake pools to create (default: 3).",
)
@click.option(
    "-p",
    "--ports-base",
    type=int,
    default=23000,
    help="Base port number (default: 23000).",
)
@common_options
def generate(
    testnet_variant: str,
    list: bool,
    run: bool,
    clean: bool,
    stake_pools_num: int,
    ports_base: int,
    work_dir: str,
    instance_num: int,
) -> None:
    retval = cli.cmd_generate(
        testnet_variant,
        list,
        run,
        clean,
        stake_pools_num,
        ports_base,
        work_dir,
        instance_num,
    )
    raise SystemExit(retval)


@main.command(help="Control existing testnets.")
@click.option("-l", "--list", is_flag=True, help="List running testnet instances.")
@click.option("-s", "--stop", is_flag=True, help="Stop the running testnet.")
@click.option("-r", "--restart", is_flag=True, help="Restart all processes of the testnet.")
@click.option("-n", "--restart-nodes", is_flag=True, help="Restart only nodes of the testnet.")
@common_options
def control(
    list: bool,
    stop: bool,
    restart: bool,
    restart_nodes: bool,
    work_dir: str,
    instance_num: int,
) -> None:
    retval = cli.cmd_control(list, stop, restart, restart_nodes, work_dir, instance_num)
    raise SystemExit(retval)
