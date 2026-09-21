# Deploy on Render

The repository's `render.yaml` is a minimal Render Blueprint for the
OpenJarvis API server. It builds `deploy/docker/Dockerfile`, binds the server to
Render's default web-service port (`10000`), and uses OpenAI's `gpt-4o-mini`
through the cloud engine.

## Create the service

1. Open Render's **New Blueprint Instance** flow and select your OpenJarvis
   fork.
2. Provide `OPENAI_API_KEY` when Render asks for the Blueprint secret.
3. Apply the Blueprint and wait for `/health` to become healthy.
4. Retrieve the generated `OPENJARVIS_API_KEY` from the Render dashboard and
   send it as `Authorization: Bearer <key>` with API requests.

The Blueprint pins both the `PORT` environment variable and the server's
`--port` argument to `10000`. Render's Docker command does not expand `$PORT`,
so if you customize the service port, update both values in `render.yaml`.

The Blueprint deliberately requires one provider key. Render treats every
`sync: false` environment variable as an input during initial creation, so
listing every optional cloud provider would incorrectly require credentials
for all of them. To use another provider, install its corresponding OpenJarvis
inference extra in the image, change `--model` to a model that provider serves,
and replace the secret in your own Blueprint.

## Storage and free-instance limits

!!! warning "Free instances do not preserve OpenJarvis data"
    Render's free web-service filesystem is ephemeral. Everything written to
    `/home/openjarvis/.openjarvis` — including configuration, credentials,
    connector tokens, local databases, and learned state — is lost whenever
    the service restarts, spins down, or redeploys. Free instances also spin
    down after periods without inbound traffic and are not suitable for
    production or durable personal-assistant state.

For durable state, upgrade the service to a paid instance and attach a
persistent disk at `/home/openjarvis/.openjarvis`, or configure the relevant
feature to use an external managed datastore. Only data below a persistent
disk's mount path survives a restart; attaching a disk elsewhere does not
preserve the default OpenJarvis home.

The Blueprint intentionally does not declare a disk because Render does not
support persistent disks on free services.
