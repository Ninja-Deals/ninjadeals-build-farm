# Production deployment

Public Farm Build builds ARM64 images from one resolved private-monorepo commit.
Every selected retained service emits a service/source/digest receipt from Docker
metadata; the deployment consumes only artifacts from that same workflow run.
Both frontend replicas use the frontend digest. Empty selection builds all 22
retained application images; retired services are rejected.

`build_only=true` intentionally skips the production job. Otherwise the job runs
in the `production` environment, serialized with other retained deployments:

- `deployment_mode=dry-run`: prepare both host plans, verify exact hashes and
  unchanged configuration/data volumes, and check the public website. No workloads
  are restarted, no dummy accounts/content are created, and no data is cleared.
- `deployment_mode=apply` (default): perform the same review, apply through
  `scripts/deploy/deploy.sh --env production`, verify host readiness and public
  smoke checks, and roll back if verification fails.

The pinned private source must include `scripts/deploy/production_actions.py`.
Existing OCI principal and deploy-key repository secrets remain in use. Deploy
keys exist only in the runner's private temporary directory and are removed after
the job. Bastion sessions are created and cleaned by the coordinator; no sweep of
other operators' sessions occurs. Raw private host plans and credentials are
never published as artifacts. The job summary contains only source/plan hashes
and sanitized outcomes. Legacy staging configuration and mutable latest tags are
not used. This workflow does not deploy native mobile applications.

## Live qualification — 2026-10-02

- [Dummy dry-run](https://github.com/Ninja-Deals/ninjadeals-build-farm/actions/runs/37011751833): setup, frontend build and deploy all passed; workloads were not applied.
- [Production apply](https://github.com/Ninja-Deals/ninjadeals-build-farm/actions/runs/37012673116): setup, frontend build and deploy all passed; both frontend replicas were updated, retained host readiness and public health checks passed.

Both runs built exact private source `645fb3922e7a1a6743603597594e1478d71f520e` with workflow source `a2bdcec824ccad1597ddfef883200e8cbb5e778e`. Live proof covers the frontend selection. All 22 services are supported by allowlist/Dockerfile validation; a full production rebuild was not performed for this qualification. Existing settings and data were preserved, and no dummy production records were created.
