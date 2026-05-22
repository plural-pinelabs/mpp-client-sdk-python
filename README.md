# pinelabs-online-mpp-client-sdk (Python)

Python port of [`@pinelabs-online/mpp-client-sdk`](../mpp-client-sdk). x402 Machine
Payments Protocol client for AI agents.

Automatically intercepts HTTP 402 Payment Required responses, constructs
UPI SBMD credentials, and completes the payment flow — zero manual
payment handling required.

## Installation

```bash
pip install pinelabs-online-mpp-client-sdk
# or from source
cd mpp-client-sdk-python
pip install -e .
```

Requires Python ≥ 3.9. Depends on `httpx` and `PyJWT[crypto]`.

## Quick Start

```python
from pinelabs-online_mpp_client import pinelabs-onlineclient, pinelabs-onlineclientConfig, MppEnvironment

client = pinelabs-onlineclient.create(pinelabs-onlineclientConfig(
    clientId="your-client-id",
    clientSecret="your-client-secret",
    baseUrl=MppEnvironment.SANDBOX,  # or MppEnvironment.PRODUCTION
))

# `client.get` / `client.post` / `client.request` intercept 402s automatically.
response = client.get("https://api.example.com/paid-resource")
print(response.json())

client.close()
```

`pinelabs-onlineclient.create(...)` supports context-manager usage to release the
underlying HTTP client:

```python
with pinelabs-onlineclient.create(config) as client:
    response = client.get(url)
```

## Configuration

```python
from pinelabs-online_mpp_client import (
    pinelabs-onlineclient, pinelabs-onlineclientConfig, TokenDefaults,
    GrantexConfig, JwksConfig, MppEnvironment,
)

client = pinelabs-onlineclient.create(pinelabs-onlineclientConfig(
    clientId="…", clientSecret="…",

    baseUrl=MppEnvironment.SANDBOX,
    autoHandlePayment=True,

    requestTimeoutMs=30_000,
    maxRetries=3,
    initialRetryDelayMs=500,

    onChallenge=lambda challenge: None,
    onPaymentComplete=lambda receipt: None,

    tokenDefaults=TokenDefaults(maxCharges=10, ttlSeconds=3600),

    grantex=GrantexConfig(
        grantToken="eyJ…",
        jwks=JwksConfig(jwksUrl="https://grantex.dev/.well-known/jwks.json"),
        agentId="my-agent",
        enforceSpendingLimits=True,
    ),
))
```

## How the 402 flow works

1. Your code calls `client.get(url)` (or any HTTP method).
2. If the server returns **HTTP 402** with a `WWW-Authenticate: Payment <challenge>` header, the SDK:
   - decodes the challenge,
   - creates a one-time UPI SBMD payment token,
   - builds a credential,
   - retries the request with `Authorization: Payment <credential>`.
3. The server captures the payment and returns **HTTP 200** with a `Payment-Receipt` header.
4. Your code receives the final 200 response transparently.

## API

### `pinelabs-onlineclient.create(config)`  /  `pinelabs-onlineclient.create_verified(config)`

`create_verified` additionally verifies the Grantex grant token before returning.

### `pinelabs-onlineclientInstance`

| Attribute | Description |
|---|---|
| `get`, `post`, `put`, `delete`, `patch`, `request`, `fetch` | HTTP methods with 402 interception |
| `raw_http` | Underlying `httpx.Client` (no interception) |
| `methods.create_mandate(...)` / `.get_mandate(...)` / `.create_token(...)` | Direct MPP API ops |
| `create_credential(challenge)` | Manually build a credential |
| `grant_claims` / `verify_grant()` | Grantex helpers |
| `close()` / context manager | Close the HTTP client |

## Utilities

```python
from pinelabs-online_mpp_client import decode_challenge, decode_receipt, validate_challenge

challenge = decode_challenge(www_authenticate_header)
validate_challenge(challenge)
receipt = decode_receipt(payment_receipt_header)
```

## Error handling

```python
from pinelabs-online_mpp_client import MppError, MppNetworkError, MppChallengeError

try:
    response = client.get(url)
except MppChallengeError as err:
    ...
except MppNetworkError as err:
    ...
except MppError as err:
    print(err.code, err.http_status, err.details)
```

## Grantex (AI Agent Authorization)

```python
from pinelabs-online_mpp_client import (
    pinelabs-onlineclient, pinelabs-onlineclientConfig, GrantexConfig, JwksConfig,
    check_payment_authorization, extract_spending_limit, has_scope, parse_scope,
)

client = pinelabs-onlineclient.create_verified(pinelabs-onlineclientConfig(
    clientId="…", clientSecret="…",
    grantex=GrantexConfig(
        grantToken=grant_token,
        jwks=JwksConfig(jwksUrl="https://grantex.dev/.well-known/jwks.json"),
    ),
))

print(client.grant_claims)  # GrantTokenClaims(...)
```

## License

MIT
