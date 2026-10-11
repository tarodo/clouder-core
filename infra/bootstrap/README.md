# Bootstrap

Things Terraform cannot own, because it needs them to run: the GitHub OIDC provider, the deploy role `github-actions-terraform` and its policy, the state bucket and the lock table. They were created by hand when the account was set up ([ADR-0028](../../docs/adr/0028-ci-roles.md)). Today only the deploy role's policy is written down here.

## `deploy-role-policy.json`

The policy of `github-actions-terraform`, the role every deploy assumes (only the `production` environment can). It replaces AdministratorAccess.

**What it allows**

- **Services:** 23 AWS services Terraform manages (all actions) and `sts:GetCallerIdentity`. The list comes from 90 days of IAM "service last accessed" data for the role (2026-10-11; there is no CloudTrail trail, so IAM Access Analyzer cannot generate a policy). `tests/unit/test_deploy_role_policy.py` maps every Terraform resource type to its IAM namespace, so a new service fails the pull request, not the deploy.
- **IAM:** writes only on `clouder-prod-*` **roles** (every role Terraform creates is named that way; the test checks it), plus IAM reads and service-linked roles. No IAM policy is writable.

**What it refuses**

- Creating a project role, writing its inline policy, attaching a policy or setting a boundary **unless the role carries the permissions boundary `clouder-role-boundary`** ([`infra/iam_boundary.tf`](../iam_boundary.tf)), removing that boundary, or changing the boundary policy. The boundary lets a role do anything except IAM writes (reads and passing project roles stay), Organizations, account settings and `sts:AssumeRole` — so a project role, whatever its own policy says, cannot grant anyone more IAM or step into another role.
- Attaching any managed policy other than `ReadOnlyAccess` (the plan role's).
- `sts:AssumeRole`, so a trust policy that names the deploy role does not let it become another role.
- Any change to its own role or to this policy (`github-actions-terraform-deploy`).

**What it does not do.** A compromised `main` can still run code under a project role with anything the boundary leaves — every AWS service except IAM writes, Organizations, account and `sts:AssumeRole` — so it can read and delete the project's data and, the account being shared, other projects' resources too. And nothing limits what a project role's **trust policy** says: it could make a role assumable from another account, which would outlive the OIDC session. IAM Access Analyzer's external-access analyzer (free) flags exactly that and is worth turning on. What the policy removes is the step from "deploy" to "IAM administrator": no principal, policy or role can outrank the boundary.

**Checked with the IAM policy simulator** (2026-10-11). Of the 160 actions the role performed in 90 days, 149 are allowed with the boundary on the roles; the 11 refused are ECR actions, unused since July. Refused as intended: a role without the boundary, removing or changing the boundary, attaching AdministratorAccess, changing its own role or policy, `sts:AssumeRole`. A project role given `*:*` inline stays inside the boundary: `iam:AttachRolePolicy` and `iam:CreateUser` are denied, S3 and Scheduler work.

**Known trap:** `enable_secretsmanager_vpc_endpoint = true` (off in production) creates an interface endpoint with private DNS, which likely also needs `route53:AssociateVPCWithHostedZone`; add it before turning the flag on.

### Apply, verify, roll back (owner)

Order matters: the boundary must be on every role before the policy that requires it.

1. Merge the pull request that adds the boundary. Its deploy still runs as AdministratorAccess; it creates `clouder-role-boundary` and sets it on all 25 project roles. Check: `aws iam get-role --role-name clouder-prod-collector-api-role --query Role.PermissionsBoundary`.
2. Then switch the deploy role:

```bash
ACCT=$(aws sts get-caller-identity --query Account --output text)
aws iam create-policy --policy-name github-actions-terraform-deploy \
  --policy-document file://infra/bootstrap/deploy-role-policy.json
aws iam attach-role-policy --role-name github-actions-terraform \
  --policy-arn arn:aws:iam::$ACCT:policy/github-actions-terraform-deploy
aws iam detach-role-policy --role-name github-actions-terraform \
  --policy-arn arn:aws:iam::aws:policy/AdministratorAccess
gh workflow run deploy.yml --ref main && gh run watch   # must end green

# Roll back if any step of the deploy is denied (and report the denied action):
aws iam attach-role-policy --role-name github-actions-terraform \
  --policy-arn arn:aws:iam::aws:policy/AdministratorAccess

# Change the policy later (after the test passes):
aws iam create-policy-version --policy-arn arn:aws:iam::$ACCT:policy/github-actions-terraform-deploy \
  --policy-document file://infra/bootstrap/deploy-role-policy.json --set-as-default
```

A policy keeps at most five versions; delete the oldest non-default one before a sixth.

**Owner-only after the switch** (the deploy fails until the owner applies them): changing the boundary (`infra/iam_boundary.tf`); changing the provider's `default_tags`, which re-tags the boundary policy; reverting the boundary, which needs `iam:DeleteRolePermissionsBoundary` — re-attach AdministratorAccess first.
