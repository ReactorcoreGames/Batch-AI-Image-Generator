Which page(s) is this about?

- https://developers.cloudflare.com/ai-gateway/usage/rest-api/ (section "Specify a gateway")
- https://developers.cloudflare.com/ai-gateway/features/unified-billing/
- https://developers.cloudflare.com/workers-ai/models/flux-2-klein-4b/ (and `flux-2-klein-9b`)

### What needs updating

The AI Gateway REST API page states, under **"Specify a gateway"**:

> Workers AI requests always require this header.

This is unqualified, but it does not hold for the Workers AI models that take a `multipart/form-data` body. For those models there is no request that satisfies both the model schema and the gateway, so they cannot be routed through AI Gateway at all — and therefore cannot be used with Unified Billing.

Concretely, on `@cf/black-forest-labs/flux-2-klein-4b`:

| Request | Result |
|---|---|
| `multipart/form-data`, **no** `cf-aig-gateway-id` | **200 OK**, image returned (billed to neurons) |
| `multipart/form-data`, **with** `cf-aig-gateway-id: default` | **500**, `{"code":7000,"message":"Invalid request body"}` |
| JSON body, **with** `cf-aig-gateway-id: default` | **400**, `{"code":5006,"message":"AiError: Bad input: Error: required properties at '/' are 'multipart'"}` |

The model requires multipart; the gateway path rejects multipart. The two requirements are mutually exclusive.

This is not an account or configuration problem. On the same account, token and gateway, a JSON-bodied Workers AI model (`@cf/bytedance/stable-diffusion-xl-lightning`) routes through the identical header correctly, returning 200 and a valid image billed to prepaid credit. The failure is specific to the multipart request encoding.

### Why this is confusing as written

The REST API page shows only JSON examples and never mentions request body encoding, so "Workers AI requests always require this header" reads as applying to every Workers AI model. The `flux-2-klein-4b` model page lists `multipart{}` in its schema but says nothing about AI Gateway. Neither page tells a reader that these two facts collide.

The practical consequence: the Unified Billing page presents prepaid credit as the way to continue past the daily free neuron allocation, but for the multipart models it is not, and there is currently no way to discover that short of trying it and getting a `7000` with no explanation.

### Suggested change

Two small additions would resolve it:

1. On the **REST API** page, qualify the sentence — for example: *"Workers AI requests always require this header. Note that models which take a `multipart/form-data` body (such as the FLUX.2 klein models) cannot currently be routed through AI Gateway."*
2. On the **Unified Billing** page, note that multipart Workers AI models are not covered by unified billing and continue to bill against the daily neuron allowance.

If instead this is an unintended gap rather than a documented limitation, then the docs are correct and the API behaviour is the bug — in which case please feel free to redirect this issue accordingly. I've also raised it on the Cloudflare community forum and Discord, since I could not tell from the documentation which of the two it is.

### Reproduction

```bash
# 1. multipart + gateway header -> 500 / 7000
curl -X POST \
  "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/ai/run/@cf/black-forest-labs/flux-2-klein-4b" \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "cf-aig-gateway-id: default" \
  -F "prompt=a red cube on a white table" \
  -F "width=1536" -F "height=864" -F "seed=4242"

# 2. JSON + gateway header -> 400 / 5006 "required properties at '/' are 'multipart'"
curl -X POST \
  "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/ai/run/@cf/black-forest-labs/flux-2-klein-4b" \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "cf-aig-gateway-id: default" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"a red cube on a white table","width":1536,"height":864,"seed":4242}'

# 3. control: same multipart body, header removed -> 200 OK
curl -X POST \
  "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/ai/run/@cf/black-forest-labs/flux-2-klein-4b" \
  -H "Authorization: Bearer $API_TOKEN" \
  -F "prompt=a red cube on a white table" \
  -F "width=1536" -F "height=864" -F "seed=4242"

# 4. control: JSON-bodied model through the same gateway header -> 200 OK
curl -X POST \
  "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/ai/run/@cf/bytedance/stable-diffusion-xl-lightning" \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "cf-aig-gateway-id: default" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"a red cube on a white table","width":1024,"height":576,"num_steps":8,"seed":4242}'
```

Gateway used was `default`, with `workers_ai_billing_mode: unified` confirmed via `GET /accounts/{account_id}/ai-gateway/gateways/default`.

Request identifiers, if useful:

| Case | Identifier |
|---|---|
| multipart + header → 7000 | cf-ray `a384c8650aaf266f-HEL`, `a384c8686f7ba1a0-HEL` |
| JSON + header → 5006 | requestId `39d38831-08d1-4438-975b-1d845b4ce934`, `1a0241e6-eb89-4c2a-9884-d1a84e82e21a` |

Tested 2026-09-09. Note the `7000` responses carry no `requestId` in the body, only a `cf-ray`.
