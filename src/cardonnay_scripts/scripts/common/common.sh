#!/usr/bin/env bash

is_truthy() {
  local val="${1:-}"
  val=${val,,}

  case "$val" in
    1 | true | yes | on | enabled )
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

get_epoch_sec() {
  if [ -z "${EPOCH_SEC:-}" ]; then
    EPOCH_SEC="$(jq '.epochLength * .slotLength | ceil' < "${STATE_CLUSTER}/shelley/genesis.json")"
  fi
  echo "$EPOCH_SEC"
}

get_slot_length() {
  if [ -z "${SLOT_LENGTH:-}" ]; then
    SLOT_LENGTH="$(jq '.slotLength' < "${STATE_CLUSTER}/shelley/genesis.json")"
  fi
  echo "$SLOT_LENGTH"
}

cardano_cli_log() {
  if [ -z "${START_CLUSTER_LOG:-}" ]; then
    START_CLUSTER_LOG="${STATE_CLUSTER}/start-cluster.log"
  fi

  echo cardano-cli "$@" >> "$START_CLUSTER_LOG"
  cardano-cli "$@"
  return "$?"
}

check_spend_success() {
  local _
  for _ in {1..10}; do
    if ! cardano_cli_log latest query utxo "$@" \
      --testnet-magic "$NETWORK_MAGIC" --output-text | grep -q lovelace; then
      return 0
    fi
    sleep 3
  done
  return 1
}

get_txins() {
  local txin_addr stop_txin_amount txhash txix amount _

  txin_addr="${1:?"Missing TxIn address"}"
  stop_txin_amount="${2:?"Missing stop TxIn amount"}"

  stop_txin_amount="$((stop_txin_amount + 2000000))"

  # Repeat in case `query utxo` fails
  for _ in {1..3}; do
    TXINS=()
    TXIN_AMOUNT=0
    while read -r txhash txix amount _; do
      if [ -z "$txhash" ] || [ -z "$txix" ] || [ "$amount" -lt 1000000 ]; then
        continue
      fi
      TXIN_AMOUNT="$((TXIN_AMOUNT + amount))"
      TXINS+=("--tx-in" "${txhash}#${txix}")
      if [ "$TXIN_AMOUNT" -ge "$stop_txin_amount" ]; then
        break
      fi
    done <<< "$(cardano_cli_log latest query utxo \
                --testnet-magic "$NETWORK_MAGIC" \
                --output-text \
                --address "$txin_addr" |
                grep -E "lovelace$|[0-9]$|lovelace \+ TxOutDatumNone$")"

    if [ "$TXIN_AMOUNT" -ge "$stop_txin_amount" ]; then
      break
    fi
  done
}

get_address_balance() {
  local txhash txix amount total_amount _

  # Repeat in case `query utxo` fails
  for _ in {1..3}; do
    total_amount=0
    while read -r txhash txix amount _; do
      if [ -z "$txhash" ] || [ -z "$txix" ]; then
        continue
      fi
      total_amount="$((total_amount + amount))"
    done <<< "$(cardano-cli latest query utxo "$@" --output-text | grep " lovelace")"

    if [ "$total_amount" -gt 0 ]; then
      break
    fi
  done

  echo "$total_amount"
}

get_epoch() {
  cardano_cli_log latest query tip --testnet-magic "$NETWORK_MAGIC" | jq -r '.epoch'
}

get_slot() {
  local future_offset="${1:-0}"
  cardano_cli_log latest query tip --testnet-magic "$NETWORK_MAGIC" | jq -r ".slot + $future_offset"
}

get_era() {
  cardano_cli_log latest query tip --testnet-magic "$NETWORK_MAGIC" | jq -r ".era"
}

get_sec_to_epoch_end() {
  cardano_cli_log latest query tip --testnet-magic "$NETWORK_MAGIC" |
    jq -r "$(get_slot_length) * .slotsToEpochEnd | ceil"
}

wait_for_era() {
  local target_era="${1:?"Missing target era"}"
  local era
  local _

  for _ in {1..10}; do
    era="$(get_era)"
    if [ "$era" = "$target_era" ]; then
      return
    fi
    sleep 3
  done

  echo "Unexpected era '$era' instead of '$target_era'" >&2
  exit 1
}

