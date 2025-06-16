import contextlib
import json
import logging
import pathlib as pl
import re

from cardonnay import ca_utils
from cardonnay import consts
from cardonnay import helpers
from cardonnay import structs

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
        with open(statedir / ca_utils.TESTNET_JSON, encoding="utf-8") as fp_in:
            testnet_info = json.load(fp_in) or {}
    except Exception:
        testnet_info = {}

    control_env = list(testnet_info.get("control_env", {}).keys())
    return control_env


def load_pools_data(statedir: pl.Path) -> list[structs.PoolData]:
    """Load data for pools existing in the cluster environment."""
    data_dir = statedir / "nodes"

    pools = [
        structs.PoolData(
            pool_name=pool_data_dir.name,
            payment=structs.AddressData(
                address=helpers.read_from_file(pool_data_dir / "owner.addr"),
                vkey_file=pool_data_dir / "owner-utxo.vkey",
                skey_file=pool_data_dir / "owner-utxo.skey",
            ),
            stake=structs.AddressData(
                address=helpers.read_from_file(pool_data_dir / "owner-stake.addr"),
                vkey_file=pool_data_dir / "owner-stake.vkey",
                skey_file=pool_data_dir / "owner-stake.skey",
            ),
            stake_addr_registration_cert=pool_data_dir / "stake.reg.cert",
            stake_addr_delegation_cert=pool_data_dir / "owner-stake.deleg.cert",
            reward_addr_registration_cert=pool_data_dir / "stake-reward.reg.cert",
            pool_registration_cert=pool_data_dir / "register.cert",
            pool_operational_cert=pool_data_dir / "op.cert",
            cold_key_pair=structs.ColdKeyPair(
                vkey_file=pool_data_dir / "cold.vkey",
                skey_file=pool_data_dir / "cold.skey",
                counter_file=pool_data_dir / "cold.counter",
            ),
            vrf_key_pair=structs.KeyPair(
                vkey_file=pool_data_dir / "vrf.vkey",
                skey_file=pool_data_dir / "vrf.skey",
            ),
            kes_key_pair=structs.KeyPair(
                vkey_file=pool_data_dir / "kes.vkey",
                skey_file=pool_data_dir / "kes.skey",
            ),
        )
        for pool_data_dir in data_dir.glob("node-pool*")
    ]

    return pools


def load_faucet_data(statedir: pl.Path) -> structs.AddressData:
    """Load data for faucet address."""
    byron_dir = statedir / "byron"
    shelley_dir = statedir / "shelley"

    if (byron_dir / "address-000-converted").exists():
        faucet_addrs_data = structs.AddressData(
            address=helpers.read_from_file(byron_dir / "address-000-converted"),
            vkey_file=byron_dir / "payment-keys.000-converted.vkey",
            skey_file=byron_dir / "payment-keys.000-converted.skey",
        )
    elif (shelley_dir / "genesis-utxo.addr").exists():
        faucet_addrs_data = structs.AddressData(
            address=helpers.read_from_file(shelley_dir / "genesis-utxo.addr"),
            vkey_file=shelley_dir / "genesis-utxo.vkey",
            skey_file=shelley_dir / "genesis-utxo.skey",
        )

    return faucet_addrs_data


def get_control_env(statedir: pl.Path) -> dict:
    """Get control environment variables."""
    environ_data = {}

    pid = -1
    with contextlib.suppress(Exception):
        pid = int(helpers.read_from_file(statedir / "supervisord.pid"))

    if pid != -1:
        environ = get_process_environ(pid=pid)
        control_var_names = [*get_control_var_names(statedir=statedir), "CARDANO_NODE_SOCKET_PATH"]
        environ_data = {k: v for k in control_var_names if (v := environ.get(k))}

    return environ_data


def get_submit_api_port(statedir: pl.Path) -> int:
    """Get the port number for the Submit API from the `run-cardano-submit-api` file."""
    content = ""
    with contextlib.suppress(Exception):
        content = helpers.read_from_file(statedir / "run-cardano-submit-api")

    if port_match := re.search(r"--port\s+(\d+)", content):
        return int(port_match.group(1))
    return -1


