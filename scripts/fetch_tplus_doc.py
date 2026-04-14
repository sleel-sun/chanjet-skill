#!/usr/bin/env python3
"""Fetch and normalize Chanjet T+ doc-center pages and directories."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import ParseResult, urlparse, urlunparse
from urllib.request import Request, urlopen


DEFAULT_TIMEOUT = 20
BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "br",
    "div",
    "dl",
    "dt",
    "dd",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "ul",
}
LIST_CONTAINERS = {"ul", "ol"}
HEADER_ORDER = ("Head", "Query", "Path", "Body", "Cookie")
PAGE_ROOT_URL = "https://open.chanjet.com/docs/file/apiFile"
DIRECTORY_ROOT_URL = "https://open.chanjet.com/api/param/default/apiFile"
DIRECTORY_TREE_URL = "https://open.chanjet.com/api/doc-center/modulesNameByCode/{product}"
DOC_DETAILS_URL = "https://openapi.chanjet.com/developer/api/doc-center/details/{slug}"


class HtmlTextExtractor(HTMLParser):
    """Convert small HTML fragments to readable plain text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.list_stack: list[dict[str, Any]] = []
        self.link_stack: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"p", "div", "section", "article", "tr", "table", "pre"}:
            self._newline(2)
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._newline(2)
        elif tag == "br":
            self._newline(1)
        elif tag in LIST_CONTAINERS:
            ordered = tag == "ol"
            self.list_stack.append({"ordered": ordered, "index": 0})
            self._newline(1)
        elif tag == "li":
            if self.list_stack:
                top = self.list_stack[-1]
                if top["ordered"]:
                    top["index"] += 1
                    marker = f"{top['index']}. "
                else:
                    marker = "- "
            else:
                marker = "- "
            self._newline(1)
            self.parts.append(marker)
        elif tag == "a":
            href = dict(attrs).get("href") or ""
            self.link_stack.append({"href": href, "text": ""})

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"p", "div", "section", "article", "tr", "table", "li", "pre"}:
            self._newline(1)
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._newline(2)
        elif tag in LIST_CONTAINERS:
            if self.list_stack:
                self.list_stack.pop()
            self._newline(1)
        elif tag == "a" and self.link_stack:
            link = self.link_stack.pop()
            href = link["href"].strip()
            text = link["text"].strip()
            if href and text and href not in text:
                self.parts.append(f" <{href}>")

    def handle_data(self, data: str) -> None:
        text = unescape(data)
        if not text:
            return
        if self.link_stack:
            self.link_stack[-1]["text"] += text
        self.parts.append(text)

    def get_text(self) -> str:
        text = "".join(self.parts)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n[ \t]+", "\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _newline(self, count: int) -> None:
        if not self.parts:
            return
        existing = 0
        index = len(self.parts) - 1
        while index >= 0 and self.parts[index].endswith("\n"):
            existing += self.parts[index].count("\n")
            break
        missing = max(0, count - existing)
        if missing:
            self.parts.append("\n" * missing)


@dataclass
class NormalizedSource:
    input_value: str
    slug: str
    path_parts: list[str]
    page_url: str | None
    api_url: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch Chanjet T+ doc-center documents or resolve category pages "
            "at runtime from product and module directories."
        )
    )
    parser.add_argument(
        "source",
        help=(
            "Chanjet doc page URL, doc-center JSON URL, or bare slug like "
            "'common/base_api/oauth2'."
        ),
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "text", "json"),
        default="markdown",
        help="Output format. Default: markdown.",
    )
    parser.add_argument(
        "--include-openapi",
        action="store_true",
        help="Include parsed openApiJson content when available.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="When the source is a directory page, expand children recursively.",
    )
    parser.add_argument(
        "--leaves-only",
        action="store_true",
        help="When the source is a directory page, flatten all leaf documents.",
    )
    parser.add_argument(
        "--output",
        help="Write the rendered result to a file instead of stdout.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"HTTP timeout in seconds. Default: {DEFAULT_TIMEOUT}.",
    )
    return parser.parse_args()


