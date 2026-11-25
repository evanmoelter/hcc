# Paperless v3 upgrade

Upgrade Paperless on Apollo from 2.20.15 to 3.5.1 in one step. The
[v3 migration guide](https://github.com/paperless-ngx/paperless-ngx/blob/v3.5.1/docs/migration-v3.md)
supports upgrading only from 2.20.15, which is the running version, so intermediate 3.x releases add nothing.

## Decisions

- Accept v3's duplicate handling: duplicates are consumed and flagged in the UI. `PAPERLESS_CONSUMER_DELETE_DUPLICATES`
  stays unset.
- Use the default `PAPERLESS_ARCHIVE_FILE_GENERATION=auto`. Born-digital PDFs no longer receive an archive copy.
- Keep polling the consume directory, renamed to `PAPERLESS_CONSUMER_POLLING_INTERVAL`.
- Replace the deprecated SSL variables with `PAPERLESS_DB_OPTIONS`.
- Raise the startup probe budget from 10 to 30 minutes for the first v3 start, which runs schema migrations,
  recomputes SHA-256 checksums for every file, and rebuilds the search index before the web server listens.
  A probe restart there would interrupt migrations. The library holds about 1.4 GB, so 10 minutes is likely
  enough; the extra budget is insurance.
- Defer Paperless AI to a separate plan. Apollo has no LLM server, so it would need a hosted provider.

Nothing in the repository calls the Paperless API. Gatus checks only the consume monitor.

## Before merging

The v3 schema migrations cannot be reversed. Rolling back means restoring the database and library together.
These steps change the live cluster or need the operator:

- [ ] Note any OCR settings saved in the Paperless admin UI (Configuration). They override environment variables
  and are migrated automatically; recheck them after upgrade.
- [ ] Confirm the consume directory is empty and no tasks are queued.
- [ ] Record a CNPG recovery boundary as described in [databases](../docs/databases.md): a UTC timestamp or named
  restore point, with its WAL segment archived.
- [ ] Trigger a manual library VolSync backup and confirm the snapshot completed after the drain.

## Verification

If the first start outlasts Helm's 5-minute wait, the HelmRelease reports `UpgradeFailed` and retries. The retry
renders the same manifests, so it does not restart the pod. Watch the pod logs, not the release status, and do not
roll back or restart while migrations run.

- [ ] Pod starts; logs show migrations and `[init-index]` completing without errors or deprecation warnings.
- [ ] SSO login succeeds. On `invalid_client`, add `"token_auth_method": "client_secret_basic"` to the provider
  settings in the `paperless` 1Password item. On a 403, set `PAPERLESS_TRUSTED_PROXIES`.
- [ ] A scan with an ASN barcode through SFTP is consumed, tagged, and assigned its ASN.
- [ ] Full-text search returns expected documents. Saved views relying on unqualified note matches need
  `notes.note:` added.
- [ ] Admin UI OCR settings match the recorded values, with archive generation at `auto`.
- [ ] The scheduled classifier training task succeeds.
- [ ] The next library and consume backups succeed.

## Follow-up

- [ ] Restore the startup probe `failureThreshold` to 120.
- [ ] Plan Paperless AI: provider, model, data exposure, and the apply-suggestions workflow.