wait_for_epoch() {
  local start_epoch
  local target_epoch="${1:?"Missing target epoch"}"
  local epochs_to_go=1
  local sec_to_epoch_end
  local sec_to_sleep
  local curr_epoch
  local _

  start_epoch="$(get_epoch)"

  if [ "$start_epoch" -ge "$target_epoch" ]; then
    return
  else
    epochs_to_go="$((target_epoch - start_epoch))"
  fi

  sec_to_epoch_end="$(get_sec_to_epoch_end)"
  sec_to_sleep="$(( sec_to_epoch_end + ((epochs_to_go - 1) * $(get_epoch_sec)) ))"
  sleep "$sec_to_sleep"

  for _ in {1..10}; do
    curr_epoch="$(get_epoch)"
    if [ "$curr_epoch" -ge "$target_epoch" ]; then
      return
    fi
    sleep 3
  done

  echo "Unexpected epoch '$curr_epoch' instead of '$target_epoch'" >&2
  exit 1
}

rm_retry() {
  # Trying to remove a directory inside /var/tmp on a container may sometimes fail with
  # "rmdir: directory not empty" error when the directory was created while running
  # an older container.
  # This function retries removing the target several times before giving up.
  local target="${1:?"Missing target to remove"}"
  local i

  for i in {1..5}; do
    if [ "$i" -gt 1 ]; then
      sleep 1
    fi
    if rm -rf "$target"; then
      return 0
    fi
  done
  return 1
}

save_protocol_params() {
  local pparams_file="${1:?"Missing protocol parameters output file"}"
  local era="${2:-latest}"

  cardano_cli_log "$era" query protocol-parameters \
    --testnet-magic "$NETWORK_MAGIC" \
    --out-file "$pparams_file"
}

configure_supervisor() {
  local enable_submit_api
  enable_submit_api="$(command -v cardano-submit-api >/dev/null 2>&1 && echo 1 || echo 0)"

  cat >> "${STATE_CLUSTER:?}/supervisor.conf" <<EoF

[unix_http_server]
file = ${SUPERVISORD_SOCKET_PATH:?}

[supervisorctl]
serverurl = unix:///${SUPERVISORD_SOCKET_PATH:?}
EoF

  if [ -n "${DBSYNC_SCHEMA_DIR:-}" ]; then
    command -v cardano-db-sync > /dev/null 2>&1 || \
      { echo "The \`cardano-db-sync\` binary not found, line $LINENO in ${BASH_SOURCE[0]}" >&2; exit 1; }

    if ! is_truthy "${DRY_RUN:-}"; then
      "${SCRIPT_DIR:?}/postgres-setup.sh"
    fi

    cp "${SCRIPT_DIR:?}/run-cardano-dbsync" "$STATE_CLUSTER"

    cat >> "${STATE_CLUSTER:?}/supervisor.conf" <<EoF

[program:dbsync]
command=./${STATE_CLUSTER_NAME:?}/run-cardano-dbsync
stderr_logfile=./${STATE_CLUSTER_NAME}/dbsync.stderr
stdout_logfile=./${STATE_CLUSTER_NAME}/dbsync.stdout
autostart=false
autorestart=false
startsecs=5
EoF
  fi

  if [ -n "${DBSYNC_SCHEMA_DIR:-}" ] && is_truthy "${SMASH:-}"; then
    command -v cardano-smash-server > /dev/null 2>&1 || \
      { echo "The \`cardano-smash-server\` binary not found, line $LINENO in ${BASH_SOURCE[0]}" >&2; exit 1; }

    cp "${SCRIPT_DIR:?}/run-cardano-smash" "$STATE_CLUSTER"

    cat >> "${STATE_CLUSTER:?}/supervisor.conf" <<EoF

[program:smash]
command=./${STATE_CLUSTER_NAME}/run-cardano-smash
stderr_logfile=./${STATE_CLUSTER_NAME}/smash.stderr
stdout_logfile=./${STATE_CLUSTER_NAME}/smash.stdout
autostart=false
autorestart=false
startsecs=5
EoF
  fi

  if [ "${enable_submit_api:-}" -eq 1 ]; then
    cat >> "${STATE_CLUSTER}/supervisor.conf" <<EoF

[program:submit_api]
command=./${STATE_CLUSTER_NAME}/run-cardano-submit-api
stderr_logfile=./${STATE_CLUSTER_NAME}/submit_api.stderr
stdout_logfile=./${STATE_CLUSTER_NAME}/submit_api.stdout
autostart=false
autorestart=false
startsecs=5
EoF
  fi
}

