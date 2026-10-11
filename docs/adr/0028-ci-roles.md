# ADR-0028: A read-only plan role for pull requests, an environment-gated deploy role
Status: Accepted — deploy-role trust and secret scope still to roll out ([known gaps](../security.md#known-gaps))
Date: 2026-10-10

## Context

Both workflows assumed one role, `github-actions-terraform`, with AdministratorAccess. Its trust
policy accepted `ref:refs/heads/main`, `pull_request` and `environment:production`, and its ARN was
a repository secret, so any pull-request job could act as administrator before review — and the
Lambda and frontend dependency installs ran with those credentials in the environment. The
`production` environment's branch rule protected the deploy job, not the role.

The pull-request plan also ran with 2 of the 19 variables the deploy passed and without the
Terraform inputs held as secrets. On a PR that touched neither, it showed the alarm topic being
destroyed and every Lambda changing, so nobody could read it as a preview.

## Decision

- `clouder-prod-gha-plan` (`infra/ci_roles.tf`): `ReadOnlyAccess`, assumable only by
  `repo:tarodo/clouder-core:pull_request`. An inline Deny takes away the reads a plan never makes
  but ReadOnlyAccess allows: vendor SecureStrings (the `aws/ssm` key lets any principal in the
  account decrypt), S3 data objects, log events, queue messages, query results. The PR plan runs
  under it with `-lock=false`.
- `github-actions-terraform` (created at bootstrap, outside Terraform) is trusted only by
  `repo:tarodo/clouder-core:environment:production`; its ARN is a secret of that environment.
- AWS credentials are configured after the Lambda is packaged and the frontend built, so no
  dependency install (pip, pnpm with install scripts) runs with them. In `pr.yml` only the
  `terraform` job may request an OIDC token; the other jobs install third-party code without it.
- `infra/prod.tfvars` holds every non-secret production value; the PR plan and both deploy phases
  read it with the same `TF_VAR_*` inputs. Inputs that are not credentials (alarm email, budget
  amount, Beatport client id) are repository secrets so the plan can see them; Terraform marks the
  email and the budget `sensitive`, so no plan prints them. Credentials (vendor API keys, the
  Beatport login) stay in the `production` environment and only reach SSM.
- Dependabot pull requests get no repository secrets; their Terraform check runs `fmt` and
  `validate` without AWS.

## Consequences

- A pull request can read the account's configuration and the Terraform state but change no
  AWS resource and read no vendor secret. The state holds the JWT signing key, which is enough
  to mint an application session, so plan access is roughly application-admin — acceptable
  while only the owner can push branches, and the reason to move the key out of state before
  anyone else can (write-only attributes, or generating it outside Terraform).
- The PR plan is a faithful preview: a change it does not show is not applied.
- The deploy role is still AdministratorAccess ([known gap](../security.md#known-gaps)); only the
  `production` environment, which accepts protected branches only, can assume it. Any step of the
  deploy job can mint an OIDC token, so step order limits exposure to installed code but is not a
  boundary; the trust policy is.
- Rebuilding the account needs the GitHub OIDC provider and the deploy role first; the plan role
  then comes from the first apply.
