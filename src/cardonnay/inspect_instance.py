import contextlib
import json
import logging
import pathlib as pl
import typing as tp

from cardonnay import cli_utils
from cardonnay import consts
from cardonnay import helpers

LOGGER = logging.getLogger(__name__)


def get_process_environ(pid: int) -> dict:
    """Read environment variables of a process from /proc/<pid>/environ."""
    environ_path = f"/proc/{pid}/environ"
    try:
        with open(environ_path, "rb") as fp_in:
            content = fp_in.read()
            env_vars = content.split(b"\0")
            env_dict = {}
            for item in env_vars:
                if b"=" in item:
                    key, value = item.split(b"=", 1)
                    env_dict[key.decode()] = value.decode()
            return env_dict
    except FileNotFoundError:
        LOGGER.error(f"Process {pid} does not exist.")  # noqa: TRY400
    except PermissionError:
        LOGGER.error(f"Permission denied for accessing environment of process {pid}.")  # noqa: TRY400
    return {}


def get_control_var_names(statedir: pl.Path) -> list[str]:
    """Get names of control environment variables from the testnet info file."""
    try:
        with open(statedir / cli_utils.TESTNET_JSON, encoding="utf-8") as fp_in:
            testnet_info = json.load(fp_in) or {}
    except Exception:
        testnet_info = {}

    control_env = list(testnet_info.get("control_env", {}).keys())
    return control_env


def load_pools_data(statedir: pl.Path) -> dict:
    """Load data for pools existing in the cluster environment."""
    data_dir = statedir / "nodes"

    pools_data = {}
    for pool_data_dir in data_dir.glob("node-pool*"):
        pools_data[pool_data_dir.name] = {
            "payment": {
                "address": helpers.read_from_file(pool_data_dir / "owner.addr"),
                "vkey_file": str(pool_data_dir / "owner-utxo.vkey"),
                "skey_file": str(pool_data_dir / "owner-utxo.skey"),
            },
            "stake": {
                "address": helpers.read_from_file(pool_data_dir / "owner-stake.addr"),
                "vkey_file": str(pool_data_dir / "owner-stake.vkey"),
                "skey_file": str(pool_data_dir / "owner-stake.skey"),
            },
            "stake_addr_registration_cert": str(pool_data_dir / "stake.reg.cert"),
            "stake_addr_delegation_cert": str(pool_data_dir / "owner-stake.deleg.cert"),
            "reward_addr_registration_cert": str(pool_data_dir / "stake-reward.reg.cert"),
            "pool_registration_cert": str(pool_data_dir / "register.cert"),
            "pool_operational_cert": str(pool_data_dir / "op.cert"),
            "cold_key_pair": {
                "vkey_file": str(pool_data_dir / "cold.vkey"),
                "skey_file": str(pool_data_dir / "cold.skey"),
                "counter_file": str(pool_data_dir / "cold.counter"),
            },
            "vrf_key_pair": {
                "vkey_file": str(pool_data_dir / "vrf.vkey"),
                "skey_file": str(pool_data_dir / "vrf.skey"),
            },
            "kes_key_pair": {
                "vkey_file": str(pool_data_dir / "kes.vkey"),
                "skey_file": str(pool_data_dir / "kes.skey"),
            },
        }

    return pools_data


def load_faucet_data(statedir: pl.Path) -> dict:
    """Load data for faucet address."""
    byron_dir = statedir / "byron"
    shelley_dir = statedir / "shelley"

    faucet_addrs_data: dict[str, dict[str, tp.Any]] = {"faucet": {"payment": None}}
    if (byron_dir / "address-000-converted").exists():
        faucet_addrs_data["faucet"]["payment"] = {
            "address": helpers.read_from_file(byron_dir / "address-000-converted"),
            "vkey_file": str(byron_dir / "payment-keys.000-converted.vkey"),
            "skey_file": str(byron_dir / "payment-keys.000-converted.skey"),
        }
    elif (shelley_dir / "genesis-utxo.addr").exists():
        faucet_addrs_data["faucet"]["payment"] = {
            "address": helpers.read_from_file(shelley_dir / "genesis-utxo.addr"),
            "vkey_file": str(shelley_dir / "genesis-utxo.vkey"),
            "skey_file": str(shelley_dir / "genesis-utxo.skey"),
        }

    return faucet_addrs_data


