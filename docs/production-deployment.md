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
