# Provider gate

## Purpose

KRCN Core is offline by default. Provider selection must never be inferred from environment variables, host configuration, installed SDKs, or previously used credentials.

## Local default

When no provider is explicitly requested, the core selects the declared deterministic local provider. Its policy must state that it is enabled and that data does not leave the device.

## Remote request

Before remote provider use, a request must disclose:

- provider identity;
- endpoint;
- data categories;
- operation scope;
- retention assumptions;
- current session identity.

The request receives a deterministic identifier. Approval must match that request and session. Approval for another request or an earlier session is invalid.

Provider endpoints and credentials must not be written to repository context, progress records, logs, or Git. Public summaries expose only whether an endpoint disclosure exists.

## Adapter requirement

Every network-capable CLI, MCP, SDK, plugin, index, search, or integration adapter must call the provider gate immediately before remote use. An approved provider request does not bypass user policy, source binding, mutation, or secret controls.
