"""Cardonnay CLI entry point."""

import logging
import typing as tp

import click

from cardonnay import cli_control
from cardonnay import cli_generate
from cardonnay import cli_utils

LOGGER = logging.getLogger(__name__)


def common_options(func: tp.Callable) -> tp.Callable:
    """Add shared options using a decorator."""
    for opt in reversed(
        [
            click.option(
                "-w",
                "--work-dir",
                type=click.Path(file_okay=False, dir_okay=True, path_type=str),
                default="",
                show_default=True,
                help="Path to working directory.",
            ),
        ]
    ):
        func = opt(func)
    return func


def common_options_control(func: tp.Callable) -> tp.Callable:
    """Add shared options to control group using a decorator."""
    for opt in reversed(
        [
            click.option(
                "-i",
                "--instance-num",
                type=click.IntRange(0, cli_utils.MAX_INSTANCES - 1),
                required=True,
                show_default=True,
                help="Instance number in the sequence of testnet instances.",
            ),
        ]
    ):
        func = opt(func)
    return func


def exit_with(retval: int) -> tp.NoReturn:
    click.get_current_context().exit(retval)


@click.group()
def main() -> None:
    """Cardonnay - Cardano local testnets."""
    logging.basicConfig(format="%(message)s", level=logging.INFO)


@main.command(help="Generate local testnet configuration")
@click.option("-t", "--testnet-variant", type=str, help="Testnet variant to use.")
@click.option("-l", "--ls", is_flag=True, help="List available testnet variants and exit.")
@click.option("-r", "--run", is_flag=True, help="Run the testnet immediately (default: false).")
@click.option("-k", "--keep", is_flag=True, help="Don't delete destination directory if it exists.")
@click.option(
    "-i",
    "--instance-num",
    default=-1,
    type=click.IntRange(-1, cli_utils.MAX_INSTANCES - 1),
    show_default=True,
    help="Instance number, auto-selected by default.",
)
@click.option(
    "-s",
    "--stake-pools-num",
    type=click.IntRange(3, 10),
    default=3,
    show_default=True,
    help="Number of stake pools to create.",
)
@click.option(
    "-p", "--ports-base", type=int, default=23000, show_default=True, help="Base port number."
)
@click.option("-v", "--verbose", count=True, help="Increase verbosity (use -vv for more).")
@common_options
@click.pass_context
def generate(
    ctx: click.Context,
    testnet_variant: str,
    ls: bool,
    run: bool,
    keep: bool,
    instance_num: int,
    stake_pools_num: int,
    ports_base: int,
    verbose: int,
    work_dir: str,
) -> None:
    # Check if no args were passed other than the command itself
    if not ctx.args and not any([testnet_variant, ls]):
        click.echo(ctx.get_help())
        ctx.exit()

    retval = cli_generate.cmd_generate(
        testnet_variant=testnet_variant,
        listit=ls,
        run=run,
        keep=keep,
        stake_pools_num=stake_pools_num,
        ports_base=ports_base,
        work_dir=work_dir,
        instance_num=instance_num,
        verbose=verbose,
    )
    ctx.exit(retval)


@main.group(help="Control existing testnets.")
def control() -> None:
    """Control interface for Cardonnay instances."""


def make_control_cmd(flag_name: str, help_text: str) -> None:
    @control.command(name=flag_name.replace("_", "-"), help=help_text)
    @common_options_control
    @common_options
    def cmd(instance_num: int, work_dir: str) -> None:
        retval = cli_control.cmd_control(
            **{flag_name: True},
            work_dir=work_dir,
            instance_num=instance_num,
        )
        exit_with(retval)


@control.command(name="ls", help="List running testnet instances.")
@common_options
def ls(work_dir: str) -> None:
    retval = cli_control.cmd_ls(work_dir=work_dir)
    exit_with(retval)


for name, help_text in [
    ("stop", "Stop the running testnet."),
    ("restart", "Restart all processes of the testnet."),
    ("restart_nodes", "Restart only nodes of the testnet."),
    ("inspect", "Inspect running testnet."),
    ("print_env", "Print environment variables for the testnet."),
]:
    make_control_cmd(name, help_text)
