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

### 1. Create a `conway_fast` testnet

```sh
$ cardonnay create -t conway_fast
Starting the testnet cluster with `/var/tmp/cardonnay/cluster0_conway_fast/start-cluster`:
[...]
Cluster started 🚀
```

### 2. List running testnet instances

`$ cardonnay control ls`

```json
[
  {
    "instance": 0,
    "type": "conway_fast",
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
  "vkey_file": "/var/tmp/cardonnay/state-cluster0/shelley/genesis-utxo.vkey",
  "skey_file": "/var/tmp/cardonnay/state-cluster0/shelley/genesis-utxo.skey"
}
```

### 4. Stop all running testnet instances

```sh
$ cardonnay control stop-all
Stopping the testnet cluster with `/var/tmp/cardonnay/state-cluster0/stop-cluster`:
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
  nix develop --override-input cardano-node "github:input-output-hk/cardano-node/master" --recreate-lock-file
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
