import pathlib as pl

import pydantic


class KeyPair(pydantic.BaseModel):
    vkey_file: pl.Path
    skey_file: pl.Path


class ColdKeyPair(KeyPair):
    counter_file: pl.Path


class AddressData(pydantic.BaseModel):
    address: str
    vkey_file: pl.Path
    skey_file: pl.Path


class PoolData(pydantic.BaseModel):
    pool_name: str
    payment: AddressData
    stake: AddressData
    stake_addr_registration_cert: pl.Path
    stake_addr_delegation_cert: pl.Path
    reward_addr_registration_cert: pl.Path
    pool_registration_cert: pl.Path
    pool_operational_cert: pl.Path
    cold_key_pair: ColdKeyPair
    vrf_key_pair: KeyPair
    kes_key_pair: KeyPair


class SupervisorData(pydantic.BaseModel):
    HAS_DBSYNC: bool
    HAS_SMASH: bool
    HAS_SUBMIT_API: bool
    NUM_POOLS: int


class InstanceInfo(pydantic.BaseModel):
    instance: int
    type: str
    state: str
    dir: pl.Path
    comment: str | None
    submit_api_port: int | None
    start_pid: int | None
    start_logfile: pl.Path | None
    control_env: dict[str, str]
    supervisor_env: SupervisorData


class InstanceSummary(pydantic.BaseModel):
    instance: int
    type: str
    state: str
    comment: str | None = None


class CombinedConfig(pydantic.BaseModel):
    # Shelley genesis.json
    epochLength: int | None = None  # noqa: N815
    maxLovelaceSupply: int | None = None  # noqa: N815
    networkMagic: int | None = None  # noqa: N815
    securityParam: int | None = None  # noqa: N815
    slotLength: float | None = None  # noqa: N815

    # Conway genesis.conway.json
    committee_members: int | None = None
    committee_threshold: float | None = None
    dRepDeposit: int | None = None  # noqa: N815
    govActionDeposit: int | None = None  # noqa: N815
    govActionLifetime: int | None = None  # noqa: N815

    # Pool1 config-pool1.json
    EnableP2P: bool | None = None
    ledgerdb_backend: str = "default"

    # Derived
    epoch_len_sec: float = 0.0
