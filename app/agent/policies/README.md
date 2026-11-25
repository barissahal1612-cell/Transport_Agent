# Runtime IAM policy documents

Not wired yet. `agentcore/agentcore.json` is intentionally unchanged: add the
`additionalPolicies` entries only after you approve them together with Open Decision 1.

| File | Grants |
| ---- | ------ |
| `dynamodb-logistic-ai.json` | `Query` on `logistic-ai-kb`; `Query` on `logistic-ai-users/index/userid-index`; `GetItem` on `logistic-ai-permissions` |
| `secretsmanager-session-secret.json` | `GetSecretValue` on `logistic-ai/session-secret*` |

## Why read-only

The backend only calls `DynamoDataRepository` (`Query`), `DynamoUserRepository.get_by_userid`
(`Query` on `userid-index`) and `DynamoPermissionRepository.get` (`GetItem`). Failure counters,
lockout, user activation and permission edits run in the Streamlit client, so the runtime gets
no `UpdateItem`, `PutItem`, `DeleteItem` or `Scan`. `BatchGetItem` and the kb `sheet-index`
(used only by the ingestion script) are also left out. If backend code starts calling any of
them, add the action and resource here.

## Steps

1. Replace `ACCOUNT_ID` and `REGION` in both files with your values. Do not commit real values.
   Secrets Manager appends a random suffix to secret ARNs, hence the trailing `*`.
2. In `agentcore/agentcore.json`, add to the runtime `agent`:

   ```json
   "additionalPolicies": [
     "policies/dynamodb-logistic-ai.json",
     "policies/secretsmanager-session-secret.json"
   ]
   ```

   Paths are relative to the runtime `codeLocation` (`app/agent/`).
3. Set `LOGISTIC_AI_SESSION_SECRET_ID` (secret name) in the runtime `envVars`, keeping
   `UNIFIED_TRACES_DESTINATION_ENABLED=true`.
4. Run `agentcore deploy`. Do not edit the runtime role by hand (`put-role-policy`); the grant
   would be lost on the next deploy.
