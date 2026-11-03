# Splittie

Splittie synchronizes paired YNAB accounts. Apollo runs it as a suspended CronJob in `default`;
installing or upgrading the HelmRelease does not start a sync. The job template defaults to
`run --dry-run`. There is no Service or ingress.

The dedicated CNPG database stores fetched transactions, complement links, and the write audit log.
It uses the shared [Postgres component](databases.md), including continuous WAL archiving and weekly
base backups to its own path in Apollo's R2 bucket. Application pods have no persistent filesystem.
Dry runs and sweeps update the database cache and may run schema migrations, but do not write to YNAB.

## Credentials and configuration

The operator populates the `splittie` item in the `hcc-apollo` 1Password vault with `YNAB_TOKEN`
and the configuration fields below. ESO creates the application Secret through the `onepassword`
ClusterSecretStore. It reuses `PUSHOVER_API_TOKEN` and `PUSHOVER_USER_KEY` from the existing `pushover`
item, mapping them to Splittie's `PUSHOVER_TOKEN` and `PUSHOVER_USER` environment variables.
Do not duplicate those credentials in the `splittie` item.
The database URI comes directly from CNPG's generated `splittie-pg-app` Secret.
Existing shared `cloudflare-r2` and `cnpg-r2` items provide database backup access.
See the [secrets integration](secrets.md) for field and refresh behavior.

The `splittie` item also supplies these configuration fields. ESO renders a private `splittie.yaml` and the pod
mounts only that key at `/config/splittie.yaml`; Splittie itself does not support account environment
variables. No budget or account names are committed to this repository.

| Field | Value |
|---|---|
| `BUDGET_A`, `BUDGET_B` | Exact YNAB budget names for the first pair. |
| `ACCOUNT_A`, `ACCOUNT_B` | Exact account names in the corresponding budgets. |
| `MIRROR_PAYEE_A`, `MIRROR_PAYEE_B` | Payee to use for mirrors arriving in each corresponding budget. |
| `START_DATE` | Earliest transaction date to sync, in `YYYY-MM-DD` format. |
| `PAYEE_MODE` | `original` retains the merchant as payee; `memo` puts it in the memo and uses the receiving side's mirror payee. |
| `WRITE_CAP` (optional) | Positive integer limiting writes per run. Missing or blank uses the default in the ExternalSecret template. |

The first sync is named `primary`; the fallback write cap lives in the
[ExternalSecret template](../kubernetes/apollo/apps/default/splittie/app/externalsecret.yaml). The operator
controls the initial date; no test budgets or household history are enabled implicitly. Local app
testing covers Test A/B. Adding more pairs requires extending the config template and the fields
in the 1Password item.

The `joint-auto` rule runs before syncing in budget A, including history from `START_DATE`.
It converts unsplit `Joint: Auto` transactions into a full-amount split transfer to `ACCOUNT_A`.
Its zero-amount padding line uses `None: None`, which must exist in budget A to keep the split
editable in YNAB. Splittie skips split actions on transactions already in sync accounts.
A real run refetches after rule writes so the new transfers can be mirrored in the same run.
A dry run previews the rule writes, but its sync preview does not include transfers those writes
would create.

The private image uses a separate `splittie-ghcr` item in `hcc-apollo`, with `username` and `password`.
Use the GitHub username and a classic PAT with `read:packages` and access to the Splittie package.
ESO creates a `kubernetes.io/dockerconfigjson` Secret referenced by the job's `imagePullSecrets`.

Before running after any field change, wait for the relevant ExternalSecret to refresh and report Ready.
Its `status.refreshTime` must be later than the edit. A previously Ready Secret can still hold the
old start date. New Jobs read the updated values; do not change configuration during a run or
between its approved preview and sync.

## Manual runs

Run one job at a time, including previews and sweeps. `concurrencyPolicy: Forbid` only coordinates
scheduled jobs; it does not serialize Jobs created manually. Check all Splittie pods, including
Pending pods, before starting another run:

```sh
kubectl --context apollo -n default get pods -l app.kubernetes.io/name=splittie
```

The following commands create live Jobs and require operator approval when run by an agent.
They copy the deployed CronJob template, so image, credentials, and config references match Flux.
They remove the inherited CronJob owner reference so history cleanup cannot delete manual Jobs.
They do not edit the Flux-managed CronJob.

Run these commands from the repository root. The log helper waits for the `app` container to run
or terminate, including a Job that finishes before logs attach. If startup times out, inspect that
Job and its pods, then rerun the log helper with the same Job name. A log-command failure does not
mean the sync failed and is not a reason to create another Job. Earlier retained output is included.