create_cluster_scripts() {
  printf "#!/bin/sh\n\nsupervisorctl -s unix:///%s start all" "${SUPERVISORD_SOCKET_PATH:?}" > "${STATE_CLUSTER:?}/supervisorctl_start"
  printf "#!/bin/sh\n\nsupervisorctl -s unix:///%s restart nodes:" "$SUPERVISORD_SOCKET_PATH" > "${STATE_CLUSTER}/supervisorctl_restart_nodes"
  printf "#!/bin/sh\n\nsupervisorctl -s unix:///%s \"\$@\"" "$SUPERVISORD_SOCKET_PATH" > "${STATE_CLUSTER}/supervisorctl"

  cat > "${STATE_CLUSTER}/supervisord_start" <<'EoF'
#!/usr/bin/env bash

set -uo pipefail

SCRIPT_DIR="$(readlink -m "${0%/*}")"

cd "${SCRIPT_DIR}/.."

supervisord --config "${SCRIPT_DIR}/supervisor.conf"
EoF

  cat > "${STATE_CLUSTER}/stop-cluster" <<EoF
#!/usr/bin/env bash

set -uo pipefail

SCRIPT_DIR="\$(readlink -m "\${0%/*}")"
PID_FILE="\${SCRIPT_DIR}/supervisord.pid"
SUPERVISORD_SOCKET_PATH="${SUPERVISORD_SOCKET_PATH}"

if [ -e "\$SUPERVISORD_SOCKET_PATH" ]; then
  supervisorctl -s unix:///\${SUPERVISORD_SOCKET_PATH} stop all || rm -f "\$SUPERVISORD_SOCKET_PATH"
fi

if [ ! -f "\$PID_FILE" ]; then
  echo "Cluster is not running!"
  exit 0
fi

PID="\$(<"\$PID_FILE")"
for _ in {1..5}; do
  if ! kill "\$PID"; then
    break
  fi
  sleep 1
  if [ ! -f "\$PID_FILE" ]; then
    break
  fi
done

rm -f "\$PID_FILE"
echo "Cluster terminated!"
EoF

  chmod u+x "$STATE_CLUSTER"/{supervisorctl*,supervisord_*,stop-cluster}
}

start_cluster_nodes() {
  if is_truthy "${DRY_RUN:-}"; then
    echo "Dry run, not starting cluster"
    exit 0
  fi

  supervisord --config "${STATE_CLUSTER:?}/supervisor.conf"

  local _
  for _ in {1..5}; do
    if [ -S "${CARDANO_NODE_SOCKET_PATH:?}" ]; then
      break
    fi
    echo "Waiting 5 seconds for the nodes to start"
    sleep 5
  done
  [ -S "$CARDANO_NODE_SOCKET_PATH" ] || { echo "Failed to start the nodes, line $LINENO in ${BASH_SOURCE[0]}" >&2; exit 1; }
}

start_optional_services() {
  local enable_submit_api
  enable_submit_api="$(command -v cardano-submit-api >/dev/null 2>&1 && echo 1 || echo 0)"

  if [ -n "${DBSYNC_SCHEMA_DIR:-}" ]; then
    echo "Starting db-sync"
    supervisorctl -s "unix:///${SUPERVISORD_SOCKET_PATH:?}" start dbsync
  fi

  if [ -n "${DBSYNC_SCHEMA_DIR:-}" ] && [ -n "${SMASH:-}" ]; then
    echo "Starting smash"
    supervisorctl -s "unix:///${SUPERVISORD_SOCKET_PATH:?}" start smash
  fi

  if [ "${enable_submit_api:-}" -eq 1 ]; then
    echo "Starting cardano-submit-api"
    supervisorctl -s "unix:///${SUPERVISORD_SOCKET_PATH:?}" start submit_api
  fi
}

create_pool_metadata() {
  local pool_ix="${1:?"Missing pool index"}"
  local pool_name="TestPool${pool_ix}"
  local pool_desc="Test Pool $pool_ix"
  local pool_ticker="TP${pool_ix}"

  cat > "${STATE_CLUSTER}/webserver/pool${pool_ix}.html" <<EoF
<!DOCTYPE html>
<html>
<head>
<title>${pool_name}</title>
</head>
<body>
name: <strong>${pool_name}</strong><br>
description: <strong>${pool_desc}</strong><br>
ticker: <strong>${pool_ticker}</strong><br>
</body>
</html>
EoF

  echo "Generating Pool $pool_ix Metadata"
  jq -n \
    --arg name "$pool_name" \
    --arg description "$pool_desc" \
    --arg ticker "$pool_ticker" \
    --arg homepage "http://localhost:${WEBSERVER_PORT:?}/pool${pool_ix}.html" \
    '{"name": $name, "description": $description, "ticker": $ticker, "homepage": $homepage}' \
    > "${STATE_CLUSTER:?}/webserver/pool${pool_ix}.json"
}

setup_state_cluster() {
  local genesis_init_dir="${1:?"Missing genesis init dir"}"

  if ! rm_retry "${STATE_CLUSTER:?}"; then
    echo "Could not remove existing '$STATE_CLUSTER'" >&2
    exit 1
  fi
  mkdir -p "$STATE_CLUSTER"/{shelley,webserver,db-sync,governance_data}
  cd "${STATE_CLUSTER}/.." || { echo "Could not cd to '${STATE_CLUSTER}/..', line $LINENO in ${BASH_SOURCE[0]}" >&2; exit 1; }

  mkdir -p "$genesis_init_dir"

  cp "${SCRIPT_DIR:?}"/cardano-node-* "$STATE_CLUSTER"
  cp "${SCRIPT_DIR}/run-cardano-submit-api" "$STATE_CLUSTER"
  cp "${SCRIPT_DIR}/byron-params.json" "$STATE_CLUSTER"
  cp "${SCRIPT_DIR}/dbsync-config.yaml" "$STATE_CLUSTER"
  cp "${SCRIPT_DIR}/submit-api-config.json" "$STATE_CLUSTER"
  cp "${SCRIPT_DIR}/supervisor.conf" "$STATE_CLUSTER"
  cp "$SCRIPT_DIR/testnet.json" "$STATE_CLUSTER"
  cp "$SCRIPT_DIR"/*genesis*.spec.json "$genesis_init_dir"
  cp "$SCRIPT_DIR"/cost_models*.json "$genesis_init_dir" 2>/dev/null || true

  if ! is_truthy "${ENABLE_LEGACY:-}"; then
    local tconf tfname
    for tconf in "$SCRIPT_DIR"/p2p-topology-*.json; do
      [ -e "$tconf" ] || { echo "No p2p topology files found in ${SCRIPT_DIR}, line $LINENO in ${BASH_SOURCE[0]}" >&2; exit 1; }
      tfname="${tconf##*/p2p-}"
      cp "$tconf" "${STATE_CLUSTER}/${tfname}"
    done
  else
    cp "$SCRIPT_DIR"/topology-*.json "$STATE_CLUSTER"
  fi
}

