# Token and auth flow notes

Use this reference when the user asks about `openToken`, `refresh_token`, `永久授权码`, `appTicket`, `企业凭证`, or the overall T+ authorization chain.

## Documents to fetch first

- Token overview article:
  `tcloud/tjrzy/openToken`
- Refresh token API:
  `common/base_api/oauth2`
- User auth and permanent auth code APIs:
  `common/app_settled/app_settled_auth`
- App credential, enterprise auth code, and enterprise credential APIs:
  `common/app_settled/app_settled_app_auth`

## Common token strategies

The T+ docs describe three common approaches:

1. Exchange a temporary user auth code for a token every time.
2. Exchange a temporary user auth code once, then refresh with `refresh_token`.
3. Use the permanent-auth flow, then obtain tokens from enterprise credentials plus the user permanent auth code.

## Permanent-auth flow

This is the chain the docs describe for the "用户永久授权码" path:

1. User temporary auth code -> exchange for token response -> keep the user permanent auth code.
2. `appTicket` -> get the app credential.
3. App credential + enterprise temporary auth code -> get the enterprise permanent auth code.
4. App credential + enterprise permanent auth code -> get the enterprise credential.
5. Enterprise credential + user permanent auth code -> get the usable token.

Operationally, the key cached values are:

- user permanent auth code
- enterprise permanent auth code

When the access token expires, the docs indicate you can usually resume from steps 2, 4, and 5 instead of re-running the full user authorization step.

## Practical guidance

- If the user asks "which URL really returns the contract", fetch the structured API doc pages, not only the overview article.
- If the user asks about token validity windows or refresh behavior, verify against the live payload before answering because those values can change.
- If the user asks why an auth flow failed, map the failing step to one of the five stages above before debugging request parameters.
