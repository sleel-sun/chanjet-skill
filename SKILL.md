---
name: tplus-api-docs
description: Use when the user wants to fetch, clean, summarize, or inspect Chanjet T+ API docs, especially `open.chanjet.com/docs/file/apiFile/...` pages, `openapi.chanjet.com/developer/api/doc-center/details/...` payloads, request/response schemas, or token/auth flows.
---

# T+ API Docs

Use this skill when the user gives a Chanjet doc page URL, asks for a clean version of a T+ API document, wants request and response fields extracted, or wants a T+ token and authorization document mapped to the real endpoint contract. This skill also handles directory pages like product roots and module roots by resolving the latest product tree at runtime before fetching leaf documents.

## Skill path

```bash
export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
export TPLUS_DOC="$CODEX_HOME/skills/tplus-api-docs/scripts/fetch_tplus_doc.py"
```

## Quick start

Use the bundled script. It accepts a page URL, a doc-center JSON URL, or a bare slug:

```bash
python3 "$TPLUS_DOC" \
  "https://open.chanjet.com/docs/file/apiFile/tcloud/tjrzy/openToken" \
  --format markdown

python3 "$TPLUS_DOC" \
  "https://openapi.chanjet.com/developer/api/doc-center/details/common/base_api/oauth2" \
  --format json

python3 "$TPLUS_DOC" \
  "common/app_settled/app_settled_auth" \
  --format markdown --include-openapi

python3 "$TPLUS_DOC" \
  "https://open.chanjet.com/docs/file/apiFile/tcloud" \
  --format markdown

python3 "$TPLUS_DOC" \
  "https://open.chanjet.com/docs/file/apiFile/tcloud/tjrzy" \
  --format text --leaves-only
```

## Core workflow

1. Normalize the user input into one of four runtime targets:
   - docs root
   - product directory
   - module directory
   - leaf document
2. For directory pages, fetch the latest directory data at runtime:
   - root products: `open.chanjet.com/api/param/default/apiFile`
   - product tree: `open.chanjet.com/api/doc-center/modulesNameByCode/<product>`
3. For leaf documents, fetch the JSON payload from `openapi.chanjet.com/developer/api/doc-center/details/...`.
4. Decide which branch matters:
   - `contentForModuleDtoList` for article or guidance pages
   - `documentApiInfoList` for API reference pages
5. Return only the level of detail the user asked for:
   - summary or cleaned prose
   - request path, method, parameters, and examples
   - success schema and error codes
   - parsed OpenAPI JSON when they need contract or codegen detail
6. If the user asks about token acquisition, permanent auth codes, `appTicket`, or enterprise credentials, also read `references/token-auth-flow.md`.

## URL rules

- The page URL is usually a Nuxt shell:
  `https://open.chanjet.com/docs/file/apiFile/<slug>`
- The real JSON payload lives at:
  `https://openapi.chanjet.com/developer/api/doc-center/details/<slug>`
- Preserve query parameters when present.
- If the input contains a leading `apiFile/` segment, strip it before building the JSON URL.
- Do not summarize the raw `open.chanjet.com` HTML shell. Fetch the JSON endpoint instead.
- If the user gives a product or module directory page like `.../apiFile/tcloud` or `.../apiFile/tcloud/tjrzy`, resolve the latest tree at runtime before choosing a leaf document.

Read `references/url-patterns.md` when you need the exact URL mapping and payload shapes.

## Output guidance

- Use `--format markdown` for human-readable summaries or cleaned documents.
- Use `--format json` when the user wants structured fields or downstream processing.
- Add `--include-openapi` when the user needs the embedded `openApiJson` contract.
- Use `--format text` for quick terminal inspection.
- Prefer the structured API page over an article page when the user asks for headers, query params, response schema, or error codes.
- Use `--recursive` to expand a directory tree.
- Use `--leaves-only` to flatten a directory subtree into leaf documents.

## Common tasks

### Clean a doc page

```bash
python3 "$TPLUS_DOC" \
  "https://open.chanjet.com/docs/file/apiFile/tcloud/tjrzy/openToken" \
  --format markdown
```

Use this when the user wants the article body without the site chrome.

### Resolve a product directory

```bash
python3 "$TPLUS_DOC" \
  "https://open.chanjet.com/docs/file/apiFile/zplus" \
  --format markdown
```

Use this when the user gives a product root page and wants the latest modules under that product.

### Resolve a module directory to leaf docs

```bash
python3 "$TPLUS_DOC" \
  "https://open.chanjet.com/docs/file/apiFile/tcloud/tjrzy" \
  --format text --leaves-only
```

Use this when the user gives a module directory and wants the current leaf documents under it.

### Extract an endpoint contract

```bash
python3 "$TPLUS_DOC" \
  "common/base_api/oauth2" \
  --format markdown --include-openapi
```

Use this when the user asks for request headers, query parameters, response examples, or OpenAPI details.

### Save a cleaned export

```bash
python3 "$TPLUS_DOC" \
  "common/app_settled/app_settled_app_auth" \
  --format json \
  --output /tmp/tplus-app-auth.json
```

Use `--output` when the user wants a reusable artifact.

## References

- URL mapping and payload shapes: `references/url-patterns.md`
- T+ token and auth flow notes: `references/token-auth-flow.md`