create_dreps_files() {
  local i
  for i in $(seq 1 "$NUM_DREPS"); do
    cardano_cli_log conway governance drep key-gen \
      --signing-key-file "${STATE_CLUSTER}/governance_data/default_drep_${i}_drep.skey" \
      --verification-key-file "${STATE_CLUSTER}/governance_data/default_drep_${i}_drep.vkey"

    cardano_cli_log conway governance drep registration-certificate \
      --drep-verification-key-file "${STATE_CLUSTER}/governance_data/default_drep_${i}_drep.vkey" \
      --key-reg-deposit-amt "$DREP_DEPOSIT" \
      --out-file "${STATE_CLUSTER}/governance_data/default_drep_${i}_drep_reg.cert"

    cardano_cli_log conway address key-gen \
      --signing-key-file "${STATE_CLUSTER}/governance_data/vote_stake_addr${i}.skey" \
      --verification-key-file "${STATE_CLUSTER}/governance_data/vote_stake_addr${i}.vkey"

    cardano_cli_log conway stake-address key-gen \
      --signing-key-file "${STATE_CLUSTER}/governance_data/vote_stake_addr${i}_stake.skey" \
      --verification-key-file "${STATE_CLUSTER}/governance_data/vote_stake_addr${i}_stake.vkey"

    cardano_cli_log conway address build \
      --payment-verification-key-file "${STATE_CLUSTER}/governance_data/vote_stake_addr${i}.vkey" \
      --stake-verification-key-file "${STATE_CLUSTER}/governance_data/vote_stake_addr${i}_stake.vkey" \
      --testnet-magic "$NETWORK_MAGIC" \
      --out-file "${STATE_CLUSTER}/governance_data/vote_stake_addr${i}.addr"

    cardano_cli_log conway stake-address build \
      --stake-verification-key-file "${STATE_CLUSTER}/governance_data/vote_stake_addr${i}_stake.vkey" \
      --testnet-magic "$NETWORK_MAGIC" \
      --out-file "${STATE_CLUSTER}/governance_data/vote_stake_addr${i}_stake.addr"

    cardano_cli_log conway stake-address registration-certificate \
      --stake-verification-key-file "${STATE_CLUSTER}/governance_data/vote_stake_addr${i}_stake.vkey" \
      --key-reg-deposit-amt "$KEY_DEPOSIT" \
      --out-file "${STATE_CLUSTER}/governance_data/vote_stake_addr${i}_stake.reg.cert"

    cardano_cli_log conway stake-address vote-delegation-certificate \
      --stake-verification-key-file "${STATE_CLUSTER}/governance_data/vote_stake_addr${i}_stake.vkey" \
      --drep-verification-key-file "${STATE_CLUSTER}/governance_data/default_drep_${i}_drep.vkey" \
      --out-file "${STATE_CLUSTER}/governance_data/vote_stake_addr${i}_stake.vote_deleg.cert"
  done
}

