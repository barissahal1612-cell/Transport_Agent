# Logistics AI Agent_Backend (Phase 1)

AgentCore Runtime application (runtime `agent`). In Phase 1 it only authenticates and authorizes the caller and then streams a fixed placeholder response. It makes no Amazon Bedrock calls, and uses no memory, tools or MCP.

## Request flow (`main.py`)

1. `parse_payload` returns `(prompt, actor_id, parse_error)`. On an error the handler returns a `validation_error` event and the agent does not run.
2. The `Authorization: Bearer <token>` header (forwarded by AgentCore, see below) is re-verified with `Shared_Auth_Package.TokenVerifier`.
3. The role comes only from the verified `cognito:groups` claim (`resolve_role`). The payload, including `actorId`, is never a role source.
4. `Authorizer.authorize(username, role, "chat:invoke")` decides, deny by default. A denial writes the Requirement 4.5 audit record and returns "Bu işlem için yetkiniz yok".
5. If allowed, the placeholder agent streams the fixed Placeholder_Response as `{"event": {"contentBlockDelta": {"delta": {"text": ...}}}}` events.

Errors are returned as `{"error": <code>, "message": <text>}` with the codes `validation_error`, `unauthenticated`, `forbidden` and `internal_error`. Unexpected exceptions return only the generic message. The agent is created lazily on the first valid request (`_agent` is `None` after import).

## Token type: access token (`expected_token_use="access"`)

The Streamlit_Client sends the Cognito **access token** as the Bearer token. The AgentCore JWT authorizer validates it with `allowedClients`, which checks the `client_id` claim that access tokens carry. ID tokens carry `aud` instead. The backend therefore builds `TokenVerifier(..., expected_token_use="access")`. It checks the signature (JWKS), `exp`, `iss`, `token_use == "access"` and `client_id == LOGISTIC_AI_APP_CLIENT_ID`. Cognito access tokens include `cognito:groups`, so the role can be derived from the same token. An ID token sent as Bearer is rejected (`wrong_token_use`).

## Environment variables

| Variable | Required | Description |
| --- | --- | --- |
| `LOGISTIC_AI_USER_POOL_ID` | Yes | Cognito user pool ID |
| `LOGISTIC_AI_APP_CLIENT_ID` | Yes | The single allowed app client ID |
| `LOGISTIC_AI_AWS_REGION` | Yes | Region of the user pool |
| `LOGISTIC_AI_PERMISSIONS_FILE` | No | Path to the permissions JSON. Defaults to `<project>/config/permissions.json` (local development) |

If a required variable is missing or the permissions file is invalid, every request fails closed with the generic `internal_error` message. Real values must not be committed; set them locally before deployment. `config/permissions.json` is outside the CodeZip `codeLocation` (`app/agent`). For a deployed runtime, put a copy inside `app/agent` and point `LOGISTIC_AI_PERMISSIONS_FILE` at it.

## Permissions

`config/permissions.json` grants `chat:invoke` to each of `SUPPLIER`, `MATERIAL_RESPONSIBLE` and `TRANSPORT_OFFICE` so the placeholder chat works. It is configuration, not a secret. Without this grant, deny-by-default rejects every chat request.

## Design Open Question 2: closed (`requestHeaderAllowlist`)

Result of checking AgentCore CLI 1.0.3 (the `RequestHeaderAllowlistSchema` in `@aws/agentcore`, the generated runtime docs, and the installed `bedrock-agentcore` SDK):

- `agentcore.json` supports `runtimes[].requestHeaderAllowlist` as an array of header names, at most 20 entries. Each name may contain only letters, digits, hyphens and underscores. Names starting with `x-amz-` are rejected, and `x-amzn-` names are rejected unless they start with `x-amzn-bedrock-agentcore-runtime-custom-`. `Authorization` passes this validation.
- `"requestHeaderAllowlist": ["Authorization"]` is now set on the `agent` runtime.
- The SDK (`BedrockAgentCoreApp`) puts the forwarded `Authorization` header into `context.request_headers["Authorization"]`. `main.py` reads the token from there (case-insensitive lookup, `Bearer` scheme).
- Not verified: the service-side forwarding behavior of a deployed runtime. This needs a check after the first deployment (invoke with a valid token and confirm the handler sees the header). If the header is missing, the backend returns `unauthenticated` (fail closed).

## Local development

```bash
agentcore dev --port 8081                       # terminal 1 (never use port 8080)
agentcore invoke --runtime agent --local --port 8081 --payload '{"prompt":"Merhaba"}'
```

Without a valid Bearer token the response is `unauthenticated`.
