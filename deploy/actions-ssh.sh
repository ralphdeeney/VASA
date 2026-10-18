#!/usr/bin/env bash
# Runner only. Never invoke this script from Codex Cloud.
set -euo pipefail
set +x
[[ "${GITHUB_ACTIONS:-}" == true ]] || { echo 'GitHub Actions runner required.' >&2; exit 1; }
case "${VASA_DEPLOY_MODE:-}" in
  check|bootstrap|deploy) ;;
  *) exit 1 ;;
esac
VASA_PROVIDER_SMOKE=${VASA_PROVIDER_SMOKE:-false}
VASA_RECOVERY=${VASA_RECOVERY:-none}
[[ "$VASA_RECOVERY" == none || "$VASA_RECOVERY" == investigate || "$VASA_RECOVERY" == prepare || "$VASA_RECOVERY" == activate || "$VASA_RECOVERY" == smtp_configure || "$VASA_RECOVERY" == smtp_check || "$VASA_RECOVERY" == evolution_check || "$VASA_RECOVERY" == evolution_deploy ]] || exit 1
VASA_RELEASE_SHA=${VASA_RELEASE_SHA:-}
VASA_MIGRATION_SQL_SHA256=${VASA_MIGRATION_SQL_SHA256:-}
VASA_SMTP_TEST_RECIPIENT=${VASA_SMTP_TEST_RECIPIENT:-}
if [[ "$VASA_RECOVERY" == activate ]]; then
  [[ "$VASA_RELEASE_SHA" =~ ^[0-9a-f]{40}$ ]] || exit 1
  [[ "$VASA_MIGRATION_SQL_SHA256" =~ ^[0-9a-f]{64}$ ]] || exit 1