def get_supervisor_env(statedir: pl.Path) -> structs.SupervisorData:
    """Get supervisor environment data from the statedir."""
    supervisor_conf = set()

    with (
        contextlib.suppress(Exception),
        open(statedir / "supervisor.conf", encoding="utf-8") as fp_in,
    ):
        supervisor_conf = {line.rstrip("\r\n") for line in fp_in}

    supervisor_data = structs.SupervisorData(
        HAS_DBSYNC="[program:dbsync]" in supervisor_conf,
        HAS_SMASH="[program:smash]" in supervisor_conf,
        HAS_SUBMIT_API="[program:submit_api]" in supervisor_conf,
        NUM_POOLS=len([line for line in supervisor_conf if "[program:pool" in line]),
    )

    return supervisor_data


def get_testnet_info(statedir: pl.Path) -> structs.InstanceInfo:
    """Get information about the testnet instance."""
    if (statedir / "supervisord.sock").exists():
        testnet_state = (
            consts.States.STARTED
            if (statedir / ca_utils.STATUS_STARTED).exists()
            else consts.States.STARTING
        )
    else:
        testnet_state = consts.States.STOPPED

    try:
        with open(statedir / ca_utils.TESTNET_JSON, encoding="utf-8") as fp_in:
            testnet_info = json.load(fp_in) or {}
    except Exception:
        testnet_info = {}

    testnet_name = testnet_info.get("name") or "unknown"
    instance_num = int(statedir.name.replace("state-cluster", ""))

    workdir = statedir.parent

    start_pid = -1
    pidfile = workdir / f"start_cluster{instance_num}.pid"
    if pidfile.exists() and testnet_state == consts.States.STARTING:
        pid = 0
        with contextlib.suppress(Exception):
            pid = int(helpers.read_from_file(pidfile))
        if pid:
            start_pid = pid

    start_logfile = None
    logfile = workdir / f"start_cluster{instance_num}.log"
    if logfile.exists():
        start_logfile = logfile

    instance_info = structs.InstanceInfo(
        instance=instance_num,
        type=testnet_name,
        state=testnet_state,
        dir=statedir,
        comment=testnet_info.get("comment"),
        submit_api_port=sp if (sp := get_submit_api_port(statedir=statedir)) > 0 else None,
        start_pid=start_pid if start_pid > 0 else None,
        start_logfile=start_logfile,
        control_env=get_control_env(statedir=statedir),
        supervisor_env=get_supervisor_env(statedir=statedir),
    )

    return instance_info


def get_config(statedir: pl.Path) -> structs.CombinedConfig:
    """Get configuration data from the statedir."""
    config = structs.CombinedConfig()

    # shelley/genesis.json
    with (
        contextlib.suppress(Exception),
        open(statedir / "shelley" / "genesis.json", encoding="utf-8") as fp_in,
    ):
        data = json.load(fp_in)
        config.epochLength = data.get("epochLength")
        config.maxLovelaceSupply = data.get("maxLovelaceSupply")
        config.networkMagic = data.get("networkMagic")
        config.securityParam = data.get("securityParam")
        config.slotLength = data.get("slotLength")

    # shelley/genesis.conway.json
    with (
        contextlib.suppress(Exception),
        open(statedir / "shelley" / "genesis.conway.json", encoding="utf-8") as fp_in,
    ):
        data = json.load(fp_in)
        committee = data.get("committee", {})
        config.committee_members = len(committee.get("members", []))
        config.committee_threshold = committee.get("threshold")
        config.dRepDeposit = data.get("dRepDeposit")
        config.govActionDeposit = data.get("govActionDeposit")
        config.govActionLifetime = data.get("govActionLifetime")

    # config-pool1.json
    with (
        contextlib.suppress(Exception),
        open(statedir / "config-pool1.json", encoding="utf-8") as fp_in,
    ):
        data = json.load(fp_in)
        config.EnableP2P = data.get("EnableP2P")
        config.ledgerdb_backend = (
            data.get("LedgerDB", {}).get("Backend", "default") if "LedgerDB" in data else "default"
        )

    # Derived field
    if config.epochLength is not None and config.slotLength is not None:
        config.epoch_len_sec = config.epochLength * config.slotLength

    return config