create_committee_keys_in_genesis() {
  if is_truthy "${NO_CC:-}"; then
    return
  fi

  local i
  for i in $(seq 1 "${NUM_CC:?}"); do
    cardano_cli_log conway governance committee key-gen-cold \
      --cold-verification-key-file "${STATE_CLUSTER:?}/governance_data/cc_member${i}_committee_cold.vkey" \
      --cold-signing-key-file "${STATE_CLUSTER}/governance_data/cc_member${i}_committee_cold.skey"
    cardano_cli_log conway governance committee key-gen-hot \
      --verification-key-file "${STATE_CLUSTER}/governance_data/cc_member${i}_committee_hot.vkey" \
      --signing-key-file "${STATE_CLUSTER}/governance_data/cc_member${i}_committee_hot.skey"
    cardano_cli_log conway governance committee create-hot-key-authorization-certificate \
      --cold-verification-key-file "${STATE_CLUSTER}/governance_data/cc_member${i}_committee_cold.vkey" \
      --hot-verification-key-file "${STATE_CLUSTER}/governance_data/cc_member${i}_committee_hot.vkey" \
      --out-file "${STATE_CLUSTER}/governance_data/cc_member${i}_committee_hot_auth.cert"
    cardano_cli_log conway governance committee key-hash \
      --verification-key-file "${STATE_CLUSTER}/governance_data/cc_member${i}_committee_cold.vkey" \
      > "${STATE_CLUSTER}/governance_data/cc_member${i}_committee_cold.hash"
  done

  local key_hash_json
  key_hash_json="$(jq -nR '[inputs | {("keyHash-" + .): 10000}] | add' \
    "$STATE_CLUSTER"/governance_data/cc_member*_committee_cold.hash)"
  jq \
    --argjson keyHashJson "$key_hash_json" \
    '.committee.members = $keyHashJson
    | .committee.threshold = 0.6
    | .committeeMinSize = 2
    | .plutusV3CostModel |= .[0:251]' \
    "${STATE_CLUSTER}/shelley/genesis.conway.json" > "${STATE_CLUSTER}/shelley/genesis.conway.json_jq"
  cat "${STATE_CLUSTER}/shelley/genesis.conway.json_jq" > "${STATE_CLUSTER}/shelley/genesis.conway.json"
  rm -f "${STATE_CLUSTER}/shelley/genesis.conway.json_jq"
}
