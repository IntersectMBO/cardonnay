<!-- markdownlint-disable MD033 MD041 -->
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![PyPi Version](https://img.shields.io/pypi/v/cardonnay.svg)](https://pypi.org/project/cardonnay/)

# Cardonnay

<p align="center">
  <img src="https://github.com/user-attachments/assets/c0c6b4ef-c647-4e77-952f-1ca9f4beaeec" alt="Cardonnay logo" width="200"/>
</p>

**Cardonnay** is a command-line tool for setting up and managing local Cardano testnets.<br />
It supports multiple preconfigured testnet types and makes it easy to inspect and control their lifecycle.

---

## 🚀 Getting Started

### 1. Create a `local_fast` testnet

```sh
$ cardonnay create -t local_fast
Starting the testnet cluster with `/var/tmp/cardonnay-of-user/cluster0_local_fast/start-cluster`:
[...]
Cluster started 🚀
```

> ℹ️ **Pro Tip:** Add `-b` to create the testnet in the background, or `-c "comment"` to add a comment.

### 2. List running testnet instances

`$ cardonnay control ls`

```json
[
  {
    "instance": 0,
    "type": "local_fast",
    "state": "started",
    "comment": null
  }
]
```

### 3. Inspect the testnet faucet

`$ cardonnay inspect faucet -i 0`

```json
{
  "address": "addr_test1vpgm9cj9u3k63642vju9jqgeqy393upttt0qtwptlesy08gx620qd",
  "vkey_file": "/var/tmp/cardonnay-of-user/state-cluster0/shelley/genesis-utxo.vkey",
  "skey_file": "/var/tmp/cardonnay-of-user/state-cluster0/shelley/genesis-utxo.skey"
}
```

### 4. Work with the testnet

```sh
source <(cardonnay control print-env -i 0)
cardano-cli query tip --testnet-magic 42
```

### 5. Stop all running testnet instances

```sh
$ cardonnay control stop-all
Stopping the testnet cluster with `/var/tmp/cardonnay-of-user/state-cluster0/stop-cluster`:
[...]
Cluster terminated!
```

## 🛠️ Installation

### Option 1: Using Nix

If you use [Nix](https://nixos.org/), you can spin up a development shell with all dependencies:

```sh
nix develop
```

This will provide a fully set-up environment, including Python, Cardano binaries, and `jq`.

> ℹ️ **NOTE:** To use the latest `master` branch of `cardano-node`, run

  ```sh
  nix flake update --accept-flake-config --override-input cardano-node github:IntersectMBO/cardano-node/master
  nix develop --accept-flake-config
  ```

---

### Option 2: Using `pip`

Ensure the following dependencies are installed and available in your `PATH`:

- `python3`
- `jq`
- `cardano-node`
- `cardano-cli`
- optional: `cardano-submit-api`

Then install **Cardonnay** in a virtual environment:

```sh
# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install Cardonnay
pip install -U --require-virtualenv cardonnay

# (Optional) Enable shell completions for Bash
source completions/cardonnay.bash-completion
```

---

## ⚙️ db-sync (optional)

db-sync is started automatically when `DBSYNC_SCHEMA_DIR` points to the
[`cardano-db-sync`](https://github.com/IntersectMBO/cardano-db-sync) schema directory
(`cardano-db-sync` must be on your `PATH`). It stays off otherwise.

Set these env vars **before** `cardonnay create`:

| Env var | Effect |
| --- | --- |
| `DBSYNC_SCHEMA_DIR` | Path to the db-sync schema dir; enables db-sync. |
| `SMASH` | Truthy (`1`/`true`/`yes`/`on`) also starts a SMASH server. |
| `DBSYNC_ALLOW_PRIVATE_OFFCHAIN_URLS` | Truthy lets db-sync fetch off-chain anchor data (pool/governance metadata) served from `localhost`. Needed on a local testnet; off by default. |

```sh
export DBSYNC_SCHEMA_DIR=/path/to/cardano-db-sync/schema
export DBSYNC_ALLOW_PRIVATE_OFFCHAIN_URLS=true
cardonnay create -t local_fast
```
