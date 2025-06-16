import logging
import os
import pathlib as pl
import shutil
import typing as tp

from cardonnay import ttypes

LOGGER = logging.getLogger(__name__)

MAX_INSTANCES = 10
TESTNET_JSON = "testnet.json"
STATUS_STARTED = "status_started"


def create_env_vars(workdir: pl.Path, instance_num: int) -> dict[str, str]:
    env = {"CARDANO_NODE_SOCKET_PATH": f"{workdir}/state-cluster{instance_num}/bft1.socket"}
    return env


def set_env_vars(env: dict[str, str]) -> None:
    for var_name, val in env.items():
        os.environ[var_name] = val


def get_workdir(workdir: ttypes.FileType) -> pl.Path:
    if workdir != "":
        return pl.Path(workdir).expanduser()

    return pl.Path("/var/tmp/cardonnay")


def get_running_instances(workdir: pl.Path) -> set[int]:
    instances = {
        int(s.parent.name.replace("state-cluster", ""))
        for s in workdir.glob("state-cluster*/supervisord.sock")
    }
    return instances


def get_available_instances(workdir: pl.Path) -> tp.Generator[int, None, None]:
    running_instances = get_running_instances(workdir)
    avail_instances = (i for i in range(MAX_INSTANCES) if i not in running_instances)
    return avail_instances


def has_bins(bins: list[str]) -> bool:
    retval = True
    for b in bins:
        if not shutil.which(b):
            LOGGER.error(f"Required binary '{b}' is not found in PATH.")
            retval = False
    return retval


def check_env_sanity() -> bool:
    bins = ["jq", "supervisord", "supervisorctl", "cardano-node", "cardano-cli"]
    return has_bins(bins=bins)


def has_supervisorctl() -> bool:
    return has_bins(bins=["supervisorctl"])
