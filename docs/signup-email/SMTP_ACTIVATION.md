# Reloop activation: protected entry and distinct acceptance gates

The operator reports `send.litatech.xyz` verified and authorizes
`VASA <noreply@send.litatech.xyz>`. This is the sender; the privately supplied test
inbox is a recipient, not a sender. Domain status is operator-reported until a
real delivery test is confirmed. Do not change DNS or Cloudflare in this task.

Reloop's [official SMTP documentation](https://reloop.sh/docs/examples/smtp/introduction)
confirms `smtp.reloop.sh`, port 587, STARTTLS, and the same API key for username
and password. The existing SMTPMailer is reused with certificate and hostname
verification. No additional SDK is needed.

## The only key-entry action

Codex has no masked chat secret-entry field. Do not paste the key in chat, a
prompt, workflow input, issue, shell command or tracked file. After Actions has
prepared the exact immutable release, the operator opens their own private VPS
terminal as `vasa-builder` and runs:

```sh
python3 /opt/vasa/.local/releases/<prepared-release-SHA>/scripts/configure_smtp.py
```

This is an operator credential action, not direct Codex SSH. Replace the SHA with
the verified preparation result. Enter the key only at the hidden prompt. The
stdlib helper checks project ownership, an owned non-writable private directory,
Git exclusion/untracked status and a real private terminal. It refuses existing
files/symlinks rather than overwriting operator settings. It creates only
`/opt/vasa/.local/smtp.env` with mode 0600 and writes these fixed nonsecret settings:

```dotenv
VASA_SMTP_HOST=smtp.reloop.sh
VASA_SMTP_PORT=587
VASA_SMTP_SENDER='VASA <noreply@send.litatech.xyz>'
VASA_SMTP_STARTTLS=true
VASA_SMTP_DELIVERY_VERIFIED=false
```

Both private credential fields contain the hidden API key. Neither is echoed.
Do not source this file or print it. Report only `VASA_SMTP_PRIVATE_CONFIG_WRITTEN`.
If existing configuration is preserved, review it privately; do not delete it to
satisfy the helper. Other private runtime files and running services are unchanged.

## Automated acceptance before activation

The existing VASA staging VPS workflow now supports explicit
`mode=check`, `recovery=smtp_check`, `release_sha=<prepared-SHA>` and
`smtp_test_recipient=<operator-inbox>`. Codex dispatches it through existing GitHub
authentication after applicable CI and image preparation, without asking the
operator to operate Actions. No key belongs in any workflow input.

It sends exactly one fixed-body test using the prepared web image and the existing
Compose model. `run --rm --no-deps -T` publishes no service ports and replaces or
restarts none of the five running services. It checks ownership, source, private
permissions, all service identities, runtime hashes and canonical Git status.
Only the web service loads smtp.env. Arbitrary stdout/stderr is discarded, including
nonzero-exit replies; only approved fixed SMTP codes can reach Actions logs.

`VASA_SMTP_ACCEPTANCE_OK` means the existing mailer completed STARTTLS, AUTH and
SMTP message submission. `SMTP_MAILBOX_VERIFIED=false` remains explicit. Do not
retry blindly after an ambiguous network outcome: inspect the run result and ask
for receipt. No paid LLM/TTS requests or customer messages are involved.

## Human inbox confirmation and release approval

An actual inbox receipt is required. SMTP acceptance, a mocked mailbox, the
operator-reported verified domain or the existence of a hostname alone is not
delivery proof. Confirm the fixed VASA test arrived in the intended inbox before
an operator sets `VASA_SMTP_DELIVERY_VERIFIED=true` in the private web configuration.
Record that confirmation separately; the test never flips this setting.

Only then may disposable real signup, verification/resend, password recovery and
invitation acceptance be tested. Do not log tokens, message bodies or passwords.
Use existing session, tenant, rate-limit and single-use token protections.
Contact additionally requires its separate trusted recipient configuration.

Application activation still requires exact source/SQL approval, fresh backup
restoration/rollback checks, compatible private web-only configuration and the
existing all-instance logged-in/connected gate. SMTP configuration must not be
used to bypass any gate. In particular an offline WhatsApp account requires the
phone owner's action; do not delete, recreate or re-pair it automatically. If
new private environment keys differ outside the seven approved SMTP fields,
activation still refuses them. The reviewed compatibility rule accepts only a
first complete web-only binding for the exact Reloop host, port, sender,
authenticated STARTTLS transport and private file specified above. It cannot
replace existing SMTP credentials/settings or ignore any LLM/TTS/voice difference.
The verified-delivery boolean remains a trusted operator attestation, never
set by the controller or the SMTP acceptance test.

Schema 0007 was current in the fresh read-only baseline. No live migration is
authorized automatically. Keep the canonical operator edge/tunnel files untouched
and use the existing isolated release model. All live delivery, real auth workflow
and deployed UI results must be reported separately from automated test results.
