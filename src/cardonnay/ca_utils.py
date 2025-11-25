import logging
import os
import pathlib as pl
import shutil
import time
import typing as tp

import filelock

from cardonnay import ttypes

LOGGER = logging.getLogger(__name__)

MAX_INSTANCES = 10
TESTNET_JSON = "testnet.json"
STATUS_STARTED = "status_started"
DELAY_STATUS = "delay_stat"
DELAY_LOCK = "delay.lock"
STATE_CLUSTER_PREFIX = "state-cluster"
STATE_CLUSTER_PREFIX_LEN = len("state-cluster")


def create_env_vars(workdir: pl.Path, instance_num: int) -> dict[str, str]:
    env = {
        "CARDANO_NODE_SOCKET_PATH": f"{workdir}/{STATE_CLUSTER_PREFIX}{instance_num}/bft1.socket"
    }
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
        int(s.parent.name[STATE_CLUSTER_PREFIX_LEN:])
        for s in workdir.glob(f"{STATE_CLUSTER_PREFIX}*/supervisord.sock")
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


def get_delay_instances(workdir: pl.Path) -> set[int]:
    """Get the set of instances that are currently delayed based on file modification time.

    An instance can be in a state where it is starting, but the supervisord.sock was not
    created yet, so it is not considered as properly "starting" yet.
    Or an instance can be in a state where it is stopping, but the supervisord.sock is still
    present, so it is not considered as properly stopped yet.
    """
    valid_time_sec = 10
    starting = set()
    sf_len = len(DELAY_STATUS)
    now = time.time()

    for sf in workdir.glob(f"{DELAY_STATUS}*"):
        try:
            mtime = sf.stat().st_mtime
        except FileNotFoundError:
            continue

        if now - mtime < valid_time_sec:
            try:
                instance_num = int(sf.name[sf_len:])
                starting.add(instance_num)
            except ValueError:
                LOGGER.warning(f"Invalid status file name: {sf}")
        else:
            sf.unlink()

    return starting


def create_delay_file(instance_num: int, workdir: pl.Path) -> None:
    """Create a delay status file for the specified testnet instance."""
    status_file = workdir / f"{DELAY_STATUS}{instance_num}"
    status_file.touch()


def delay_instance(instance_num: int, workdir: pl.Path) -> bool:
    """Delay the specified testnet instance to prevent concurrent access."""
    lockfile = str(workdir / DELAY_LOCK)
    with filelock.FileLock(lock_file=lockfile, timeout=2):
        delay_instances = get_delay_instances(workdir=workdir)
        if instance_num in delay_instances:
            LOGGER.error(f"Instance number {instance_num} is already delayed.")
            return False
        create_delay_file(instance_num=instance_num, workdir=workdir)

    return True


def undelay_instance(instance_num: int, workdir: pl.Path) -> bool:
    """Remove the delay for the specified testnet instance."""
    lockfile = str(workdir / DELAY_LOCK)
    with filelock.FileLock(lock_file=lockfile, timeout=2):
        status_file = workdir / f"{DELAY_STATUS}{instance_num}"
        status_file.unlink(missing_ok=True)

    return True
