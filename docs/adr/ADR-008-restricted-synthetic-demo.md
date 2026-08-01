# ADR-008: Restrict the temporary synthetic AWS demo

## Status
Accepted.

## Decision
Only synthetic data is allowed. ALB ingress always requires an explicit restricted non-world CIDR;
tasks have no public IP. Preferred `https_token` mode adds ACM HTTPS and a constant-time
`Authorization: Bearer` check on prediction. The value comes from a pre-created SSM SecureString ARN
and never enters Terraform. Token-exempt health routes return minimal status and `/metrics` is not
publicly routed. `http_cidr_only` is a short-lived fallback that transmits no reusable token and must
not be described as authenticated or secure transport. This gate is not an enterprise identity
system; the dashboard is read-only and CIDR-restricted.
