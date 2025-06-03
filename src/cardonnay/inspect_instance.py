import logging
import pathlib as pl
import typing as tp

from cardonnay import helpers

LOGGER = logging.getLogger(__name__)


def load_pools_data(statedir: pl.Path) -> dict:
    """Load data for pools existing in the cluster environment."""
    data_dir = statedir / "nodes"

    pools_data = {}
    for pool_data_dir in data_dir.glob("node-pool*"):
        pools_data[pool_data_dir.name] = {
            "payment": {
                "address": helpers.read_address_from_file(pool_data_dir / "owner.addr"),
                "vkey_file": str(pool_data_dir / "owner-utxo.vkey"),
                "skey_file": str(pool_data_dir / "owner-utxo.skey"),
            },
            "stake": {
                "address": helpers.read_address_from_file(pool_data_dir / "owner-stake.addr"),
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
            "address": helpers.read_address_from_file(byron_dir / "address-000-converted"),
            "vkey_file": str(byron_dir / "payment-keys.000-converted.vkey"),
            "skey_file": str(byron_dir / "payment-keys.000-converted.skey"),
        }
    elif (shelley_dir / "genesis-utxo.addr").exists():
        faucet_addrs_data["faucet"]["payment"] = {
            "address": helpers.read_address_from_file(shelley_dir / "genesis-utxo.addr"),
            "vkey_file": str(shelley_dir / "genesis-utxo.vkey"),
            "skey_file": str(shelley_dir / "genesis-utxo.skey"),
        }

    return faucet_addrs_data


def inspect_instance(statedir: pl.Path, verbose: int) -> dict:
    instance_data = {}
    instance_data.update(load_faucet_data(statedir=statedir))
    if verbose > 0:
        instance_data.update(load_pools_data(statedir=statedir))
    return instance_data