elif [[ "$VASA_RECOVERY" == smtp_check ]]; then
  [[ "$VASA_RELEASE_SHA" =~ ^[0-9a-f]{40}$ && -z "$VASA_MIGRATION_SQL_SHA256" ]] || exit 1
  [[ ${#VASA_SMTP_TEST_RECIPIENT} -le 254 && "$VASA_SMTP_TEST_RECIPIENT" =~ ^[A-Za-z0-9][A-Za-z0-9._%+-]{0,63}@[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,63}$ ]] || exit 1
else
  [[ -z "$VASA_RELEASE_SHA" && -z "$VASA_MIGRATION_SQL_SHA256" ]] || exit 1
fi
[[ "$VASA_RECOVERY" == smtp_check || -z "$VASA_SMTP_TEST_RECIPIENT" ]] || exit 1
[[ "$VASA_RECOVERY" == none || ( "$VASA_DEPLOY_MODE" == check && "$VASA_PROVIDER_SMOKE" == false ) ]] || exit 1
[[ "$VASA_PROVIDER_SMOKE" == false || "$VASA_PROVIDER_SMOKE" == true ]] || exit 1
[[ "$VASA_PROVIDER_SMOKE" == false || "$VASA_DEPLOY_MODE" == deploy ]] || exit 1
[[ "${VASA_VPS_USER:-}" == vasa-builder ]] || { echo 'Unexpected SSH user.' >&2; exit 1; }
[[ "${VASA_VPS_HOST:-}" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*$ ]] || {
  echo 'VPS host must be a hostname or IPv4 address.' >&2; exit 1;
}
[[ "${GITHUB_SHA:-}" =~ ^[0-9a-f]{40}$ ]] || exit 1
[[ -n "${VASA_VPS_SSH_KEY:-}" ]] || { echo 'SSH key is not configured.' >&2; exit 1; }
umask 077
vasa_ssh_dir=$(mktemp -d "${RUNNER_TEMP:?}/vasa-ssh.XXXXXXXX")
trap 'rm -rf -- "$vasa_ssh_dir"' EXIT
printf '%s\n' "$VASA_VPS_SSH_KEY" > "$vasa_ssh_dir/key"
chmod 600 "$vasa_ssh_dir/key"
unset VASA_VPS_SSH_KEY
# No ambient agent, SSH config, trust database, or connection sharing.
if ! ssh-keygen -y -P '' -f "$vasa_ssh_dir/key" > /dev/null 2>&1; then
  echo 'SSH private key is invalid or requires a passphrase.' >&2; exit 1
fi
if ! ssh-keyscan -T 10 -t ed25519,rsa,ecdsa -- "$VASA_VPS_HOST" \
    > "$vasa_ssh_dir/scanned" 2> "$vasa_ssh_dir/scan-error"; then
  echo 'SSH host-key scan failed; no connection was attempted.' >&2; exit 1
fi
: > "$vasa_ssh_dir/known_hosts"
while IFS= read -r vasa_host_key; do
  [[ "$vasa_host_key" != \#* && -n "$vasa_host_key" ]] || continue
  printf '%s\n' "$vasa_host_key" > "$vasa_ssh_dir/candidate"
  vasa_fingerprint=$(ssh-keygen -lf "$vasa_ssh_dir/candidate" -E sha256 | awk '{print $2}')
  if [[ "$vasa_fingerprint" == "${VASA_VPS_HOST_KEY_SHA256:-}" ]]; then
    printf '%s\n' "$vasa_host_key" >> "$vasa_ssh_dir/known_hosts"
  fi
done < "$vasa_ssh_dir/scanned"
if [[ ! -s "$vasa_ssh_dir/known_hosts" ]]; then
  echo 'Host trust is missing or mismatched. Set repository variable VASA_VPS_HOST_KEY_SHA256'
  echo 'to a SHA256 fingerprint obtained through the VPS provider console. No SSH login attempted.'
  exit 1
fi
vasa_remote_payload=deploy/actions_vps.py
if [[ "$VASA_RECOVERY" == smtp_configure ]]; then
  [[ -z "${VASA_REQUEST_FILE:-}" && -z "${VASA_LIVE_ACCEPTANCE_FILE:-}" ]] || exit 1
  vasa_remote_payload="$vasa_ssh_dir/smtp-task.py"
  python3 deploy/actions_smtp_payload.py > "$vasa_remote_payload"
  chmod 600 "$vasa_remote_payload"
fi
unset VASA_RELOOP_API_KEY
if [[ "$VASA_RECOVERY" == evolution_check || "$VASA_RECOVERY" == evolution_deploy ]]; then
  vasa_remote_payload="$vasa_ssh_dir/evolution-task.py"
  python3 deploy/actions_evolution_payload.py > "$vasa_remote_payload"
  chmod 600 "$vasa_remote_payload"
fi
if [[ -n "${VASA_REQUEST_FILE:-}" ]]; then
  [[ "$VASA_DEPLOY_MODE" == check && "$VASA_RECOVERY" == none && "$VASA_PROVIDER_SMOKE" == false ]] || exit 1
  [[ -z "${VASA_LIVE_ACCEPTANCE_FILE:-}" ]] || exit 1
  vasa_remote_payload="$vasa_ssh_dir/request-task.py"
  python3 -m deploy.request_payload "$VASA_REQUEST_FILE" > "$vasa_remote_payload"
  chmod 600 "$vasa_remote_payload"
fi
if [[ -n "${VASA_LIVE_ACCEPTANCE_FILE:-}" ]]; then
  [[ "$VASA_DEPLOY_MODE" == check && "$VASA_RECOVERY" == none && "$VASA_PROVIDER_SMOKE" == false ]] || exit 1
  vasa_remote_payload="$vasa_ssh_dir/private-task.py"
  python3 deploy/actions_live_payload.py "$VASA_LIVE_ACCEPTANCE_FILE" > "$vasa_remote_payload"
  chmod 600 "$vasa_remote_payload"
fi
ssh -F /dev/null -T -p 22 -i "$vasa_ssh_dir/key" \
  -o BatchMode=yes -o IdentitiesOnly=yes -o IdentityAgent=none \
  -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$vasa_ssh_dir/known_hosts" \
  -o GlobalKnownHostsFile=/dev/null -o UpdateHostKeys=no \
  -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no \
  -o ForwardAgent=no -o ClearAllForwardings=yes -o ControlMaster=no \
  -o ConnectTimeout=15 -o ConnectionAttempts=1 -o LogLevel=ERROR \
  -o ServerAliveInterval=15 -o ServerAliveCountMax=4 \
  "$VASA_VPS_USER@$VASA_VPS_HOST" \
  "python3 - '$VASA_DEPLOY_MODE' '$GITHUB_SHA' '$VASA_PROVIDER_SMOKE' '$VASA_RECOVERY' '$VASA_RELEASE_SHA' '$VASA_MIGRATION_SQL_SHA256' '$VASA_SMTP_TEST_RECIPIENT'" < "$vasa_remote_payload"
