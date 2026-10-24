# Isolated staging preparation

This directory defines a fail-closed staging topology and release-input
preflight. It is preparation only: neither validation command pulls images,
creates containers, runs migrations, changes Cloudflare, or starts services.

## Boundaries

- Every runtime is an externally published image selected by immutable
  `sha256` digest. The root workspace never builds application release images.
- The independently deployed frontend and backend repositories own their
  images. A release must record each owning commit and CI result; a root
  gitlink remains only the tested integration baseline.
- Database, application, media, and the two tunnel-ingress networks are
  internal. A separate edge network gives only `cloudflared` outbound
  connectivity, while the tunnel can reach only the frontend and storage
  services. No service publishes a host port, including PostgreSQL, the
  backend, MinIO API, and the MinIO console.
- The remotely managed tunnel token is file-backed and scoped to one tunnel.
  Cloudflare must route only the application hostname to `frontend:3000` and
  the distinct upload hostname to `storage:9000`. No route may target the
  backend, database, MinIO console, or host SSH.
- `migrate` is a separate `staging-migration` profile. It is never a backend
  startup side effect and must be run once under a controlled release step.
- Runtime services are behind the explicit `staging-runtime` profile, so the
  checked-in definition has no default startup path.

Cloudflare recommends a remotely managed tunnel for new deployments, and its
[current run-parameter documentation][cloudflare-run-parameters] records
`--token-file` support in `cloudflared` 2025.4.0 or later. The connector in
this contract therefore reads `/run/secrets/cloudflared_token` rather than
placing the token in command arguments or environment variables. The tunnel
and its public hostname routes are external prerequisites, not resources
created by this repository.

[cloudflare-run-parameters]: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/run-parameters/#token-file

## Prepare release inputs without launching

1. Copy `.env.example` to an absolute path outside the clone. Keep it mode
   `0600`, replace all `example.invalid` image references with immutable
   digest references produced by the owning repositories, and use the exact
   public staging origins.
2. Create the absolute `STAGING_SECRETS_DIR` with mode `0700`. Create each
   named secret file from the Compose `secrets` section with mode `0600`,
   owned by the deployment identity. Values must be independent of local,
   CI, and production credentials.
3. Configure a remotely managed Cloudflare Tunnel and exact hostname routes
   separately. Apply the intended Cloudflare Access policy before any runtime
   launch, and verify that the upload hostname can complete the browser's
   presigned POST flow without opening the MinIO console or anonymous writes.
4. Run the non-mutating checks:

   ```sh
   make check-staging
   make staging-preflight STAGING_ENV_FILE=/absolute/path/to/staging.env
   ```

The preflight renders Compose and validates image immutability, explicit
profiles, service/network isolation, secret ownership and modes, distinct
buckets and HTTPS origins, production commands, and the absence of published
ports. It intentionally does not verify that registry images exist or pull
them.

## Launch blockers at the pinned revisions

Do not launch this topology yet. The root `development` baseline currently
pins backend `d9ddb016fd0fd6cff893f1d70dcb067574bedafc` and frontend
`d46626891ca8ec780a554b4fadd7b2515a8c7e5a`. At those independent revisions:

- the backend Dockerfile has only a development target, its production
  requirements do not contain Gunicorn, and its staging settings are tied to
  Vercel branch detection instead of the environment contract used here;
- the frontend Dockerfile has only a development target and no verified
  minimal production image whose build embeds the staging public values;
- registry locations, image provenance, immutable release digests, and the
  root-owned MinIO server/client release images have not been established;
- the tunnel, DNS routes, Access policy, backup/restore rehearsal, controlled
  migration procedure, smoke checks, and digest rollback record have not been
  created or proven.

Resolve those items through focused issues and PRs in the owning repositories,
then update root gitlinks in separate integration PRs. A passing preflight is
necessary preparation, not authorization to deploy or evidence that staging
is healthy.
