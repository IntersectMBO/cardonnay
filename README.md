# Cardonnay

[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

<p align="center">  <!-- markdownlint-disable-line MD033 -->
  <img src="https://github.com/user-attachments/assets/c0c6b4ef-c647-4e77-952f-1ca9f4beaeec" alt="Cardonnay logo" width="200"/>  <!-- markdownlint-disable-line MD033 -->
</p>

## Creating a testnet

1. List available testnet variants:

    ```sh
    $ cardonnay create -l
    [
      "conway_fast",
      "conway_slow",
      "mainnet_fast"
    ]
    ```

1. Create a "conway_fast" testnet:

    ```sh
    $ cardonnay create -t conway_fast
    Starting the testnet cluster with `/var/tmp/cardonnay/cluster0_conway_fast/start-cluster`:
    generated genesis with: 3 genesis keys, 1 non-delegating UTxO keys, 3 stake pools, 3 delegating UTxO keys, 3 delegation map entries,
    Generating Pool 1 Secrets
    Generating Pool 1 Metadata
    Generating Pool 2 Secrets
    Generating Pool 2 Metadata
    Generating Pool 3 Secrets
    Generating Pool 3 Metadata
    Waiting 5 seconds for the nodes to start
    Sleeping for initial Tx submission delay of 60 seconds
    Re-registering pools, creating CC members and DReps
    Estimated transaction fee: 707009 Lovelace
    Transaction successfully submitted. Transaction hash is:
    {"txhash":"0da263167de3998adc0590072fbf3a82fecf47618933cf9a4833c69005c7c18c"}
    Starting cardano-submit-api
    submit_api: started
    Cluster started 🚀
    ```

1. List running testnet instances:

    ```sh
    $ cardonnay control ls
    [
      {
        "instance": 0,
        "type": "conway_fast",
        "state": "started"
      }
    ]
    ```

1. Display data about the testnet faucet:

    ```sh
    $ cardonnay inspect faucet -i 0
    {
      "faucet": {
        "payment": {
          "address": "addr_test1vzg7nhcqqvf3fer9qayexlwqhhkh6fux9nc3exvrdu6lrgsxl3v77",
          "vkey_file": "/var/tmp/cardonnay/state-cluster0/shelley/genesis-utxo.vkey",
          "skey_file": "/var/tmp/cardonnay/state-cluster0/shelley/genesis-utxo.skey"
        }
      }
    }
    ```

1. Stop all running testnet instances:

    ```sh
    $ cardonnay control stop-all
    Stopping the testnet cluster with `/var/tmp/cardonnay/state-cluster0/stop-cluster`:
    nodes:bft1: stopped
    nodes:pool1: stopped
    nodes:pool2: stopped
    nodes:pool3: stopped
    submit_api: stopped
    webserver: stopped
    Cluster terminated!
    ```
