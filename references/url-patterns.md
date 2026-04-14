# URL patterns and payload shapes

Use this reference when the user gives a Chanjet doc page URL and you need the real JSON payload or the latest product and module tree at runtime.

## URL mapping

- Page shell:
  `https://open.chanjet.com/docs/file/apiFile/<slug>`
- Docs root products:
  `https://open.chanjet.com/api/param/default/apiFile`
- Product tree:
  `https://open.chanjet.com/api/doc-center/modulesNameByCode/<product>`
- Real doc-center payload:
  `https://openapi.chanjet.com/developer/api/doc-center/details/<slug>`

Examples:

- `https://open.chanjet.com/docs/file/apiFile/tcloud/tjrzy/openToken`
  -> `https://openapi.chanjet.com/developer/api/doc-center/details/tcloud/tjrzy/openToken`
- `https://open.chanjet.com/docs/file/apiFile/common/base_api/oauth2?id=32130`
  -> `https://openapi.chanjet.com/developer/api/doc-center/details/common/base_api/oauth2?id=32130`

Notes:

- `open.chanjet.com` usually returns only the Nuxt shell HTML, not the document body.
- Product pages like `.../apiFile/tcloud`, `.../apiFile/common`, `.../apiFile/zplus` are directory pages, not leaf documents.
- Module pages like `.../apiFile/tcloud/tjrzy` are also directory pages. Resolve the product tree first, then decide which leaf documents to fetch.
- Preserve query parameters when present.
- If an input slug starts with `apiFile/`, strip that prefix before building the JSON URL.
- `https://openapi.chanjet.com/developer/api/doc-center/details/apiFile/...` is the wrong shape and can return `404`.
- The frontend resolves directories in this order:
  - `apiFile` -> `/api/param/default/apiFile`
  - `apiFile/<product>` -> `/api/doc-center/modulesNameByCode/<product>`
  - `apiFile/<product>/<module>/<leaf>` -> `/developer/api/doc-center/details/<product>/<module>/<leaf>`

## Payload shapes

The doc-center JSON payload usually contains one or both of these arrays:

- `contentForModuleDtoList`
  Use for article or guidance pages.
  Key fields:
  - `moduleName`
  - `body` (HTML fragment)
  - `url`
  - `source`

- `documentApiInfoList`
  Use for structured API reference pages.
  Key fields:
  - `interfaceName`
  - `requestPath`
  - `requestHttpMethod`
  - `parameter.fields`
  - `parameter.examples`
  - `success.fields`
  - `success.examples`
  - `errorCodeList`
  - `openApiJson`

## Extraction rules

- For docs root or product pages, fetch the latest directory or tree API first.
- For module pages, resolve the current children from the product tree instead of assuming cached paths are still valid.
- If the user asks for prose, summarize `contentForModuleDtoList`.
- If the user asks for headers, query params, request body, response schema, or error codes, prefer `documentApiInfoList`.
- If both exist, use `documentApiInfoList` for the contract and `contentForModuleDtoList` for process explanation.
