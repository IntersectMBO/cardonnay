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
  : "${STATE_CLUSTER:?STATE_CLUSTER is required}"

  if [ -z "${EPOCH_SEC:-}" ]; then
    EPOCH_SEC="$(jq '.epochLength * .slotLength | ceil' < "${STATE_CLUSTER}/shelley/genesis.json")"
  fi
  echo "$EPOCH_SEC"
}

get_slot_length() {
  : "${STATE_CLUSTER:?STATE_CLUSTER is required}"

  if [ -z "${SLOT_LENGTH:-}" ]; then
    SLOT_LENGTH="$(jq '.slotLength' < "${STATE_CLUSTER}/shelley/genesis.json")"
  fi
  echo "$SLOT_LENGTH"
}

cardano_cli_log() {
  : "${STATE_CLUSTER:?STATE_CLUSTER is required}"

  if [ -z "${START_CLUSTER_LOG:-}" ]; then
    START_CLUSTER_LOG="${STATE_CLUSTER}/start-cluster.log"
  fi

  echo cardano-cli "$@" >> "$START_CLUSTER_LOG"
  cardano-cli "$@"
  return "$?"
}

check_spend_success() {
  : "${NETWORK_MAGIC:?NETWORK_MAGIC is required}"

  local _
  for _ in {1..10}; do
    if ! cardano_cli_log latest query utxo "$@" \
      --testnet-magic "${NETWORK_MAGIC}" --output-text | grep -q lovelace; then
      return 0
    fi
    sleep 6
  done
  return 1
}

