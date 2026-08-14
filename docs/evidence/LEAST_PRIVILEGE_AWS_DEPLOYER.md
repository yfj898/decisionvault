# Least-Privilege AWS Deployer Evidence

Date: 2026-08-14

Status: **PASS** for routine DecisionVault Lambda deployment operations.

## Problem under test

Initial AWS bootstrap and deployment work was performed from an AWS root login.
That was unnecessarily privileged for routine code/configuration updates.

An attempted root-source `AssumeRole` path was rejected by AWS because root
accounts cannot assume roles in that way. The remediation therefore uses a
dedicated IAM user rather than pretending the failed role path succeeded.

## Deployer identity

`decisionvault-deployer` has one inline policy scoped to the existing
`decisionvault-agent` Lambda resource. Allowed actions are limited to the Lambda
read/update calls required for deployment and status checks.

The deployer has no IAM administration grant. Its access key is stored only in
the ignored local `.venv` deployment workspace and is not embedded in Lambda,
source control, evidence files, or the public submission.

## Live verification

Using only the restricted deployer identity:

```text
STS identity                  decisionvault-deployer
Lambda configuration update  PASS
Lambda code update           PASS
Lambda state                 Active
Lambda last update           Successful
IAM get-user probe           AccessDenied
least_privilege_aws_deployer PASS
```

Routine deployment therefore no longer executes as root.

## Boundary

This IAM user still uses a long-lived access key in the local deployment
workspace. The key should be rotated or deleted after the final competition
deployment. A longer-lived production setup should prefer an organization-managed
federated/SSO deployment identity and short-lived credentials.