Preview the currently configured syncs:

```sh
splittie_job="splittie-preview-$(date +%s)"
kubectl --context apollo -n default create job "$splittie_job" \
  --from=cronjob/splittie --dry-run=client -o json |
  jq 'del(.metadata.ownerReferences) |
    .spec.template.spec.containers |= map(if .name == "app" then
    .args = ["run", "--dry-run"] else . end)' |
  kubectl --context apollo -n default create -f -
bash scripts/splittie-logs.sh apollo "$splittie_job"
kubectl --context apollo -n default get job "$splittie_job"
```

For a historical sweep, choose the inclusive date range for `primary`:

```sh
splittie_job="splittie-sweep-$(date +%s)"
kubectl --context apollo -n default create job "$splittie_job" \
  --from=cronjob/splittie --dry-run=client -o json |
  jq 'del(.metadata.ownerReferences) |
    .spec.template.spec.containers |= map(if .name == "app" then
    .args = ["sweep", "--sync", "primary", "--from", "2025-01-01", "--to", "2025-12-31"]
    else . end)' |
  kubectl --context apollo -n default create -f -
bash scripts/splittie-logs.sh apollo "$splittie_job"
```

After reviewing a preview and approving its writes, run the same configuration without `--dry-run`:

```sh
splittie_job="splittie-sync-$(date +%s)"
kubectl --context apollo -n default create job "$splittie_job" \
  --from=cronjob/splittie --dry-run=client -o json |
  jq 'del(.metadata.ownerReferences) |
    .spec.template.spec.containers |= map(if .name == "app" then .args = ["run"] else . end)' |
  kubectl --context apollo -n default create -f -
bash scripts/splittie-logs.sh apollo "$splittie_job"
kubectl --context apollo -n default get job "$splittie_job"
```

`run` executes every configured sync; `--sync`, `--from`, and `--to` only apply to `sweep`.
Enable pairs one at a time. For each backlog step, sweep the proposed range, fix the reported issues
in YNAB, move `START_DATE` earlier in 1Password, wait for ESO to refresh, and preview again. Review the
planned write count before raising `WRITE_CAP` in 1Password, wait for ESO to refresh, then run and
verify balances before moving further back. Rules and syncs share the write cap. Each phase aborts
before writing if its plan exceeds the remaining cap; rule planning also reserves writes for the
mirrors its transfers will create. A sync-phase abort can happen after rule writes have succeeded,
so inspect the run before retrying. Lower the cap again after the batch, or clear the field to restore
the default. Malformed or non-positive values fail application configuration validation.

Job completion alone does not establish a clean sync. Inspect `sync_applied.failures`,
`run_finished.unbalancedSyncs`, and Pushover notifications as well as the Job's exit status.
Dry-run and sweep output contains transaction details; keep it out of commits and PRs.
Manual Jobs become eligible for cleanup according to `ttlSecondsAfterFinished` in the
[HelmRelease](../kubernetes/apollo/apps/default/splittie/app/helmrelease.yaml). This is not a guarantee
of log retention; node loss or log rotation can also remove output. Failed Jobs do not retry
automatically; inspect partial writes and pending write-log records before deciding to run again.

## Deployment checks

Verify ExternalSecrets `splittie` and `splittie-ghcr`, Flux Kustomizations `splittie-database` and
`splittie`, HelmRelease `splittie`, and CNPG Cluster `splittie-pg` are Ready. Confirm the CronJob
remains suspended and no application pods started on install.
The first approved preview should confirm image access, credential/config loading, database migrations,
and the expected planned writes. Verify Pushover delivery during testing.

Confirm a completed `splittie-pg` base backup and healthy WAL archiving after the first application run.
Then remove the Postgres `init` component from `ks-database.yaml` in a follow-up commit, preserving the
database and its Kustomization. [Database recovery](databases.md) describes the recovery lifecycle.

## Enabling the schedule

Once testing and backfill are complete, update the HelmRelease through git: change the container args
to `[run]` and set `controllers.splittie.cronjob.suspend: false`. Review the schedule and
start deadline in the HelmRelease; the deadline limits catch-up after suspension. Confirm the final
start dates and write cap first, and ensure no manually started Job is still running.

## References

- [Splittie design and CLI](https://github.com/evanmoelter/splittie/blob/main/docs/designs/20261101-splittie.md)
- [Community app-template CronJob example](https://github.com/onedr0p/home-ops/blob/main/kubernetes/apps/default/recyclarr/app/helmrelease.yaml)