get_txins() {
  : "${NETWORK_MAGIC:?NETWORK_MAGIC is required}"

  # Internal locals are prefixed with `_gt_` to avoid shadowing the caller's
  # output variables, which are passed by name.
  local _gt_addr _gt_stop_amount _gt_txins_var _gt_amount_var
  local _gt_txhash _gt_txix _gt_amount _gt_total _gt_i _
  local -a _gt_txins

  _gt_addr="${1:?"Missing TxIn address"}"
  _gt_stop_amount="${2:?"Missing stop TxIn amount"}"
  _gt_txins_var="${3:?"Missing TxIns variable name"}"
  _gt_amount_var="${4:?"Missing TxIn amount variable name"}"

  _gt_stop_amount="$((_gt_stop_amount + 2000000))"

  # Repeat in case `query utxo` fails
  for _ in {1..3}; do
    _gt_txins=()
    _gt_total=0
    while read -r _gt_txhash _gt_txix _gt_amount _; do
      if [ -z "$_gt_txhash" ] || [ -z "$_gt_txix" ] || [ "$_gt_amount" -lt 1000000 ]; then
        continue
      fi
      _gt_total="$((_gt_total + _gt_amount))"
      _gt_txins+=("--tx-in" "${_gt_txhash}#${_gt_txix}")
      if [ "$_gt_total" -ge "$_gt_stop_amount" ]; then
        break
      fi
    done <<< "$(cardano_cli_log latest query utxo \
                --testnet-magic "${NETWORK_MAGIC}" \
                --output-text \
                --address "$_gt_addr" |
                grep -E "lovelace$|[0-9]$|lovelace \+ TxOutDatumNone$|lovelace \+ NoDatum" || echo "")"

    if [ "$_gt_total" -ge "$_gt_stop_amount" ]; then
      break
    fi
  done

  # Set the caller's variables.
  eval "$_gt_txins_var=()"
  for ((_gt_i=0; _gt_i<${#_gt_txins[@]}; _gt_i++)); do
    printf -v "${_gt_txins_var}[$_gt_i]" '%s' "${_gt_txins[$_gt_i]}"
  done
  printf -v "$_gt_amount_var" '%d' "$_gt_total"
}

get_address_balance() {
  : "${NETWORK_MAGIC:?NETWORK_MAGIC is required}"

  local txhash txix amount total_amount _

  # Repeat in case `query utxo` fails
  for _ in {1..3}; do
    total_amount=0
    while read -r txhash txix amount _; do
      if [ -z "$txhash" ] || [ -z "$txix" ]; then
        continue
      fi
      total_amount="$((total_amount + amount))"
    done <<< "$(cardano-cli latest query utxo \
                --testnet-magic "${NETWORK_MAGIC}" \
                --output-text \
                "$@" |
                grep " lovelace" || echo "")"

    if [ "$total_amount" -gt 0 ]; then
      break
    fi
  done

  echo "$total_amount"
}

get_epoch() {
  : "${NETWORK_MAGIC:?NETWORK_MAGIC is required}"

  cardano_cli_log latest query tip --testnet-magic "${NETWORK_MAGIC}" | jq -r '.epoch'
}

get_slot() {
  : "${NETWORK_MAGIC:?NETWORK_MAGIC is required}"

  local future_offset="${1:-0}"
  cardano_cli_log latest query tip --testnet-magic "${NETWORK_MAGIC}" | jq -r ".slot + $future_offset"
}

get_era() {
  : "${NETWORK_MAGIC:?NETWORK_MAGIC is required}"

  cardano_cli_log latest query tip --testnet-magic "${NETWORK_MAGIC}" | jq -r '.era'
}

get_node_version() {
  local version _
  read -r _ version _ < <(cardano-node --version 2>/dev/null)
  [ -n "$version" ] || return 1
  printf '%s\n' "$version"
}

version_parse() {
  # Limitation: minor and patch must be < 1000, else they overflow into the next field.
  local v="${1:?"Missing version"}"
  local major minor patch
  IFS=. read -r major minor patch <<< "$v"
  major="${major%%[!0-9]*}"
  minor="${minor%%[!0-9]*}"
  patch="${patch%%[!0-9]*}"
  printf '%d\n' "$((10#${major:-0} * 1000000 + 10#${minor:-0} * 1000 + 10#${patch:-0}))"
}

get_sec_to_epoch_end() {
  : "${NETWORK_MAGIC:?NETWORK_MAGIC is required}"

  cardano_cli_log latest query tip --testnet-magic "${NETWORK_MAGIC}" |
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
  : "${NETWORK_MAGIC:?NETWORK_MAGIC is required}"

  local pparams_file="${1:?"Missing protocol parameters output file"}"
  local era="${2:-latest}"

  cardano_cli_log "$era" query protocol-parameters \
    --testnet-magic "${NETWORK_MAGIC}" \
    --out-file "$pparams_file"
}

submit_gov_action() {
  : "${FEE:?FEE is required}"
  : "${GOV_ACTION_DEPOSIT:?GOV_ACTION_DEPOSIT is required}"
  : "${FAUCET_ADDR:?FAUCET_ADDR is required}"
  : "${FAUCET_SKEY:?FAUCET_SKEY is required}"
  : "${NETWORK_MAGIC:?NETWORK_MAGIC is required}"
  : "${SUBMIT_DELAY:?SUBMIT_DELAY is required}"

  local action_base="${1:?}"
  local stop_txin_amount="$((FEE + GOV_ACTION_DEPOSIT))"
  local -a txins=()
  local txin_amount=0

  get_txins "${FAUCET_ADDR}" "$stop_txin_amount" txins txin_amount

  local txout_amount="$((txin_amount - stop_txin_amount))"

  cardano_cli_log conway transaction build-raw \
    --fee    "${FEE}" \
    "${txins[@]}" \
    --proposal-file "${action_base}.action" \
    --tx-out "${FAUCET_ADDR}+${txout_amount}" \
    --out-file "${action_base}-tx.txbody"

  cardano_cli_log conway transaction sign \
    --signing-key-file "${FAUCET_SKEY}" \
    --testnet-magic    "${NETWORK_MAGIC}" \
    --tx-body-file     "${action_base}-tx.txbody" \
    --out-file         "${action_base}-tx.tx"

  cardano_cli_log conway transaction submit \
    --tx-file "${action_base}-tx.tx" \
    --testnet-magic "${NETWORK_MAGIC}"

  sleep "${SUBMIT_DELAY}"
  if ! check_spend_success "${txins[@]}"; then
    echo "Failed to spend Tx inputs, line $LINENO in ${BASH_SOURCE[0]}" >&2
    exit 1
  fi
}

create_and_submit_hf_action() {
  : "${GOV_ACTION_DEPOSIT:?GOV_ACTION_DEPOSIT is required}"
  : "${STATE_CLUSTER:?STATE_CLUSTER is required}"

  local hf_action="${1:?}"
  local cmdgroup="${2:?}"
  local major_version="${3:?}"
  local prev_txid="${4:-}"
  local prev_index="${5:-0}"

  local -a prev_args=()
  if [ -n "$prev_txid" ]; then
    prev_args=( \
      "--prev-governance-action-tx-id" "$prev_txid" \
      "--prev-governance-action-index" "$prev_index" \
    )
  fi

  cardano_cli_log "$cmdgroup" governance action create-hardfork \
    --testnet \
    --governance-action-deposit "${GOV_ACTION_DEPOSIT}" \
    --deposit-return-stake-verification-key-file "${STATE_CLUSTER}/nodes/node-pool1/reward.vkey" \
    "${prev_args[@]}" \
    --anchor-url "http://www.hardfork-pv${major_version}.com" \
    --anchor-data-hash 5d372dca1a4cc90d7d16d966c48270e33e3aa0abcb0e78f0d5ca7ff330d2245d \
    --protocol-major-version "$major_version" \
    --protocol-minor-version 0 \
    --out-file "${hf_action}.action"

  submit_gov_action "$hf_action"
}

vote_on_action() {
  : "${STATE_CLUSTER:?STATE_CLUSTER is required}"

  local action_txid="${1:?}"
  local action_base="${2:?}"
  local with_spos="${3:-no}"
  local with_dreps="${4:-no}"
  local f

  echo "Voting on $(basename "$action_base") proposal"

  local index=0
  for f in "${STATE_CLUSTER}"/governance_data/cc_member*_committee_hot.vkey; do
    [ -e "$f" ] || continue
    index="$((index + 1))"
    cardano_cli_log conway governance vote create \
      --yes \
      --governance-action-tx-id "$action_txid" \
      --governance-action-index 0 \
      --cc-hot-verification-key-file "$f" \
      --out-file "${action_base}_cc${index}.vote"
  done

  if [ "$with_spos" = "yes" ]; then
    index=0
    for f in "${STATE_CLUSTER}"/nodes/node-pool*/cold.vkey; do
      [ -e "$f" ] || continue
      index="$((index + 1))"
      cardano_cli_log conway governance vote create \
        --yes \
        --governance-action-tx-id "$action_txid" \
        --governance-action-index 0 \
        --cold-verification-key-file "$f" \
        --out-file "${action_base}_spo${index}.vote"
    done
  fi

  if [ "$with_dreps" = "yes" ]; then
    index=0
    for f in "${STATE_CLUSTER}"/governance_data/default_drep*_drep.vkey; do
      [ -e "$f" ] || continue
      index="$((index + 1))"
      cardano_cli_log conway governance vote create \
        --yes \
        --governance-action-tx-id "$action_txid" \
        --governance-action-index 0 \
        --drep-verification-key-file "$f" \
        --out-file "${action_base}_drep${index}.vote"
    done
  fi
}

submit_votes() {
  : "${STATE_CLUSTER:?STATE_CLUSTER is required}"
  : "${FAUCET_ADDR:?FAUCET_ADDR is required}"
  : "${FAUCET_SKEY:?FAUCET_SKEY is required}"
  : "${FEE:?FEE is required}"
  : "${NETWORK_MAGIC:?NETWORK_MAGIC is required}"
  : "${SUBMIT_DELAY:?SUBMIT_DELAY is required}"

  local votes_base="${1:?}"
  local action_base="${2:?}"
  local f

  local -a vote_files=()
  for f in "$action_base"_*.vote; do
    [ -e "$f" ] || continue
    vote_files+=( "--vote-file" "$f" )
  done
  [ "${#vote_files[@]}" -gt 0 ] || \
    { echo "No vote files found for action base '${action_base}', line $LINENO in ${BASH_SOURCE[0]}" >&2; exit 1; }

  local -a cc_signing=()
  for f in "${STATE_CLUSTER}"/governance_data/cc_member*_committee_hot.skey; do
    [ -e "$f" ] || continue
    cc_signing+=( "--signing-key-file" "$f" )
  done

  local -a pool_signing=()
  if [ -e "${action_base}_spo1.vote" ]; then
    for f in "${STATE_CLUSTER}"/nodes/node-pool*/cold.skey; do
      [ -e "$f" ] || continue
      pool_signing+=( "--signing-key-file" "$f" )
    done
  fi

  local -a drep_signing=()
  if [ -e "${action_base}_drep1.vote" ]; then
    for f in "${STATE_CLUSTER}"/governance_data/default_drep*_drep.skey; do
      [ -e "$f" ] || continue
      drep_signing+=( "--signing-key-file" "$f" )
    done
  fi

  local -a txins=()
  local txin_amount=0

  get_txins "${FAUCET_ADDR}" "${FEE}" txins txin_amount

  local txout_amount="$((txin_amount - FEE))"

  cardano_cli_log conway transaction build-raw \
    --fee    "${FEE}" \
    "${txins[@]}" \
    "${vote_files[@]}" \
    --tx-out "${FAUCET_ADDR}+${txout_amount}" \
    --out-file "${votes_base}-tx.txbody"

  cardano_cli_log conway transaction sign \
    --signing-key-file "${FAUCET_SKEY}" \
    "${cc_signing[@]}" \
    "${pool_signing[@]}" \
    "${drep_signing[@]}" \
    --testnet-magic    "${NETWORK_MAGIC}" \
    --tx-body-file     "${votes_base}-tx.txbody" \
    --out-file         "${votes_base}-tx.tx"

  cardano_cli_log conway transaction submit \
    --tx-file "${votes_base}-tx.tx" \
    --testnet-magic "${NETWORK_MAGIC}"

  sleep "${SUBMIT_DELAY}"
  if ! check_spend_success "${txins[@]}"; then
    echo "Failed to spend Tx inputs, line $LINENO in ${BASH_SOURCE[0]}" >&2
    exit 1
  fi
}

configure_supervisor() {
  : "${STATE_CLUSTER:?STATE_CLUSTER is required}"
  : "${STATE_CLUSTER_NAME:?STATE_CLUSTER_NAME is required}"
  : "${SUPERVISORD_SOCKET_PATH:?SUPERVISORD_SOCKET_PATH is required}"
  : "${SCRIPT_DIR:?SCRIPT_DIR is required}"
  : "${NUM_BFT_NODES:?NUM_BFT_NODES is required}"
  : "${NUM_POOLS:?NUM_POOLS is required}"
  : "${WEBSERVER_PORT:?WEBSERVER_PORT is required}"

  local autorestart_nodes="${1:-false}"
  if is_truthy "$autorestart_nodes"; then
    autorestart_nodes="true"
  else
    autorestart_nodes="false"
  fi

  local -a node_names=()
  local i
  for ((i=1; i<="${NUM_BFT_NODES}"; i++)); do
    node_names+=("bft${i}")
  done
  for ((i=1; i<="${NUM_POOLS}"; i++)); do
    node_names+=("pool${i}")
  done

  cat > "${STATE_CLUSTER}/supervisor.conf" <<EoF
[unix_http_server]
file = ${SUPERVISORD_SOCKET_PATH}

[supervisorctl]
serverurl = unix:///${SUPERVISORD_SOCKET_PATH}
EoF

  for node_name in "${node_names[@]}"; do
    cat >> "${STATE_CLUSTER}/supervisor.conf" <<EoF

[program:${node_name}]
command=./${STATE_CLUSTER_NAME}/cardano-node-${node_name}
stderr_logfile=./${STATE_CLUSTER_NAME}/${node_name}.stderr
stdout_logfile=./${STATE_CLUSTER_NAME}/${node_name}.stdout
autorestart=${autorestart_nodes}
startsecs=5
EoF
  done

  if [ -n "${DBSYNC_SCHEMA_DIR:-}" ]; then
    command -v cardano-db-sync > /dev/null 2>&1 || \
      { echo "The \`cardano-db-sync\` binary not found, line $LINENO in ${BASH_SOURCE[0]}" >&2; exit 1; }

    if ! is_truthy "${DRY_RUN:-}"; then
      "${SCRIPT_DIR}/postgres-setup.sh"
    fi

    cp "${SCRIPT_DIR}/run-cardano-dbsync" "${STATE_CLUSTER}"

    cat >> "${STATE_CLUSTER}/supervisor.conf" <<EoF

[program:dbsync]
command=./${STATE_CLUSTER_NAME}/run-cardano-dbsync
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

    cp "${SCRIPT_DIR}/run-cardano-smash" "${STATE_CLUSTER}"

    cat >> "${STATE_CLUSTER}/supervisor.conf" <<EoF

[program:smash]
command=./${STATE_CLUSTER_NAME}/run-cardano-smash
stderr_logfile=./${STATE_CLUSTER_NAME}/smash.stderr
stdout_logfile=./${STATE_CLUSTER_NAME}/smash.stdout
autostart=false
autorestart=false
startsecs=5
EoF
  fi

  if command -v cardano-submit-api >/dev/null 2>&1; then
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

  if is_truthy "${ENABLE_TX_GENERATOR:-}"; then
    cp "${SCRIPT_DIR}/run-tx-generator" "${STATE_CLUSTER}"

    cat >> "${STATE_CLUSTER}/supervisor.conf" <<EoF

[program:tx_generator]
command=./${STATE_CLUSTER_NAME}/run-tx-generator
stderr_logfile=./${STATE_CLUSTER_NAME}/tx-generator.stderr
stdout_logfile=./${STATE_CLUSTER_NAME}/tx-generator.stdout
autostart=false
autorestart=false
startsecs=5
EoF
  fi

  cat >> "${STATE_CLUSTER}/supervisor.conf" <<EoF

[group:nodes]
programs=$(IFS=,; echo "${node_names[*]}")

[program:webserver]
command=python -m http.server --bind 127.0.0.1 ${WEBSERVER_PORT}
directory=./${STATE_CLUSTER_NAME}/webserver

[rpcinterface:supervisor]
supervisor.rpcinterface_factory=supervisor.rpcinterface:make_main_rpcinterface

[supervisord]
logfile=./${STATE_CLUSTER_NAME}/supervisord.log
pidfile=./${STATE_CLUSTER_NAME}/supervisord.pid
EoF
}

create_cluster_scripts() {
  : "${STATE_CLUSTER:?STATE_CLUSTER is required}"
  : "${SUPERVISORD_SOCKET_PATH:?SUPERVISORD_SOCKET_PATH is required}"

  printf "#!/bin/sh\n\nsupervisorctl -s unix:///%s start all" "${SUPERVISORD_SOCKET_PATH}" > "${STATE_CLUSTER}/supervisorctl_start"
  printf "#!/bin/sh\n\nsupervisorctl -s unix:///%s restart nodes:" "${SUPERVISORD_SOCKET_PATH}" > "${STATE_CLUSTER}/supervisorctl_restart_nodes"
  printf "#!/bin/sh\n\nsupervisorctl -s unix:///%s \"\$@\"" "${SUPERVISORD_SOCKET_PATH}" > "${STATE_CLUSTER}/supervisorctl_local"

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

kill_supervisor() {
  local PID
  PID="\$(<"\$PID_FILE")" || return 1
  if ! kill -0 "\$PID" 2>/dev/null; then
    return 0
  fi
  if ! kill "\$PID"; then
    kill -0 "\$PID" 2>/dev/null || return 0
    return 1
  fi
  for _ in {1..5}; do
    if ! kill -0 "\$PID" 2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  echo "Warning: process \$PID did not exit after SIGTERM, sending SIGKILL." >&2
  kill -9 "\$PID" 2>/dev/null || true
  kill -0 "\$PID" 2>/dev/null && return 1
  return 0
}

if ! kill_supervisor; then
  echo "Failed to terminate cluster with PID \$(<"\$PID_FILE")" >&2
  exit 1
fi
rm -f "\$PID_FILE"
echo "Cluster terminated!"
EoF

  chmod u+x "${STATE_CLUSTER}"/{supervisorctl*,supervisord_*,stop-cluster}
}

start_cluster_nodes() {
  if is_truthy "${DRY_RUN:-}"; then
    echo "Dry run, not starting cluster"
    exit 0
  fi

  : "${STATE_CLUSTER:?STATE_CLUSTER is required}"
  : "${CARDANO_NODE_SOCKET_PATH:?CARDANO_NODE_SOCKET_PATH is required}"

  supervisord --config "${STATE_CLUSTER}/supervisor.conf"

  local _
  for _ in {1..5}; do
    if [ -S "${CARDANO_NODE_SOCKET_PATH}" ]; then
      break
    fi
    echo "Waiting 5 seconds for the nodes to start"
    sleep 5
  done
  [ -S "${CARDANO_NODE_SOCKET_PATH}" ] || { echo "Failed to start the nodes, line $LINENO in ${BASH_SOURCE[0]}" >&2; exit 1; }
}

start_optional_services() {
  : "${SUPERVISORD_SOCKET_PATH:?SUPERVISORD_SOCKET_PATH is required}"

  if [ -n "${DBSYNC_SCHEMA_DIR:-}" ]; then
    echo "Starting db-sync"
    supervisorctl -s "unix:///${SUPERVISORD_SOCKET_PATH}" start dbsync
  fi

  if [ -n "${DBSYNC_SCHEMA_DIR:-}" ] && is_truthy "${SMASH:-}"; then
    echo "Starting smash"
    supervisorctl -s "unix:///${SUPERVISORD_SOCKET_PATH}" start smash
  fi

  if command -v cardano-submit-api >/dev/null 2>&1; then
    echo "Starting cardano-submit-api"
    supervisorctl -s "unix:///${SUPERVISORD_SOCKET_PATH}" start submit_api
  fi
}

create_pool_metadata() {
  : "${STATE_CLUSTER:?STATE_CLUSTER is required}"
  : "${WEBSERVER_PORT:?WEBSERVER_PORT is required}"

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
    --arg homepage "http://localhost:${WEBSERVER_PORT}/pool${pool_ix}.html" \
    '{"name": $name, "description": $description, "ticker": $ticker, "homepage": $homepage}' \
    > "${STATE_CLUSTER}/webserver/pool${pool_ix}.json"
}

setup_state_cluster() {
  : "${STATE_CLUSTER:?STATE_CLUSTER is required}"
  : "${SCRIPT_DIR:?SCRIPT_DIR is required}"

  local genesis_init_dir="${1:?"Missing genesis init dir"}"

  if ! rm_retry "${STATE_CLUSTER}"; then
    echo "Could not remove existing '$STATE_CLUSTER'" >&2
    exit 1
  fi
  mkdir -p "${STATE_CLUSTER}"/{shelley,webserver,db-sync,governance_data}
  cd "${STATE_CLUSTER}/.." || { echo "Could not cd to '${STATE_CLUSTER}/..', line $LINENO in ${BASH_SOURCE[0]}" >&2; exit 1; }

  mkdir -p "$genesis_init_dir"

  cp "${SCRIPT_DIR}"/cardano-node-* "${STATE_CLUSTER}"
  cp "${SCRIPT_DIR}/run-cardano-submit-api" "${STATE_CLUSTER}"
  cp "${SCRIPT_DIR}/byron-params.json" "${STATE_CLUSTER}"
  cp "${SCRIPT_DIR}/dbsync-config.yaml" "${STATE_CLUSTER}"
  cp "${SCRIPT_DIR}/submit-api-config.json" "${STATE_CLUSTER}"
  cp "${SCRIPT_DIR}/testnet.json" "${STATE_CLUSTER}"
  cp "${SCRIPT_DIR}"/*genesis*.spec.json "$genesis_init_dir"
  cp "${SCRIPT_DIR}"/cost_models*.json "$genesis_init_dir" 2>/dev/null || true
  cp "${SCRIPT_DIR}"/topology-*.json "${STATE_CLUSTER}"
}

create_dreps_files() {
  : "${STATE_CLUSTER:?STATE_CLUSTER is required}"
  : "${NUM_DREPS:?NUM_DREPS is required}"
  : "${DREP_DEPOSIT:?DREP_DEPOSIT is required}"
  : "${KEY_DEPOSIT:?KEY_DEPOSIT is required}"
  : "${NETWORK_MAGIC:?NETWORK_MAGIC is required}"

  local i
  for ((i=1; i<="${NUM_DREPS}"; i++)); do
    cardano_cli_log conway governance drep key-gen \
      --signing-key-file "${STATE_CLUSTER}/governance_data/default_drep_${i}_drep.skey" \
      --verification-key-file "${STATE_CLUSTER}/governance_data/default_drep_${i}_drep.vkey"

    cardano_cli_log conway governance drep registration-certificate \
      --drep-verification-key-file "${STATE_CLUSTER}/governance_data/default_drep_${i}_drep.vkey" \
      --key-reg-deposit-amt "${DREP_DEPOSIT}" \
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
      --testnet-magic "${NETWORK_MAGIC}" \
      --out-file "${STATE_CLUSTER}/governance_data/vote_stake_addr${i}.addr"

    cardano_cli_log conway stake-address build \
      --stake-verification-key-file "${STATE_CLUSTER}/governance_data/vote_stake_addr${i}_stake.vkey" \
      --testnet-magic "${NETWORK_MAGIC}" \
      --out-file "${STATE_CLUSTER}/governance_data/vote_stake_addr${i}_stake.addr"

    cardano_cli_log conway stake-address registration-certificate \
      --stake-verification-key-file "${STATE_CLUSTER}/governance_data/vote_stake_addr${i}_stake.vkey" \
      --key-reg-deposit-amt "${KEY_DEPOSIT}" \
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

  : "${STATE_CLUSTER:?STATE_CLUSTER is required}"
  : "${NUM_CC:?NUM_CC is required}"

  local i
  for ((i=1; i<="${NUM_CC}"; i++)); do
    cardano_cli_log conway governance committee key-gen-cold \
      --cold-verification-key-file "${STATE_CLUSTER}/governance_data/cc_member${i}_committee_cold.vkey" \
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
    "${STATE_CLUSTER}"/governance_data/cc_member*_committee_cold.hash)"
  jq \
    --argjson keyHashJson "$key_hash_json" '
    .committee.members = $keyHashJson
    | .committee.threshold = 0.6
    | .committeeMinSize = 2
    | .plutusV3CostModel |= .[0:251]
    ' "${STATE_CLUSTER}/shelley/genesis.conway.json" > "${STATE_CLUSTER}/shelley/genesis.conway.tmp.json"
  mv -f "${STATE_CLUSTER}/shelley/genesis.conway.tmp.json" "${STATE_CLUSTER}/shelley/genesis.conway.json"
}

edit_genesis_conf() {
  : "${BYRON_GENESIS_HASH:?BYRON_GENESIS_HASH is required}"
  : "${SHELLEY_GENESIS_HASH:?SHELLEY_GENESIS_HASH is required}"
  : "${ALONZO_GENESIS_HASH:?ALONZO_GENESIS_HASH is required}"
  : "${CONWAY_GENESIS_HASH:?CONWAY_GENESIS_HASH is required}"
  : "${PROTOCOL_VERSION:?PROTOCOL_VERSION is required}"

  local conf="${1:?"Missing node config file"}"
  local node_ver node_v11
  node_ver="$(version_parse "$(get_node_version || echo 0.0.0)")"
  node_v11="$(version_parse 11.0.0)"

  jq \
    --arg byron_hash "${BYRON_GENESIS_HASH}" \
    --arg shelley_hash "${SHELLEY_GENESIS_HASH}" \
    --arg alonzo_hash "${ALONZO_GENESIS_HASH}" \
    --arg conway_hash "${CONWAY_GENESIS_HASH}" \
    --arg dijkstra_hash "${DIJKSTRA_GENESIS_HASH:-}" \
    --argjson prot_ver "${PROTOCOL_VERSION}" \
    --argjson node_ver "$node_ver" \
    --argjson node_v11 "$node_v11" \
    --argjson enable_experimental "$(is_truthy "${ENABLE_EXPERIMENTAL:-}" && echo true || echo false)" '
    .ByronGenesisHash = $byron_hash
    | .ShelleyGenesisHash = $shelley_hash
    | .AlonzoGenesisHash = $alonzo_hash
    | .ConwayGenesisHash = $conway_hash
    | if $dijkstra_hash != "" then
        (.DijkstraGenesisFile = "shelley/genesis.dijkstra.json"
          | .DijkstraGenesisHash = $dijkstra_hash)
      else
        .
      end
    | if $enable_experimental
        or ($prot_ver >= 11 and $node_ver < $node_v11)
        or ($prot_ver >= 12 and $node_ver >= $node_v11)
      then
        (.ExperimentalProtocolsEnabled = true
          | .ExperimentalHardForksEnabled = true)
      else
        .
      end
    ' "$conf" > "${conf}.tmp.json"
  mv -f "${conf}.tmp.json" "$conf"
}

edit_utxo_backend_conf() {
  : "${STATE_CLUSTER_NAME:?STATE_CLUSTER_NAME is required}"

  local conf="${1:?"Missing node config file"}"
  local node_name="${2:?"Missing node name"}"
  local pool_num="${3:-}"
  local live_tables_base="${STATE_CLUSTER_NAME}/lmdb"
  local utxo_backend index

  utxo_backend="${UTXO_BACKEND:-}"
  # Rotate through the mixed backends for block producing nodes, if set.
  if [ -n "$pool_num" ] && [ "${#UTXO_BACKENDS[@]}" -gt 0 ]; then
    index=$(( (pool_num - 1) % ${#UTXO_BACKENDS[@]} ))
    utxo_backend="${UTXO_BACKENDS[$index]}"
  fi
  if [ "$utxo_backend" = "empty" ]; then
    utxo_backend=""
  fi

  jq \
    --arg backend "$utxo_backend" \
    --arg live_tables_path "${live_tables_base}-${node_name}" '
    if $backend == "mem" then
      (.LedgerDB.Backend = "V2InMemory"
       | .LedgerDB.SnapshotInterval = 216)
    elif $backend == "disk" then
      .LedgerDB.Backend = "V2LSM"
    elif $backend == "disklmdb" then
      (.LedgerDB.Backend = "V1LMDB"
       | .LedgerDB.LiveTablesPath = $live_tables_path
       | .LedgerDB.SnapshotInterval = 300)
    elif has("LedgerDB") then
      .LedgerDB |= del(.Backend)
    else
      .
    end
    | if (.LedgerDB? // {}) == {} then del(.LedgerDB) else . end
    ' "$conf" > "${conf}.tmp.json"
  mv -f "${conf}.tmp.json" "$conf"
}

use_genesis_mode() {
  if ! is_truthy "${USE_GENESIS_MODE:-}"; then
    return
  fi

  : "${STATE_CLUSTER:?STATE_CLUSTER is required}"
  : "${NETWORK_MAGIC:?NETWORK_MAGIC is required}"
  : "${NUM_POOLS:?NUM_POOLS is required}"
  : "${SUPERVISORD_SOCKET_PATH:?SUPERVISORD_SOCKET_PATH is required}"

  echo "Setting up GenesisMode for pools, restarting nodes"

  cardano_cli_log query ledger-peer-snapshot \
    --testnet-magic "${NETWORK_MAGIC}" \
    --socket-path "${STATE_CLUSTER}/pool1.socket" \
    --output-json \
    --out-file "${STATE_CLUSTER}/peer-snapshot.json"
  [ -e "${STATE_CLUSTER}/peer-snapshot.json" ] || \
    { echo "Failed to get peer snapshot from pool1, line $LINENO in ${BASH_SOURCE[0]}" >&2; exit 1; }

  local i
  for ((i=1; i<="${NUM_POOLS}"; i++)); do
    jq '
      .localRoots[] += {"trustable": true}
      | .peerSnapshotFile = "peer-snapshot.json"
      ' "${STATE_CLUSTER}/topology-pool${i}.json" > "${STATE_CLUSTER}/topology-pool${i}.tmp.json"
    mv -f "${STATE_CLUSTER}/topology-pool${i}.tmp.json" "${STATE_CLUSTER}/topology-pool${i}.json"

    jq '.ConsensusMode = "GenesisMode"' \
      "${STATE_CLUSTER}/config-pool${i}.json" > "${STATE_CLUSTER}/config-pool${i}.tmp.json"
    mv -f "${STATE_CLUSTER}/config-pool${i}.tmp.json" "${STATE_CLUSTER}/config-pool${i}.json"
  done

  supervisorctl -s unix:///"${SUPERVISORD_SOCKET_PATH}" restart nodes:
}

_fund_tx_gen() {
  : "${STATE_CLUSTER:?STATE_CLUSTER is required}"
  : "${FAUCET_ADDR:?FAUCET_ADDR is required}"
  : "${FAUCET_SKEY:?FAUCET_SKEY is required}"
  : "${NETWORK_MAGIC:?NETWORK_MAGIC is required}"
  : "${SUBMIT_DELAY:?SUBMIT_DELAY is required}"

  local addr="${1:?}"
  local fund_amount="${2:?}"
  local fee=500000
  local stop_txin_amount="$((fund_amount + fee))"
  local tx_base="${STATE_CLUSTER}/shelley/fund-tx-generator"
  local addr_balance
  local -a txins=()
  local txin_amount=0

  addr_balance="$(get_address_balance --address "$addr")"
  if [ "$addr_balance" -ge "$fund_amount" ]; then
    echo "Tx generator address already has enough funds: $addr_balance lovelace"
    return
  fi

  get_txins "${FAUCET_ADDR}" "$stop_txin_amount" txins txin_amount

  local txout_amount="$((txin_amount - stop_txin_amount))"

  cardano_cli_log latest transaction build-raw \
    --fee    "$fee" \
    "${txins[@]}" \
    --tx-out "${addr}+${fund_amount}" \
    --tx-out "${FAUCET_ADDR}+${txout_amount}" \
    --out-file "${tx_base}-tx.txbody"

  cardano_cli_log latest transaction sign \
    --signing-key-file "${FAUCET_SKEY}" \
    --testnet-magic    "${NETWORK_MAGIC}" \
    --tx-body-file     "${tx_base}-tx.txbody" \
    --out-file         "${tx_base}-tx.tx"

  cardano_cli_log latest transaction submit \
    --tx-file "${tx_base}-tx.tx" \
    --testnet-magic "${NETWORK_MAGIC}"

  sleep "${SUBMIT_DELAY}"
  if ! check_spend_success "${txins[@]}"; then
    echo "Failed to spend Tx inputs, line $LINENO in ${BASH_SOURCE[0]}" >&2
    exit 1
  fi
}

_create_tx_gen_config() {
  if [ $# -lt 4 ]; then
    echo "Usage: _create_tx_gen_config <topology> <node.socket> <config.json> <genesis.skey>" >&2
    return 1
  fi

  local topology_file="$1"
  local socket_path="$2"
  local config_file="$3"
  local skey_file="$4"

  if [ ! -f "$topology_file" ]; then
    echo "Error: topology file not found: $topology_file" >&2
    return 1
  fi

  jq -n \
    --argjson topology "$(<"$topology_file")" \
    --arg socket "$socket_path" \
    --arg config "$config_file" \
    --arg skey "$skey_file" \
    '{
      debugMode: false,
      tx_count: 500000,
      tps: 100,
      inputs_per_tx: 2,
      outputs_per_tx: 2,
      tx_fee: 212345,
      min_utxo_value: 1000000,
      add_tx_size: 100,
      init_cooldown: 5,
      era: "Conway",
      keepalive: 30,
      localNodeSocketPath: $socket,
      nodeConfigFile: $config,
      sigKey: $skey,
      targetNodes: [
        $topology.localRoots[].accessPoints[] |
        {
          addr: "127.0.0.1",
          port: .port,
          name: ("node" + (.port | tostring))
        }
      ],
      plutus: null
    }'
}

_wait_for_tx_gen_log() {
  : "${STATE_CLUSTER:?STATE_CLUSTER is required}"

  local logfile="${STATE_CLUSTER}/tx-generator.stdout"
  local _

  for _ in {1..10}; do
    if [ -f "$logfile" ]; then
      return 0
    fi
    sleep 3
  done
  echo "Tx generator log file was not created, line $LINENO in ${BASH_SOURCE[0]}" >&2
  exit 1
}

_wait_for_tx_gen_tx() {
  : "${STATE_CLUSTER:?STATE_CLUSTER is required}"

  local logfile="${STATE_CLUSTER}/tx-generator.stdout"
  local attempts=360
  local start_time elapsed_time
  local success=0
  local a

  start_time="$EPOCHSECONDS"
  for ((a=1; a<=attempts; a++)); do
    if tail -n 100 "$logfile" | grep -q "SubmissionClientReplyTxIds"; then
      success=1
      break
    fi
    sleep 20
  done

  elapsed_time="$((EPOCHSECONDS - start_time))"
  if [ "$success" -eq 0 ]; then
    echo "Tx generator did not start submitting transactions after $elapsed_time seconds, line $LINENO in ${BASH_SOURCE[0]}" >&2
    exit 1
  fi
  echo "Tx generator started submitting transactions after $elapsed_time seconds"
}

setup_tx_generator() {
  if ! is_truthy "${ENABLE_TX_GENERATOR:-}"; then
    return 0
  fi

  : "${STATE_CLUSTER:?STATE_CLUSTER is required}"
  : "${SUPERVISORD_SOCKET_PATH:?SUPERVISORD_SOCKET_PATH is required}"

  local fund_amount="${1:?}"

  _fund_tx_gen "$(<"${STATE_CLUSTER}/shelley/genesis-utxo2.addr")" "$fund_amount"

  _create_tx_gen_config \
    "${STATE_CLUSTER}/topology-bft1.json" \
    "./pool1.socket" \
    "./config-pool1.json" \
    "./shelley/genesis-utxo2.skey" > "${STATE_CLUSTER}/tx-generator-config.json"

  echo "Starting tx-generator"
  supervisorctl -s "unix:///${SUPERVISORD_SOCKET_PATH}" start tx_generator || \
    { echo "Failed to start tx generator, line $LINENO in ${BASH_SOURCE[0]}" >&2; exit 1; }
  _wait_for_tx_gen_log

  # The tx generator setup takes time, so we wait for it to start submitting transactions before proceeding
  echo "Waiting for tx generator to start submitting transactions"
  _wait_for_tx_gen_tx
}