def normalize_source(raw: str) -> NormalizedSource:
    raw = raw.strip()
    if not raw:
        raise ValueError("source is empty")

    if raw.startswith("http://") or raw.startswith("https://"):
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
        query = parsed.query

        if host == "open.chanjet.com":
            prefix = "/docs/file/apiFile"
            if not parsed.path.startswith(prefix):
                raise ValueError(
                    "Unsupported open.chanjet.com path. Expected "
                    "/docs/file/apiFile[/<slug>]."
                )
            slug = parsed.path[len(prefix) :].strip("/")
            slug = normalize_slug(slug)
            api_url = build_details_url(slug, query=query) if slug else None
            return NormalizedSource(
                input_value=raw,
                slug=slug,
                path_parts=split_slug(slug),
                page_url=raw,
                api_url=api_url,
            )

        if host == "openapi.chanjet.com":
            prefix = "/developer/api/doc-center/details/"
            if not parsed.path.startswith(prefix):
                raise ValueError(
                    "Unsupported openapi.chanjet.com path. Expected "
                    "/developer/api/doc-center/details/<slug>."
                )
            slug = normalize_slug(parsed.path[len(prefix) :])
            page_url = build_page_url(slug, query=query)
            api_parsed = parsed._replace(path=f"/developer/api/doc-center/details/{slug}")
            return NormalizedSource(
                input_value=raw,
                slug=slug,
                path_parts=split_slug(slug),
                page_url=page_url,
                api_url=urlunparse(api_parsed),
            )

        raise ValueError(
            "Unsupported host. Use open.chanjet.com, openapi.chanjet.com, or a bare slug."
        )

    slug = raw
    if raw.startswith("/docs/file/apiFile/"):
        slug = raw[len("/docs/file/apiFile/") :]
    elif raw == "/docs/file/apiFile":
        slug = ""
    elif raw.startswith("/developer/api/doc-center/details/"):
        slug = raw[len("/developer/api/doc-center/details/") :]
    slug = normalize_slug(slug)
    page_url = build_page_url(slug)
    api_url = build_details_url(slug) if slug else None
    return NormalizedSource(
        input_value=raw,
        slug=slug,
        path_parts=split_slug(slug),
        page_url=page_url,
        api_url=api_url,
    )


def strip_api_file_prefix(slug: str) -> str:
    slug = slug.strip("/")
    if slug.startswith("apiFile/"):
        return slug[len("apiFile/") :]
    return slug


def normalize_slug(slug: str) -> str:
    slug = slug.strip("/")
    if slug == "apiFile":
        return ""
    return strip_api_file_prefix(slug)


def split_slug(slug: str) -> list[str]:
    if not slug:
        return []
    return [part for part in slug.split("/") if part]


def build_page_url(slug: str, query: str = "") -> str:
    path = PAGE_ROOT_URL if not slug else f"{PAGE_ROOT_URL}/{slug}"
    return path if not query else f"{path}?{query}"


def build_details_url(slug: str, query: str = "") -> str:
    path = DOC_DETAILS_URL.format(slug=slug)
    return path if not query else f"{path}?{query}"


def fetch_raw_json(url: str, timeout: int) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "codex-tplus-api-docs/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} while fetching {url}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"Request failed for {url}: {exc.reason}") from exc

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Response from {url} was not valid JSON.") from exc

    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected top-level payload type from {url}.")
    return payload


def unwrap_value(payload: dict[str, Any], url: str) -> Any:
    if not payload.get("result"):
        error = payload.get("error") or {}
        code = error.get("code", "unknown")
        message = error.get("msg", "unknown error")
        raise RuntimeError(f"Endpoint returned {code} for {url}: {message}")
    return payload.get("value")


def fetch_value(url: str, timeout: int) -> Any:
    payload = fetch_raw_json(url, timeout)
    return unwrap_value(payload, url)


