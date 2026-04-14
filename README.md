# chanjet-skill

`chanjet-skill` 是一个面向畅捷通开放平台文档抓取与整理的 Codex 技能仓库，当前主要提供 `T+ API Docs` 技能。

这个技能的目标是：

- 处理 `open.chanjet.com/docs/file/apiFile/...` 文档页
- 在运行时解析产品目录和模块树，获取最新文档结构
- 抓取叶子文档的正文、接口定义、参数、错误码和 OpenAPI 内容
- 支持把目录页展开为模块列表或叶子文档列表

## 仓库结构

```text
.
├── README.md
├── SKILL.md
├── agents/
│   └── openai.yaml
├── references/
│   ├── token-auth-flow.md
│   └── url-patterns.md
└── scripts/
    └── fetch_tplus_doc.py
```

## 核心能力

- 目录根解析：获取最新产品目录
- 产品目录解析：如 `tcloud`、`zplus`、`finance`、`accounting`、`common`、`stapi`
- 模块目录解析：如 `tcloud/tjrzy`
- 叶子文档抓取：如 `tcloud/tjrzy/openToken`
- 输出格式：`markdown`、`text`、`json`
- 目录展开选项：`--recursive`、`--leaves-only`
- 合同细节提取：`--include-openapi`

## 快速使用

```bash
export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
export TPLUS_DOC="$CODEX_HOME/skills/tplus-api-docs/scripts/fetch_tplus_doc.py"
```

抓取叶子文档：

```bash
python3 "$TPLUS_DOC" \
  "https://open.chanjet.com/docs/file/apiFile/tcloud/tjrzy/openToken" \
  --format markdown
```

查看产品目录：

```bash
python3 "$TPLUS_DOC" \
  "https://open.chanjet.com/docs/file/apiFile/tcloud" \
  --format text
```

展开模块目录下的叶子文档：

```bash
python3 "$TPLUS_DOC" \
  "https://open.chanjet.com/docs/file/apiFile/tcloud/tjrzy" \
  --format text \
  --leaves-only
```

导出结构化 JSON：

```bash
python3 "$TPLUS_DOC" \
  "common/base_api/oauth2" \
  --format json \
  --include-openapi
```

## 工作方式

对于目录页，脚本会先查询最新目录结构：

- `https://open.chanjet.com/api/param/default/apiFile`
- `https://open.chanjet.com/api/doc-center/modulesNameByCode/<product>`

对于叶子文档页，脚本会抓取：

- `https://openapi.chanjet.com/developer/api/doc-center/details/<slug>`

也就是说，这个技能不是把目录结构写死在本地，而是运行时动态解析当前线上文档目录，再定位到最新内容。

## 相关文件

- 技能说明：[`SKILL.md`](./SKILL.md)
- URL 与返回结构参考：[`references/url-patterns.md`](./references/url-patterns.md)
- Token 与授权链路参考：[`references/token-auth-flow.md`](./references/token-auth-flow.md)