def get_testnet_info(statedir: pl.Path) -> dict:
    """Get information about the testnet instance."""
    if (statedir / "supervisord.sock").exists():
        testnet_state = (
            consts.States.STARTED
            if (statedir / cli_utils.STATUS_STARTED).exists()
            else consts.States.STARTING
        )
    else:
        testnet_state = consts.States.STOPPED

    try:
        with open(statedir / cli_utils.TESTNET_JSON, encoding="utf-8") as fp_in:
            testnet_info = json.load(fp_in) or {}
    except Exception:
        testnet_info = {}

    testnet_name = testnet_info.get("name") or "unknown"
    instance_num = int(statedir.name.replace("state-cluster", ""))

    instance_info = {
        "instance": instance_num,
        "type": testnet_name,
        "state": testnet_state,
        "dir": str(statedir),
    }
    testnet_comment = testnet_info.get("comment")
    if testnet_comment:
        instance_info["comment"] = testnet_comment

    workdir = statedir.parent

    pidfile = workdir / f"start_cluster{instance_num}.pid"
    if pidfile.exists() and testnet_state == consts.States.STARTING:
        pid = 0
        with contextlib.suppress(Exception):
            pid = int(helpers.read_from_file(pidfile))
        if pid:
            instance_info["start_pid"] = pid

    logfile = workdir / f"start_cluster{instance_num}.log"
    if logfile.exists():
        instance_info["start_logfile"] = str(logfile)

    return instance_info


def get_control_env(statedir: pl.Path) -> dict:
    """Get control environment variables and supervisor data from the statedir."""
    environ_data = {}
    supervisor_data = {}

    pid = -1
    with contextlib.suppress(Exception):
        pid = int(helpers.read_from_file(statedir / "supervisord.pid"))

    if pid != -1:
        environ = get_process_environ(pid=pid)
        control_var_names = [*get_control_var_names(statedir=statedir), "CARDANO_NODE_SOCKET_PATH"]
        environ_data = {k: v for k in control_var_names if (v := environ.get(k))}

    supervisor_conf = set()
    with (
        contextlib.suppress(Exception),
        open(statedir / "supervisor.conf", encoding="utf-8") as fp_in,
    ):
        supervisor_conf = set(fp_in.readlines())

    if supervisor_conf:
        supervisor_data = {
            "HAS_DBSYNC": "[program:dbsync]" in supervisor_conf,
            "HAS_SMASH": "[program:smash]" in supervisor_conf,
            "HAS_SUBMIT_API": "[program:submit_api]" in supervisor_conf,
            "NUM_POOLS": len([line for line in supervisor_conf if "[program:pool" in line]),
        }

    control_env = {"control_env": {**environ_data, **supervisor_data}}

    return control_env


def get_config(statedir: pl.Path) -> dict:
    """Get configuration data from the statedir."""
    genesis_shelley_data: dict = {}
    genesis_conway_data: dict = {}
    pool1_data: dict = {}

    genesis_shelley_json = {}
    with (
        contextlib.suppress(Exception),
        open(statedir / "shelley" / "genesis.json", encoding="utf-8") as fp_in,
    ):
        genesis_shelley_json = json.load(fp_in)

    if genesis_shelley_json:
        genesis_shelley_data = {
            "shelley": {
                "epochLength": genesis_shelley_json.get("epochLength"),
                "maxLovelaceSupply": genesis_shelley_json.get("maxLovelaceSupply"),
                "networkMagic": genesis_shelley_json.get("networkMagic"),
                "securityParam": genesis_shelley_json.get("securityParam"),
                "slotLength": genesis_shelley_json.get("slotLength"),
            }
        }

    genesis_conway_json = {}
    with (
        contextlib.suppress(Exception),
        open(statedir / "shelley" / "genesis.conway.json", encoding="utf-8") as fp_in,
    ):
        genesis_conway_json = json.load(fp_in)

    if genesis_conway_json:
        genesis_conway_data = {
            "conway": {
                "committee": {
                    "members": len(genesis_conway_json.get("committee", {}).get("members")),
                    "threshold": genesis_conway_json.get("committee", {}).get("threshold"),
                },
                "dRepDeposit": genesis_conway_json.get("dRepDeposit"),
                "govActionDeposit": genesis_conway_json.get("govActionDeposit"),
                "govActionLifetime": genesis_conway_json.get("govActionLifetime"),
            }
        }

    pool1_json = {}
    with (
        contextlib.suppress(Exception),
        open(statedir / "config-pool1.json", encoding="utf-8") as fp_in,
    ):
        pool1_json = json.load(fp_in)

    if pool1_json:
        ledgerdb_backend = (
            "default"
            if "LedgerDB" not in pool1_json
            else pool1_json.get("LedgerDB", {}).get("Backend")
        )
        pool1_data = {
            "config": {
                "EnableP2P": pool1_json.get("EnableP2P"),
                "LedgerDB_Backend": ledgerdb_backend,
            }
        }

    config_data = {**genesis_shelley_data, **genesis_conway_data, **pool1_data}
    if genesis_shelley_json:
        config_data["epoch_len_sec"] = int(genesis_shelley_json.get("epochLength") or 0) * float(
            genesis_shelley_json.get("slotLength") or 0.0
        )
    return config_data
