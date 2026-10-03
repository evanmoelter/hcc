# Node-RED

Node-RED keeps its LAN hostname and separate Tailscale endpoint. The editor and admin API have no
application login, preserving the operator's chosen access model. Anyone with network access to
these endpoints can edit and deploy flows. There is no public Gateway route. Adding editor login
later does not automatically protect HTTP endpoints created by flows; see
[upstream authentication guidance](https://nodered.org/docs/user-guide/runtime/securing-node-red).

## Credentials and persistent state

The operator maintains `NODE_RED_CREDENTIAL_SECRET` and `RESTIC_PASSWORD` in the `node-red` item in
`hcc-apollo`. ESO supplies the former to the app and the latter to the shared backup lifecycle.
The committed `settings.js` explicitly reads the encryption key and refuses startup when it is empty.
Setting an environment variable alone does not configure Node-RED's `credentialSecret`.
Keep the encryption key once credentials have been saved; replacing it can make them unreadable.
Projects have their own credential-encryption settings, which must also be preserved with project state.

`/data` holds flows, encrypted credentials, installed nodes, Projects, and runtime state. VolSync
backs it up to Apollo's own repository. Follow [storage guidance](storage.md) and the
[VolSync lifecycle](../kubernetes/apollo/components/volsync/README.md) for recovery; this initial
empty deployment has no restore reference. A successful backup job is not enough when the source is
empty: verify an actual snapshot after Node-RED has initialized its persistent files.

The official image's UID/GID 1000 is retained, including the backup mover. Projects invokes system
Git and OpenSSH, so keeping the image's passwd identity avoids relying on arbitrary-UID support.
`HOME=/data` makes user configuration writable; upstream directs npm's cache into `/data/.npm`.
The settings ConfigMap is mounted separately from persistent data and Reloader restarts the app on
configuration or credential changes. The rest of the container filesystem remains read-only, with
writable temporary storage at `/tmp`.

## Home Assistant

Cutover waits for verified Apollo Home Assistant. The empty runtime has no hard dependency on Home
Assistant readiness, so it can still start for editing or repair during an HA outage. The operator installs
`node-red-contrib-home-assistant-websocket` through the palette and configures
its server node with Home Assistant's base URL and an operator-created long-lived access token.
Use standalone-server settings, leaving the Home Assistant add-on option disabled. Keep the token
in Node-RED's credential fields, never in committed flows or documentation. Node-RED uses the normal
cluster network for the API/WebSocket connection; it does not need Home Assistant's IoT attachment.
See the [integration's server setup](https://github.com/zachowj/node-red-contrib-home-assistant-websocket/blob/main/docs/node/config-server.md).

Verify palette installation, Projects, a harmless deployed flow, persistence after an approved restart,
and an actual Home Assistant event/action before treating the integration as complete. The
[cutover record](../plans/20261003-node-red-migration.md) tracks migration and backup verification.
