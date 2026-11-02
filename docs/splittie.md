# Splittie

Splittie synchronizes paired YNAB accounts. Apollo runs it as a suspended CronJob in `default`;
installing or upgrading the HelmRelease does not start a sync. The job template defaults to
`run --dry-run`. There is no Service or ingress.

The dedicated CNPG database stores fetched transactions, complement links, and the write audit log.
It uses the shared [Postgres component](databases.md), including continuous WAL archiving and weekly
base backups to its own path in Apollo's R2 bucket. Application pods have no persistent filesystem.
Dry runs and sweeps update the database cache and may run schema migrations, but do not write to YNAB.

## Credentials and configuration

The operator populates the `splittie` item in the `hcc-apollo` 1Password vault with `YNAB_TOKEN`,
`PUSHOVER_TOKEN`, and `PUSHOVER_USER`. ESO creates the application Secret through the `onepassword`
ClusterSecretStore. The database URI comes directly from CNPG's generated `splittie-pg-app` Secret.
Existing shared `cloudflare-r2` and `cnpg-r2` items provide database backup access.
See the [secrets integration](secrets.md) for field and refresh behavior.

The same item supplies these configuration fields. ESO renders a private `splittie.yaml` and the pod
mounts only that key at `/config/splittie.yaml`; Splittie itself does not support account environment
variables. No budget or account names are committed to this repository.

| Field | Value |
|---|---|
| `BUDGET_A`, `BUDGET_B` | Exact YNAB budget names for the first pair. |
| `ACCOUNT_A`, `ACCOUNT_B` | Exact account names in the corresponding budgets. |
| `MIRROR_PAYEE_A`, `MIRROR_PAYEE_B` | Payee to use for mirrors arriving in each corresponding budget. |
| `START_DATE` | Earliest transaction date to sync, in `YYYY-MM-DD` format. |
| `PAYEE_MODE` | `original` retains the merchant as payee; `memo` puts it in the memo and uses the receiving side's mirror payee. |

The first sync is named `primary`, with `writeCap: 50` in the ExternalSecret template. The operator
controls the initial date; no test budgets or household history are enabled implicitly. Local app
testing covers Test A/B. Adding more pairs requires extending the config template and its field mappings.

The private image uses a separate `splittie-ghcr` item in `hcc-apollo`, with `username` and `password`.
Use the GitHub username and a classic PAT with `read:packages` and access to the Splittie package.
ESO creates a `kubernetes.io/dockerconfigjson` Secret referenced by the job's `imagePullSecrets`.

Before running after any field change, wait for the relevant ExternalSecret to refresh and report Ready.
Its `status.refreshTime` must be later than the edit; `refreshInterval` is one hour. A previously Ready
Secret can still hold the old start date. New Jobs read the updated values; do not change configuration
during a run or between its approved preview and sync.

## Manual runs

Run one job at a time, including previews and sweeps. `concurrencyPolicy: Forbid` only coordinates
scheduled jobs; it does not serialize Jobs created manually. Check all Splittie pods, including
Pending pods, before starting another run:

```sh
kubectl --context apollo -n default get pods -l app.kubernetes.io/name=splittie
```

The following commands create live Jobs and require operator approval when run by an agent.
They copy the deployed CronJob template, so image, credentials, and config references match Flux.
They do not edit the Flux-managed CronJob.

Preview the currently configured syncs:

```sh
splittie_job="splittie-preview-$(date +%s)"
kubectl --context apollo -n default create job "$splittie_job" --from=cronjob/splittie
kubectl --context apollo -n default logs -f "job/$splittie_job"
kubectl --context apollo -n default get job "$splittie_job"
```

For a historical sweep, choose the inclusive date range for `primary`:

```sh
splittie_job="splittie-sweep-$(date +%s)"
kubectl --context apollo -n default create job "$splittie_job" \
  --from=cronjob/splittie --dry-run=client -o json |
  jq '.spec.template.spec.containers |= map(if .name == "app" then
    .args = ["sweep", "--sync", "primary", "--from", "2025-01-01", "--to", "2025-12-31"]
    else . end)' |
  kubectl --context apollo -n default create -f -
kubectl --context apollo -n default logs -f "job/$splittie_job"
```

After reviewing a preview and approving its writes, run the same configuration without `--dry-run`:

```sh
splittie_job="splittie-sync-$(date +%s)"
kubectl --context apollo -n default create job "$splittie_job" \
  --from=cronjob/splittie --dry-run=client -o json |
  jq '.spec.template.spec.containers |= map(if .name == "app" then .args = ["run"] else . end)' |
  kubectl --context apollo -n default create -f -
kubectl --context apollo -n default logs -f "job/$splittie_job"
kubectl --context apollo -n default get job "$splittie_job"
```

`run` executes every configured sync; `--sync`, `--from`, and `--to` only apply to `sweep`.
Enable pairs one at a time. For each backlog step, sweep the proposed range, fix the reported issues
in YNAB, move `START_DATE` earlier in 1Password, wait for ESO to refresh, and preview again. Review the
planned write count before raising `writeCap` in the ExternalSecret template through git, then run
and verify balances before moving further back. The cap aborts an entire run above the limit;
it does not process the first N writes. Lower it again after the batch.

Job completion alone does not establish a clean sync. Inspect `sync_applied.failures`,
`run_finished.unbalancedSyncs`, and Pushover notifications as well as the Job's exit status.
Dry-run and sweep output contains transaction details; keep it out of commits and PRs.
Finished Jobs expire after seven days. Failed Jobs do not retry automatically; inspect partial writes
and pending write-log records before deciding to run again.

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
to `[run]` and set `controllers.splittie.cronjob.suspend: false`. The prepared schedule is every
30 minutes, with a 60-second start deadline to avoid replaying a long suspension. Confirm the final
start dates and write cap first, and ensure no manually started Job is still running.

## References

- [Splittie design and CLI](https://github.com/evanmoelter/splittie/blob/main/docs/designs/20261101-splittie.md)
- [Community app-template CronJob example](https://github.com/onedr0p/home-ops/blob/main/kubernetes/apps/default/recyclarr/app/helmrelease.yaml)