def fetch_document_payload(source: NormalizedSource, timeout: int) -> dict[str, Any]:
    if not source.api_url:
        raise RuntimeError("No document details URL is available for this source.")
    value = fetch_value(source.api_url, timeout)
    if not isinstance(value, dict):
        raise RuntimeError(f"Document payload from {source.api_url} was not an object.")
    return value


def fetch_product_directory(timeout: int) -> list[dict[str, Any]]:
    value = fetch_value(DIRECTORY_ROOT_URL, timeout)
    if not isinstance(value, list):
        raise RuntimeError("Product directory payload was not a list.")
    return value


def fetch_product_tree(product_code: str, timeout: int) -> dict[str, Any]:
    url = DIRECTORY_TREE_URL.format(product=product_code)
    value = fetch_value(url, timeout)
    if not isinstance(value, dict):
        raise RuntimeError(f"Product tree payload from {url} was not an object.")
    return value


def html_fragment_to_text(fragment: str | None) -> str:
    if not fragment:
        return ""
    parser = HtmlTextExtractor()
    parser.feed(fragment)
    parser.close()
    text = parser.get_text()
    text = text.replace("\xa0", " ")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_article(item: dict[str, Any]) -> dict[str, Any]:
    body_html = item.get("body") or ""
    return {
        "name": item.get("moduleName") or "",
        "source": item.get("source") or "",
        "url": item.get("url") or "",
        "body_html": body_html,
        "body_text": html_fragment_to_text(body_html),
    }


def normalize_field(field: dict[str, Any]) -> dict[str, Any]:
    children = field.get("childList") or []
    return {
        "group": field.get("group") or "",
        "type": field.get("type") or "",
        "required": not bool(field.get("optional", False)),
        "field": field.get("field") or "",
        "description_html": field.get("description") or "",
        "description_text": html_fragment_to_text(field.get("description") or ""),
        "data_level": field.get("dataLevel") or "",
        "default_value": field.get("defaultValue"),
        "allowed_values": field.get("allowedValues"),
        "children": [normalize_field(child) for child in children],
    }


