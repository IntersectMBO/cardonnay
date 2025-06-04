import logging
import pathlib as pl
import typing as tp

from cardonnay import cli_utils
from cardonnay import helpers
from cardonnay import inspect_instance

LOGGER = logging.getLogger(__name__)


def run_cmd_with_state(
    work_dir: str,
    instance_num: int,
    data_fn: tp.Callable[[pl.Path], dict],
) -> int:
    workdir = cli_utils.get_workdir(workdir=work_dir).absolute()
    statedir = workdir / f"state-cluster{instance_num}"

    if instance_num < 0:
        LOGGER.error("Valid instance number is required.")
        return 1

    if not statedir.exists():
        LOGGER.error("State dir for the instance doesn't exist.")
        return 1

    helpers.print_json(data=data_fn(statedir))
    return 0


def cmd_faucet(work_dir: str, instance_num: int) -> int:
    return run_cmd_with_state(
        work_dir=work_dir,
        instance_num=instance_num,
        data_fn=inspect_instance.load_faucet_data,
    )


def cmd_pools(work_dir: str, instance_num: int) -> int:
    return run_cmd_with_state(
        work_dir=work_dir,
        instance_num=instance_num,
        data_fn=inspect_instance.load_pools_data,
    )


def cmd_status(work_dir: str, instance_num: int) -> int:
    return run_cmd_with_state(
        work_dir=work_dir,
        instance_num=instance_num,
        data_fn=lambda s: {
            **inspect_instance.get_testnet_info(statedir=s),
            **inspect_instance.get_control_env(statedir=s),
        },
    )


def cmd_config(work_dir: str, instance_num: int) -> int:
    return run_cmd_with_state(
        work_dir=work_dir,
        instance_num=instance_num,
        data_fn=inspect_instance.get_config,
    )
