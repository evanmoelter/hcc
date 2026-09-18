# Apollo Mealie

Mealie uses a dedicated CNPG database and a restored Longhorn data claim. Its app Kustomization waits
for both restores and ESO. OIDC continues through `sso.${SECRET_DOMAIN}` on the old cluster until
Authentik migrates; a Flux dependency cannot express readiness in another cluster. Verify discovery
and login again when Authentik moves.

The app keeps its existing official image and chart for the first recovery proof. Mealie's later
[verified-email requirement](https://github.com/mealie-recipes/mealie/releases/tag/v3.22.0) needs an
OIDC review before upgrading against the existing Authentik provider. Password login remains disabled.

Separate internal and external HTTPRoutes serve `food.${SECRET_DOMAIN}`. There is no Tailscale Ingress.
Routes and VolSync backups have separate, initially suspended Flux Kustomizations so pod readiness
does not publish an unverified restore or start its PVC backup schedule. Activate them through git
after the gates in the [cutover record](../plans/20260918-mealie-migration.md).

The restored PVC and database have Flux pruning disabled. After verification and the first Apollo
backups, remove temporary recovery machinery as described in the cutover record. Keep the PVC's
immutable `dataSourceRef` and both permanent owning Kustomizations. Subsequent database recovery
uses the Apollo archive; a new PVC recovery requires explicit setup and a new restore ID.

OIDC credentials and the new restic password come from the `mealie` item in the `hcc-apollo` vault.
Temporary source credentials use `mealie-volsync-migration` and `mealie-postgres-migration`.
Apollo backup credentials use the shared `volsync-r2` and `cnpg-r2` items. Reloader restarts Mealie
when its referenced Secrets change.
