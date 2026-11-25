# Streamlit client principal: required permissions (documentation only)

This file documents what the principal running the Streamlit client needs. Nothing here is
applied or created by the repository. Replace `ACCOUNT_ID`, `REGION` and `RUNTIME_ID` with your
values and attach the policy yourself after review.

| Need | Actions | Resources |
| ---- | ------- | --------- |
| Call the agent | `bedrock-agentcore:InvokeAgentRuntime` | `arn:aws:bedrock-agentcore:REGION:ACCOUNT_ID:runtime/RUNTIME_ID` and `.../runtime/RUNTIME_ID/runtime-endpoint/*` |
| Users (login, lockout, activate/deactivate, list) | `dynamodb:GetItem`, `Query`, `UpdateItem`, `PutItem`, `Scan` | `table/logistic-ai-users`, `table/logistic-ai-users/index/userid-index` (Query only) |
| Permissions (check, admin edit) | `dynamodb:GetItem`, `Query`, `PutItem`, `DeleteItem` | `table/logistic-ai-permissions` |
| Knowledge base (Dashboard KPIs) | `dynamodb:GetItem`, `Query` | `table/logistic-ai-kb` |
| Session secret | `secretsmanager:GetSecretValue` | `arn:aws:secretsmanager:REGION:ACCOUNT_ID:secret:logistic-ai/session-secret*` |

Trim the action lists to what the deployed client code calls (`UserRepository`,
`PermissionRepository`, `AdminService`); `Scan` is used only by `list_users` and
`count_active_admins`. Dashboard reads go through `Query` on the kb table.

## Example policy

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "InvokeRuntime",
      "Effect": "Allow",
      "Action": "bedrock-agentcore:InvokeAgentRuntime",
      "Resource": [
        "arn:aws:bedrock-agentcore:REGION:ACCOUNT_ID:runtime/RUNTIME_ID",
        "arn:aws:bedrock-agentcore:REGION:ACCOUNT_ID:runtime/RUNTIME_ID/runtime-endpoint/*"
      ]
    },
    {
      "Sid": "UsersReadWrite",
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:UpdateItem", "dynamodb:PutItem", "dynamodb:Scan"],
      "Resource": [
        "arn:aws:dynamodb:REGION:ACCOUNT_ID:table/logistic-ai-users",
        "arn:aws:dynamodb:REGION:ACCOUNT_ID:table/logistic-ai-users/index/userid-index"
      ]
    },
    {
      "Sid": "PermissionsReadWrite",
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:DeleteItem"],
      "Resource": "arn:aws:dynamodb:REGION:ACCOUNT_ID:table/logistic-ai-permissions"
    },
    {
      "Sid": "KbRead",
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem", "dynamodb:Query"],
      "Resource": "arn:aws:dynamodb:REGION:ACCOUNT_ID:table/logistic-ai-kb"
    },
    {
      "Sid": "ReadSessionSecret",
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": "arn:aws:secretsmanager:REGION:ACCOUNT_ID:secret:logistic-ai/session-secret*"
    }
  ]
}
```

The Streamlit client and the backend must read the same session secret. The client signs the
session token; the backend only verifies it.
