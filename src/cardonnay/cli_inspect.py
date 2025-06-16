import logging
import pathlib as pl

from cardonnay import ca_utils
from cardonnay import helpers
from cardonnay import inspect_instance

LOGGER = logging.getLogger(__name__)


def check_prereq(
    statedir: pl.Path,
    instance_num: int,
) -> int:
    if instance_num < 0:
        LOGGER.error("Valid instance number is required.")
        return 1

    if not statedir.exists():
        LOGGER.error("State dir for the instance doesn't exist.")
        return 1

    return 0


def cmd_faucet(workdir: str, instance_num: int) -> int:
    workdir_pl = ca_utils.get_workdir(workdir=workdir).absolute()
    statedir = workdir_pl / f"state-cluster{instance_num}"

    if (ret := check_prereq(statedir=statedir, instance_num=instance_num)) > 0:
        return ret

    helpers.print_json(data=inspect_instance.load_faucet_data(statedir=statedir))
    return 0


def cmd_pools(workdir: str, instance_num: int) -> int:
    workdir_pl = ca_utils.get_workdir(workdir=workdir).absolute()
    statedir = workdir_pl / f"state-cluster{instance_num}"

    if (ret := check_prereq(statedir=statedir, instance_num=instance_num)) > 0:
        return ret

    pools_data = [
        d.model_dump(mode="json") for d in inspect_instance.load_pools_data(statedir=statedir)
    ]
    helpers.print_json(data=pools_data)
    return 0


def cmd_status(workdir: str, instance_num: int) -> int:
    workdir_pl = ca_utils.get_workdir(workdir=workdir).absolute()
    statedir = workdir_pl / f"state-cluster{instance_num}"

    if (ret := check_prereq(statedir=statedir, instance_num=instance_num)) > 0:
        return ret

    helpers.print_json(data=inspect_instance.get_testnet_info(statedir=statedir))
    return 0


def cmd_config(workdir: str, instance_num: int) -> int:
    workdir_pl = ca_utils.get_workdir(workdir=workdir).absolute()
    statedir = workdir_pl / f"state-cluster{instance_num}"

    if (ret := check_prereq(statedir=statedir, instance_num=instance_num)) > 0:
        return ret

    helpers.print_json(data=inspect_instance.get_config(statedir=statedir))
    return 0