def normalize_examples(examples: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for example in examples or []:
        normalized.append(
            {
                "title": example.get("title") or "",
                "content": example.get("content") or "",
                "type": example.get("type") or "",
            }
        )
    return normalized


def normalize_api(item: dict[str, Any], include_openapi: bool) -> dict[str, Any]:
    parameter = item.get("parameter") or {}
    success = item.get("success") or {}
    api: dict[str, Any] = {
        "name": item.get("interfaceName") or "",
        "status": item.get("interfaceStatus") or "",
        "request_path": item.get("requestPath") or "",
        "request_http_method": item.get("requestHttpMethod") or "",
        "description_html": item.get("description") or "",
        "description_text": html_fragment_to_text(item.get("description") or ""),
        "permissions_type": item.get("permissionsType") or "",
        "api_id": item.get("apiId"),
        "product_code": item.get("productCode") or "",
        "parameters": {
            "body_type": parameter.get("bodyType"),
            "fields": {
                key: [normalize_field(field) for field in value or []]
                for key, value in (parameter.get("fields") or {}).items()
            },
            "examples": normalize_examples(parameter.get("examples")),
        },
        "success": {
            "body_type": success.get("bodyType"),
            "fields": {
                key: [normalize_field(field) for field in value or []]
                for key, value in (success.get("fields") or {}).items()
            },
            "examples": normalize_examples(success.get("examples")),
        },
        "error_codes": [
            {
                "code": code.get("code") or "",
                "description": code.get("description") or "",
            }
            for code in item.get("errorCodeList") or []
        ],
    }

    if include_openapi:
        raw_openapi = item.get("openApiJson") or ""
        if raw_openapi:
            try:
                api["openapi"] = json.loads(raw_openapi)
            except json.JSONDecodeError:
                api["openapi"] = raw_openapi
    return api


def count_leaf_nodes(nodes: list[dict[str, Any]]) -> int:
    total = 0
    for node in nodes:
        children = node.get("children") or []
        if children:
            total += count_leaf_nodes(children)
        else:
            total += 1
    return total


def normalize_tree_node(
    node: dict[str, Any],
    product_code: str,
    ancestors: list[str],
    recursive: bool,
) -> dict[str, Any]:
    path_parts = ancestors + [node.get("moduleCode") or ""]
    path = "/".join(path_parts)
    children = node.get("children") or []
    normalized_children = [
        normalize_tree_node(child, product_code, path_parts, recursive)
        for child in children
    ] if recursive else []
    return {
        "module_code": node.get("moduleCode") or "",
        "module_name": node.get("moduleName") or "",
        "module_id": node.get("moduleId"),
        "parent_module_code": node.get("parentModuleCode") or "",
        "weight": node.get("weight"),
        "path": path,
        "page_url": build_page_url(path),
        "detail_api_url": build_details_url(path) if not children else None,
        "is_leaf": not children,
        "child_count": len(children),
        "leaf_count": 1 if not children else count_leaf_nodes(children),
        "children": normalized_children,
    }


def shallow_tree_node(node: dict[str, Any], product_code: str, ancestors: list[str]) -> dict[str, Any]:
    return normalize_tree_node(node, product_code, ancestors, recursive=False)


def flatten_leaf_nodes(
    nodes: list[dict[str, Any]],
    product_code: str,
    ancestors: list[str],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for node in nodes:
        children = node.get("children") or []
        if children:
            items.extend(
                flatten_leaf_nodes(children, product_code, ancestors + [node.get("moduleCode") or ""])
            )
        else:
            items.append(shallow_tree_node(node, product_code, ancestors))
    return items


def find_tree_node(nodes: list[dict[str, Any]], codes: list[str]) -> dict[str, Any] | None:
    current_nodes = nodes
    current: dict[str, Any] | None = None
    for code in codes:
        current = next(
            (node for node in current_nodes if node.get("moduleCode") == code),
            None,
        )
        if current is None:
            return None
        current_nodes = current.get("children") or []
    return current


def normalize_directory_root(source: NormalizedSource, products: list[dict[str, Any]]) -> dict[str, Any]:
    items = [
        {
            "code": item.get("code") or "",
            "name": item.get("name") or "",
            "page_url": build_page_url(item.get("code") or ""),
            "tree_api_url": DIRECTORY_TREE_URL.format(product=item.get("code") or ""),
        }
        for item in products
    ]
    return {
        "kind": "directory",
        "source_input": source.input_value,
        "page_url": source.page_url,
        "api_url": DIRECTORY_ROOT_URL,
        "slug": source.slug,
        "path_parts": source.path_parts,
        "directory_type": "products",
        "product_count": len(items),
        "products": items,
    }


def normalize_directory_payload(
    source: NormalizedSource,
    tree: dict[str, Any],
    recursive: bool,
    leaves_only: bool,
) -> dict[str, Any]:
    product_code = tree.get("productCode") or ""
    product_name = tree.get("productName") or ""
    tree_url = DIRECTORY_TREE_URL.format(product=product_code)
    root_children = tree.get("children") or []
    sub_path = source.path_parts[1:]
    selected_type = "product"
    selected_name = product_name
    selected_code = product_code
    selected_path = product_code
    selected_children = root_children
    ancestors = [product_code]

    if sub_path:
        matched = find_tree_node(root_children, sub_path)
        if matched is None:
            raise RuntimeError(
                f"Module path '{'/'.join(source.path_parts)}' was not found in product '{product_code}'."
            )
        selected_type = "module"
        selected_name = matched.get("moduleName") or ""
        selected_code = matched.get("moduleCode") or ""
        selected_path = "/".join([product_code] + sub_path)
        selected_children = matched.get("children") or []
        ancestors = [product_code] + sub_path

    if leaves_only:
        items = flatten_leaf_nodes(selected_children, product_code, ancestors)
    elif recursive:
        items = [
            normalize_tree_node(child, product_code, ancestors, recursive=True)
            for child in selected_children
        ]
    else:
        items = [
            shallow_tree_node(child, product_code, ancestors)
            for child in selected_children
        ]

    return {
        "kind": "directory",
        "source_input": source.input_value,
        "page_url": source.page_url,
        "api_url": tree_url,
        "slug": source.slug,
        "path_parts": source.path_parts,
        "directory_type": selected_type,
        "product_code": product_code,
        "product_name": product_name,
        "selected": {
            "code": selected_code,
            "name": selected_name,
            "path": selected_path,
            "page_url": build_page_url(selected_path),
            "child_count": len(selected_children),
            "leaf_count": count_leaf_nodes(selected_children) if selected_children else 0,
        },
        "recursive": recursive,
        "leaves_only": leaves_only,
        "item_count": len(items),
        "items": items,
    }


def normalize_payload(
    source: NormalizedSource,
    payload: dict[str, Any],
    include_openapi: bool,
) -> dict[str, Any]:
    articles = [normalize_article(item) for item in payload.get("contentForModuleDtoList") or []]
    apis = [
        normalize_api(item, include_openapi)
        for item in payload.get("documentApiInfoList") or []
    ]
    return {
        "kind": "document",
        "source_input": source.input_value,
        "page_url": source.page_url,
        "api_url": source.api_url,
        "slug": source.slug,
        "path_parts": source.path_parts,
        "module_path": payload.get("modulePath") or "",
        "article_count": len(articles),
        "api_count": len(apis),
        "articles": articles,
        "apis": apis,
    }


def count_leaf_nodes(nodes: list[dict[str, Any]]) -> int:
    total = 0
    for node in nodes:
        children = node.get("children") or []
        if children:
            total += count_leaf_nodes(children)
        else:
            total += 1
    return total


def normalize_product_item(item: dict[str, Any]) -> dict[str, Any]:
    code = item.get("code") or ""
    return {
        "code": code,
        "name": item.get("name") or "",
        "page_url": build_page_url(code),
        "tree_api_url": DIRECTORY_TREE_URL.format(product=code),
    }


def normalize_tree_node(
    node: dict[str, Any],
    product_code: str,
    ancestors: list[str] | None = None,
    recursive: bool = True,
) -> dict[str, Any]:
    ancestors = ancestors or []
    module_code = node.get("moduleCode") or ""
    path_parts = [product_code, *ancestors, module_code]
    path = "/".join(path_parts)
    raw_children = node.get("children") or []
    children = [
        normalize_tree_node(
            child,
            product_code=product_code,
            ancestors=[*ancestors, module_code],
            recursive=recursive,
        )
        for child in raw_children
    ]
    item = {
        "module_code": module_code,
        "module_name": node.get("moduleName") or "",
        "module_id": node.get("moduleId"),
        "parent_module_code": node.get("parentModuleCode") or "",
        "weight": node.get("weight"),
        "path": path,
        "page_url": build_page_url(path),
        "detail_api_url": build_details_url(path) if not raw_children else None,
        "is_leaf": not raw_children,
        "child_count": len(raw_children),
        "leaf_count": count_leaf_nodes(raw_children) if raw_children else 1,
    }
    if recursive:
        item["children"] = children
    else:
        item["children"] = []
    return item


def flatten_leaf_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    leaves: list[dict[str, Any]] = []
    for node in nodes:
        children = node.get("children") or []
        if children:
            leaves.extend(flatten_leaf_nodes(children))
        else:
            leaves.append(node)
    return leaves


def find_tree_node(tree_children: list[dict[str, Any]], codes: list[str]) -> dict[str, Any] | None:
    current_children = tree_children
    current_node: dict[str, Any] | None = None
    for code in codes:
        current_node = next(
            (item for item in current_children if (item.get("moduleCode") or "") == code),
            None,
        )
        if current_node is None:
            return None
        current_children = current_node.get("children") or []
    return current_node


def normalize_directory_payload(
    source: NormalizedSource,
    timeout: int,
    recursive: bool,
    leaves_only: bool,
) -> dict[str, Any]:
    if not source.path_parts:
        products = [normalize_product_item(item) for item in fetch_product_directory(timeout)]
        return {
            "kind": "directory",
            "directory_type": "products",
            "source_input": source.input_value,
            "page_url": source.page_url,
            "api_url": DIRECTORY_ROOT_URL,
            "slug": source.slug,
            "path_parts": source.path_parts,
            "product_count": len(products),
            "products": products,
            "recursive": False,
            "leaves_only": False,
        }

    product_code = source.path_parts[0]
    tree = fetch_product_tree(product_code, timeout)
    tree_children = tree.get("children") or []
    selected_codes = source.path_parts[1:]
    selected_kind = "product"
    selected_name = tree.get("productName") or product_code
    selected_path = product_code
    selected_page_url = build_page_url(product_code)
    selected_node: dict[str, Any] | None = None
    selected_children_raw = tree_children

    if selected_codes:
        selected_node = find_tree_node(tree_children, selected_codes)
        if selected_node is None:
            raise RuntimeError(
                f"Could not find module path '{'/'.join(source.path_parts)}' "
                f"under product '{product_code}'."
            )
        selected_kind = "module"
        selected_name = selected_node.get("moduleName") or selected_codes[-1]
        selected_path = "/".join(source.path_parts)
        selected_page_url = build_page_url(selected_path)
        selected_children_raw = selected_node.get("children") or []

    full_children = [
        normalize_tree_node(
            child,
            product_code=product_code,
            ancestors=selected_codes,
            recursive=True,
        )
        for child in selected_children_raw
    ]

    if leaves_only:
        directory_items = flatten_leaf_nodes(full_children)
    elif recursive:
        directory_items = full_children
    else:
        directory_items = [
            normalize_tree_node(child, product_code=product_code, ancestors=selected_codes, recursive=False)
            for child in selected_children_raw
        ]

    return {
        "kind": "directory",
        "directory_type": selected_kind,
        "source_input": source.input_value,
        "page_url": source.page_url or selected_page_url,
        "api_url": DIRECTORY_TREE_URL.format(product=product_code),
        "slug": source.slug,
        "path_parts": source.path_parts,
        "product_code": product_code,
        "product_name": tree.get("productName") or product_code,
        "selected": {
            "kind": selected_kind,
            "name": selected_name,
            "path": selected_path,
            "page_url": selected_page_url,
            "child_count": len(selected_children_raw),
            "leaf_count": count_leaf_nodes(selected_children_raw) if selected_children_raw else 0,
        },
        "child_count": len(directory_items),
        "children": directory_items,
        "recursive": recursive,
        "leaves_only": leaves_only,
    }


def render_field_lines(fields: list[dict[str, Any]], indent: int = 0) -> list[str]:
    lines: list[str] = []
    prefix = "  " * indent
    for field in fields:
        required = "required" if field["required"] else "optional"
        group = f" [{field['group']}]" if field["group"] else ""
        line = (
            f"{prefix}- `{field['field']}` ({field['type']}, {required}){group}"
        )
        if field["description_text"]:
            line += f": {field['description_text']}"
        lines.append(line)
        if field["children"]:
            lines.extend(render_field_lines(field["children"], indent + 1))
    return lines


def render_examples_markdown(examples: list[dict[str, Any]], heading: str) -> list[str]:
    lines: list[str] = []
    if not examples:
        return lines
    lines.append(heading)
    lines.append("")
    for example in examples:
        title = example["title"] or "Example"
        language = "json" if (example["type"] or "").lower() == "json" else ""
        lines.append(f"#### {title}")
        lines.append("")
        lines.append(f"```{language}")
        lines.append(example["content"].strip())
        lines.append("```")
        lines.append("")
    return lines


def render_directory_tree_markdown(items: list[dict[str, Any]], indent: int = 0) -> list[str]:
    lines: list[str] = []
    prefix = "  " * indent + "- "
    for item in items:
        path = item.get("path") or item.get("module_code") or ""
        name = item.get("module_name") or item.get("name") or ""
        if item.get("is_leaf"):
            lines.append(f"{prefix}`{path}`: {name}")
        else:
            lines.append(
                f"{prefix}`{path}`: {name} "
                f"(children: {item.get('child_count', 0)}, leaves: {item.get('leaf_count', 0)})"
            )
        children = item.get("children") or []
        if children:
            lines.extend(render_directory_tree_markdown(children, indent + 1))
    return lines


def render_directory_markdown(data: dict[str, Any]) -> str:
    lines = [
        "# API Directory",
        "",
        f"- Source input: `{data['source_input']}`",
        f"- Page URL: `{data['page_url'] or ''}`",
        f"- API URL: `{data['api_url']}`",
        f"- Directory type: `{data['directory_type']}`",
        "",
    ]

    if data["directory_type"] == "products":
        lines.append("## Products")
        lines.append("")
        for item in data["products"]:
            lines.append(f"- `{item['code']}`: {item['name']}")
        lines.append("")
        return "\n".join(lines).strip() + "\n"

    selected = data["selected"]
    lines.extend(
        [
            f"- Product: `{data['product_code']}` ({data['product_name']})",
            f"- Selected path: `{selected['path']}`",
            f"- Selected name: {selected['name']}",
            f"- Child count: {selected['child_count']}",
            f"- Leaf count: {selected['leaf_count']}",
            f"- Recursive: {data['recursive']}",
            f"- Leaves only: {data['leaves_only']}",
            "",
        ]
    )

    heading = "## Leaf Documents" if data["leaves_only"] else "## Directory Contents"
    lines.append(heading)
    lines.append("")
    lines.extend(render_directory_tree_markdown(data["children"]))
    lines.append("")
    return "\n".join(lines).strip() + "\n"


def render_markdown(data: dict[str, Any]) -> str:
    if data.get("kind") == "directory":
        return render_directory_markdown(data)

    title = data["module_path"] or data["slug"]
    lines = [
        f"# {title}",
        "",
        f"- Source input: `{data['source_input']}`",
        f"- Page URL: `{data['page_url'] or ''}`",
        f"- API URL: `{data['api_url']}`",
        f"- Articles: {data['article_count']}",
        f"- APIs: {data['api_count']}",
        "",
    ]

    if data["articles"]:
        lines.append("## Articles")
        lines.append("")
        for article in data["articles"]:
            heading = article["name"] or "Untitled article"
            lines.append(f"### {heading}")
            lines.append("")
            if article["body_text"]:
                lines.append(article["body_text"])
                lines.append("")

    if data["apis"]:
        lines.append("## APIs")
        lines.append("")
        for api in data["apis"]:
            lines.append(f"### {api['name']}")
            lines.append("")
            if api["request_http_method"] or api["request_path"]:
                lines.append(
                    f"- Endpoint: `{api['request_http_method']} {api['request_path']}`".strip()
                )
            if api["status"]:
                lines.append(f"- Status: {api['status']}")
            if api["permissions_type"]:
                lines.append(f"- Permissions: {api['permissions_type']}")
            if api["description_text"]:
                lines.append("")
                lines.append(api["description_text"])
            lines.append("")

            parameter_fields = api["parameters"]["fields"]
            for group_name in HEADER_ORDER:
                group_fields = [
                    field
                    for field in parameter_fields.get("Parameter", [])
                    if field["group"] == group_name
                ]
                if group_fields:
                    lines.append(f"#### {group_name} Parameters")
                    lines.append("")
                    lines.extend(render_field_lines(group_fields))
                    lines.append("")

            other_parameter_groups = [
                key for key in parameter_fields.keys() if key != "Parameter"
            ]
            for group_name in other_parameter_groups:
                group_fields = parameter_fields.get(group_name) or []
                if group_fields:
                    lines.append(f"#### {group_name}")
                    lines.append("")
                    lines.extend(render_field_lines(group_fields))
                    lines.append("")

            success_fields = api["success"]["fields"]
            for group_name, fields in success_fields.items():
                if not fields:
                    continue
                lines.append(f"#### {group_name}")
                lines.append("")
                lines.extend(render_field_lines(fields))
                lines.append("")

            if api["error_codes"]:
                lines.append("#### Error Codes")
                lines.append("")
                for item in api["error_codes"]:
                    lines.append(f"- `{item['code']}`: {item['description']}")
                lines.append("")

            lines.extend(render_examples_markdown(api["parameters"]["examples"], "#### Request Examples"))
            lines.extend(render_examples_markdown(api["success"]["examples"], "#### Response Examples"))

            if "openapi" in api:
                lines.append("#### OpenAPI")
                lines.append("")
                lines.append("```json")
                lines.append(json.dumps(api["openapi"], ensure_ascii=False, indent=2))
                lines.append("```")
                lines.append("")

    return "\n".join(lines).strip() + "\n"


def render_directory_text(data: dict[str, Any]) -> str:
    lines = [
        f"Directory type: {data['directory_type']}",
        f"Source input: {data['source_input']}",
        f"Page URL: {data['page_url'] or ''}",
        f"API URL: {data['api_url']}",
        "",
    ]

    if data["directory_type"] == "products":
        lines.append("Products:")
        for item in data["products"]:
            lines.append(f"- {item['code']}: {item['name']}")
        lines.append("")
        return "\n".join(lines).strip() + "\n"

    selected = data["selected"]
    lines.extend(
        [
            f"Product: {data['product_code']} ({data['product_name']})",
            f"Selected path: {selected['path']}",
            f"Selected name: {selected['name']}",
            f"Child count: {selected['child_count']}",
            f"Leaf count: {selected['leaf_count']}",
            f"Recursive: {data['recursive']}",
            f"Leaves only: {data['leaves_only']}",
            "",
            "Items:",
        ]
    )
    lines.extend(render_directory_tree_markdown(data["children"]))
    lines.append("")
    return "\n".join(lines).strip() + "\n"


def render_text(data: dict[str, Any]) -> str:
    if data.get("kind") == "directory":
        return render_directory_text(data)

    lines = [
        f"Module: {data['module_path'] or data['slug']}",
        f"Source input: {data['source_input']}",
        f"Page URL: {data['page_url'] or ''}",
        f"API URL: {data['api_url']}",
        f"Articles: {data['article_count']}",
        f"APIs: {data['api_count']}",
        "",
    ]

    for article in data["articles"]:
        lines.append(f"[Article] {article['name'] or 'Untitled article'}")
        if article["body_text"]:
            lines.append(article["body_text"])
        lines.append("")

    for api in data["apis"]:
        lines.append(f"[API] {api['name']}")
        if api["request_http_method"] or api["request_path"]:
            lines.append(f"Endpoint: {api['request_http_method']} {api['request_path']}".strip())
        if api["description_text"]:
            lines.append(api["description_text"])
        if api["error_codes"]:
            lines.append("Error codes:")
            for item in api["error_codes"]:
                lines.append(f"  - {item['code']}: {item['description']}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def render_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def write_output(content: str, output_path: str | None) -> None:
    if not output_path:
        sys.stdout.write(content)
        return
    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> int:
    args = parse_args()
    try:
        source = normalize_source(args.source)
        if len(source.path_parts) < 3:
            normalized = normalize_directory_payload(
                source,
                timeout=args.timeout,
                recursive=args.recursive or args.leaves_only,
                leaves_only=args.leaves_only,
            )
        else:
            payload = fetch_document_payload(source, timeout=args.timeout)
            normalized = normalize_payload(
                source,
                payload,
                include_openapi=args.include_openapi,
            )

        if args.format == "json":
            rendered = render_json(normalized)
        elif args.format == "text":
            rendered = render_text(normalized)
        else:
            rendered = render_markdown(normalized)

        write_output(rendered, args.output)
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # pylint: disable=broad-except
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
