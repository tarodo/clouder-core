# Bootstrap

Things Terraform cannot own, because it needs them to run: the GitHub OIDC provider, the deploy role `github-actions-terraform` and its policy, the state bucket and the lock table. They were created by hand when the account was set up ([ADR-0028](../../docs/adr/0028-ci-roles.md)). Today only the deploy role's policy is written down here.

## `deploy-role-policy.json`

The policy of `github-actions-terraform`, the role every deploy assumes (only the `production` environment can). It replaces AdministratorAccess:

- **Services:** 23 AWS services Terraform manages (all actions), IAM (scoped below) and `sts:GetCallerIdentity`. The list comes from 90 days of IAM "service last accessed" data for the role (2026-10-11; there is no CloudTrail trail, so IAM Access Analyzer cannot generate a policy) and is kept in step with the code by `tests/unit/test_deploy_role_policy.py`, which maps every Terraform resource type to its IAM namespace — a new service fails the pull request, not the deploy.
- **IAM:** writes only on `clouder-prod-*` roles and policies (every role Terraform creates is named that way; the test checks it). Attaching any managed policy other than `ReadOnlyAccess` (the plan role's) is denied, so no project role can be given AdministratorAccess. The role cannot change itself.
- **Checked with the IAM policy simulator** (2026-10-11) over the 160 actions the role performed in 90 days: 148 allowed. The rest are 11 ECR actions (unused since July) and `iam:AttachRolePolicy` without a policy ARN, which is allowed for `ReadOnlyAccess` and denied for `AdministratorAccess`.

**Remaining gap:** inline policies (`iam:PutRolePolicy`) on `clouder-prod-*` roles are not bounded, so the role could still write a broad inline policy on a project role. A permissions boundary on those roles is the next step.

### Apply, verify, roll back (owner)

```bash
ACCT=$(aws sts get-caller-identity --query Account --output text)
aws iam create-policy --policy-name clouder-prod-deploy \
  --policy-document file://infra/bootstrap/deploy-role-policy.json
aws iam attach-role-policy --role-name github-actions-terraform \
  --policy-arn arn:aws:iam::$ACCT:policy/clouder-prod-deploy
aws iam detach-role-policy --role-name github-actions-terraform \
  --policy-arn arn:aws:iam::aws:policy/AdministratorAccess
gh workflow run deploy.yml --ref main && gh run watch   # must end green

# Roll back if any step of the deploy is denied (and report the denied action):
aws iam attach-role-policy --role-name github-actions-terraform \
  --policy-arn arn:aws:iam::aws:policy/AdministratorAccess

# Change the policy later (after the test passes):
aws iam create-policy-version --policy-arn arn:aws:iam::$ACCT:policy/clouder-prod-deploy \
  --policy-document file://infra/bootstrap/deploy-role-policy.json --set-as-default
```

A policy keeps at most five versions; delete the oldest non-default one before a sixth.
