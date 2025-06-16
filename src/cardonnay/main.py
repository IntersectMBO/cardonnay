"""Cardonnay CLI entry point."""

import logging
import typing as tp

import click

from cardonnay import ca_utils
from cardonnay import cli_control
from cardonnay import cli_create
from cardonnay import cli_inspect
from cardonnay import color_logger

LOGGER = logging.getLogger(__name__)


def common_options_dir(func: tp.Callable) -> tp.Callable:
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


def common_options_instance(func: tp.Callable) -> tp.Callable:
    """Add shared options to control group using a decorator."""
    for opt in reversed(
        [
            click.option(
                "-i",
                "--instance-num",
                type=click.IntRange(0, ca_utils.MAX_INSTANCES - 1),
                required=True,
                show_default=True,
                help="Instance number.",
            ),
        ]
    ):
        func = opt(func)
    return func


def exit_with(retval: int) -> tp.NoReturn:
    click.get_current_context().exit(retval)


def validate_comment(
    ctx: click.Context,  # noqa: ARG001
    param: click.Parameter,  # noqa: ARG001
    value: str,
) -> str:
    max_char = 255
    if value is not None and len(value) > max_char:
        err = f"must be {max_char} characters or fewer."
        raise click.BadParameter(err)
    return value


@click.group()
def main() -> None:
    """Cardonnay - Cardano local testnets."""
    color_logger.configure_logging()


@main.command(help="Create a local testnet.")
@click.option("-t", "--testnet-variant", type=str, help="Testnet variant to use.")
@click.option(
    "-c", "--comment", type=str, callback=validate_comment, help="Comment for the testnet."
)
@click.option("-l", "--ls", is_flag=True, help="List available testnet variants and exit.")
@click.option(
    "-b",
    "--background",
    is_flag=True,
    help="Start the testnet cluster script in background (default: false).",
)
@click.option(
    "-g", "--generate-only", is_flag=True, help="Don't run the testnet cluster (default: false)."
)
@click.option("-k", "--keep", is_flag=True, help="Don't delete destination directory if it exists.")
@click.option(
    "-i",
    "--instance-num",
    default=-1,
    type=click.IntRange(-1, ca_utils.MAX_INSTANCES - 1),
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
@common_options_dir
@click.pass_context
def create(
    ctx: click.Context,
    testnet_variant: str,
    comment: str,
    ls: bool,
    background: bool,
    generate_only: bool,
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
        ctx.exit(1)

    retval = cli_create.cmd_create(
        testnet_variant=testnet_variant,
        comment=comment,
        listit=ls,
        background=background,
        generate_only=generate_only,
        keep=keep,
        stake_pools_num=stake_pools_num,
        ports_base=ports_base,
        workdir=work_dir,
        instance_num=instance_num,
        verbose=verbose,
    )
    ctx.exit(retval)


@main.group(help="Control existing testnet instances.")
def control() -> None:
    """Control interface for Cardonnay instances."""


def make_actions_cmd(flag_name: str, help_text: str) -> None:
    @control.command(name=flag_name.replace("_", "-"), help=help_text)
    @common_options_instance
    @common_options_dir
    def cmd(instance_num: int, work_dir: str) -> None:
        retval = cli_control.cmd_actions(
            **{flag_name: True},
            workdir=work_dir,
            instance_num=instance_num,
        )
        exit_with(retval)


@control.command(name="ls", help="List running testnet instances.")
@common_options_dir
def control_ls(work_dir: str) -> None:
    retval = cli_control.cmd_ls(workdir=work_dir)
    exit_with(retval)


@control.command(name="print-env", help="Print environment variables for the testnet instance.")
@common_options_instance
@common_options_dir
def control_print_env(instance_num: int, work_dir: str) -> None:
    retval = cli_control.cmd_print_env(workdir=work_dir, instance_num=instance_num)
    exit_with(retval)


for name, help_text in [
    ("stop", "Stop the running testnet cluster."),
    ("restart", "Restart all processes of the testnet cluster."),
    ("restart_nodes", "Restart only node processes of the testnet cluster."),
]:
    make_actions_cmd(name, help_text)


@control.command(name="stop-all", help="Stop all running testnet instances.")
@common_options_dir
def control_stopall(work_dir: str) -> None:
    retval = cli_control.cmd_stopall(workdir=work_dir)
    exit_with(retval)


@main.group(help="Inspect a testnet instance.")
def inspect() -> None:
    """Control interface for Cardonnay instances."""


@inspect.command(name="faucet", help="Inspect faucet.")
@common_options_instance
@common_options_dir
def inspect_faucet(instance_num: int, work_dir: str) -> None:
    retval = cli_inspect.cmd_faucet(
        workdir=work_dir,
        instance_num=instance_num,
    )
    exit_with(retval)


@inspect.command(name="pools", help="Inspect pools.")
@common_options_instance
@common_options_dir
def inspect_pools(instance_num: int, work_dir: str) -> None:
    retval = cli_inspect.cmd_pools(
        workdir=work_dir,
        instance_num=instance_num,
    )
    exit_with(retval)


@inspect.command(name="status", help="Inspect status.")
@common_options_instance
@common_options_dir
def inspect_status(instance_num: int, work_dir: str) -> None:
    retval = cli_inspect.cmd_status(
        workdir=work_dir,
        instance_num=instance_num,
    )
    exit_with(retval)


@inspect.command(name="config", help="Inspect configuration.")
@common_options_instance
@common_options_dir
def inspect_config(instance_num: int, work_dir: str) -> None:
    retval = cli_inspect.cmd_config(
        workdir=work_dir,
        instance_num=instance_num,
    )
    exit_with(retval)
