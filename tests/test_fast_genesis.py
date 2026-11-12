"""Offline integration tests for fast-testnet genesis generation.

Run with `python -m unittest discover -s tests`. These tests require the Cardano
binaries and jq, but do not start nodes, bind ports or submit transactions.
"""

# Use unittest assertions for diagnostics without adding a pytest dependency.
# ruff: noqa: PT009

import json
import os
import pathlib as pl
import shutil
import subprocess
import tempfile
import unittest

import cardonnay_scripts
from cardonnay import local_scripts

REQUIRED_BINS = ("bash", "jq", "cardano-cli", "cardano-node")
DIJKSTRA_PV = 12
GENERATION_SCRIPT = r"""
source <(sed '/^main "\$@"$/d' "$0")
initialize_globals
setup_state_cluster "$TESTNET_DATA_DIR"
create_genesis
create_committee_keys_in_genesis
create_genesis_utxos
get_genesis_data
create_bft_nodes_files
create_pools_files
inject_pools_into_genesis
get_genesis_hashes
edit_node_configs
create_dreps_files
"""


@unittest.skipUnless(
    all(shutil.which(b) for b in REQUIRED_BINS), "Cardano binaries and jq required"
)
class FastGenesisTest(unittest.TestCase):
    def test_genesis_generation(self) -> None:
        cases = (
            ("local_fast", 3, 11, False, False),
            ("local_fast", 4, 9, True, False),
            ("local_fast", 10, DIJKSTRA_PV, False, True),
            ("mainnet_fast", 3, 11, False, False),
            ("leios_fast", 3, DIJKSTRA_PV, False, False),
        )
        for variant, pools, protocol, no_cc, hard_fork in cases:
            with self.subTest(variant=variant, pools=pools, protocol=protocol, no_cc=no_cc):
                self._check_genesis(variant, pools, protocol, no_cc, hard_fork)

    def _check_genesis(
        self, variant: str, pools: int, protocol: int, no_cc: bool, hard_fork: bool
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="cardonnay-genesis-") as tmp:
            workdir = pl.Path(tmp)
            scriptsdir = pl.Path(str(cardonnay_scripts.SCRIPTS_ROOT)) / variant
            rendered = workdir / "scripts"
            rendered.mkdir()
            local_scripts.prepare_scripts_files(
                destdir=rendered,
                scriptsdir=scriptsdir,
                instance_num=0,
                num_pools=pools,
                ports_base=31000,
            )
            state = workdir / "state-cluster0"
            env = os.environ.copy()
            env.update(
                CARDANO_NODE_SOCKET_PATH=str(state / "bft1.socket"),
                PROTOCOL_VERSION=str(protocol),
                NO_CC=str(no_cc),
                HF_TO_DIJKSTRA=str(hard_fork),
                NO_POOLS_IN_GENESIS="false",
                ENABLE_TX_GENERATOR="false",
                ENABLE_TX_CENTRIFUGE="false",
                ENABLE_TX_FIREHOSE="false",
                ENABLE_EXPERIMENTAL="false",
                UTXO_BACKEND="",
                MIXED_UTXO_BACKENDS="",
                START_CLUSTER_LOG=str(workdir / "commands.log"),
            )
            result = subprocess.run(
                ["bash", "-c", GENERATION_SCRIPT, str(rendered / "common-start-fast")],
                cwd=workdir,
                env=env,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self._check_outputs(state, scriptsdir, pools, 11 if hard_fork else protocol, no_cc)

            commands = (workdir / "commands.log").read_text(encoding="utf-8")
            self.assertIn("latest genesis create-testnet-data", commands)
            self.assertNotIn("genesis create-staked", commands)
            self.assertNotIn("byron genesis genesis", commands)

    def _check_outputs(
        self, state: pl.Path, scriptsdir: pl.Path, pools: int, protocol: int, no_cc: bool
    ) -> None:
        shelley_dir = state / "shelley"
        template = self._read_json(scriptsdir / "genesis.spec.json")
        shelley = self._read_json(shelley_dir / "genesis.json")
        self.assertEqual(shelley["maxLovelaceSupply"], template["maxLovelaceSupply"])
        self.assertEqual(shelley["networkMagic"], template["networkMagic"])
        self.assertEqual(shelley["securityParam"], template["securityParam"])
        self.assertEqual(shelley["protocolParams"]["protocolVersion"]["major"], protocol)

        extra = shelley.get("extraConfig", {})
        funds = extra.get("initialFunds", {}).get("data", shelley["initialFunds"])
        pool_params = extra.get("stakePools", {}).get("data", shelley["staking"]["pools"])
        stake = extra.get("stakeCredentials", {}).get("data", shelley["staking"]["stake"])
        self.assertEqual(len(funds), pools + 2)
        self.assertEqual(len(pool_params), pools)
        self.assertEqual(len(stake), pools)
        pledge = 1_000_000_000_000
        self.assertEqual(sorted(funds.values())[:pools], [pledge * 3] * pools)
        delegated_supply = pledge * pools * 3 * 10 // 9
        nondelegated_supply = shelley["maxLovelaceSupply"] - delegated_supply
        expected_funds = (
            delegated_supply
            - delegated_supply // 10
            + nondelegated_supply
            - nondelegated_supply // 10
        )
        self.assertEqual(sum(funds.values()), expected_funds)
        for params in pool_params.values():
            self.assertEqual(params["pledge"], pledge)
            self.assertEqual(params["cost"], template["protocolParams"]["minPoolCost"] or 600)
            self.assertEqual(params["margin"], 0.35)
            self.assertEqual(len(params["owners"]), 1)
            self.assertEqual(len(params["relays"]), 1)
            self.assertTrue(params["metadata"])
            if protocol >= DIJKSTRA_PV and (state / "nodes/node-pool1/bls.skey").is_file():
                self.assertIsNotNone(params["blsKey"])

        alonzo = self._read_json(shelley_dir / "genesis.alonzo.json")
        alonzo_spec = self._read_json(shelley_dir / "genesis.alonzo.spec.json")
        conway = self._read_json(shelley_dir / "genesis.conway.json")
        self.assertEqual(len(alonzo["costModels"]["PlutusV1"]), 166)
        # The Alonzo decoder emits only V1; verify V2 trimming in its input.
        self.assertEqual(len(alonzo_spec["costModels"]["PlutusV2"]), 175)
        self.assertEqual(len(conway["plutusV3CostModel"]), 251)
        self.assertEqual(len(conway["committee"]["members"]), 0 if no_cc else 5)
        if not no_cc:
            self.assertEqual(conway["committee"]["threshold"], 0.6)
            self.assertEqual(conway["committeeMinSize"], 2)
            self.assertEqual(set(conway["committee"]["members"].values()), {10000})
        self.assertFalse(conway.get("extraConfig", {}).get("initialDReps", {}).get("data"))
        for i in range(1, 6):
            self.assertTrue((state / f"governance_data/default_drep_{i}_drep_reg.cert").is_file())
            self.assertTrue((state / f"governance_data/vote_stake_addr{i}.addr").is_file())

        self._check_key_paths(state, pools)
        byron = self._read_json(state / "byron/genesis.json")
        self.assertEqual(byron["startTime"], int((state / "cluster_start_time").read_text()))
        self.assertEqual(byron["protocolConsts"]["k"], shelley["securityParam"])
        self.assertEqual(byron["protocolConsts"]["protocolMagic"], shelley["networkMagic"])
        self.assertEqual(
            self._read_json(shelley_dir / "genesis.dijkstra.json"),
            self._read_json(scriptsdir / "genesis.dijkstra.spec.json"),
        )
        config = self._read_json(state / "config-pool1.json")
        eras = ("Shelley", "Alonzo", "Conway", "Dijkstra")
        for era in eras:
            if f"{era}GenesisFile" not in config:
                continue
            result = subprocess.run(
                [
                    "cardano-cli",
                    "latest",
                    "genesis",
                    "hash",
                    "--genesis",
                    str(state / config[f"{era}GenesisFile"]),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(config[f"{era}GenesisHash"], result.stdout.strip())

    def _check_key_paths(self, state: pl.Path, pools: int) -> None:
        shelley_dir = state / "shelley"
        for name in ("genesis-utxo", "genesis-utxo2"):
            for suffix in ("skey", "vkey", "addr"):
                self.assertTrue((shelley_dir / f"{name}.{suffix}").is_file())
        self.assertTrue((shelley_dir / "stake-delegator-keys").is_dir())
        for i in range(1, 4):
            for suffix in ("skey", "vkey"):
                self.assertTrue((shelley_dir / f"genesis-keys/genesis{i}.{suffix}").is_file())
                for stem in (f"delegate{i}", f"delegate{i}.vrf", f"delegate{i}.kes"):
                    self.assertTrue((shelley_dir / f"delegate-keys/{stem}.{suffix}").is_file())
            self.assertTrue((shelley_dir / f"delegate-keys/opcert{i}.cert").is_file())
            self.assertTrue((shelley_dir / f"delegate-keys/delegate{i}.counter").is_file())
        for i in range(1, pools + 1):
            names = ("cold.skey", "kes.skey", "vrf.skey", "op.cert", "cold.counter", "reward.skey")
            for name in names:
                self.assertTrue((state / f"nodes/node-pool{i}" / name).is_file())
            self.assertTrue((state / f"byron/delegate-keys.{i - 1:03d}.key").is_file())
            self.assertTrue((state / f"byron/delegation-cert.{i - 1:03d}.json").is_file())

    @staticmethod
    def _read_json(path: pl.Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
