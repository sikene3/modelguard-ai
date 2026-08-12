# Architecture export

The shareable diagram is generated from [`architecture.mmd`](architecture.mmd). Do not edit the PNG
or SVG by hand; change the Mermaid source and regenerate both outputs.

## Repository-local export

The checked-in exporter validates the restricted Mermaid node/edge syntax used by this diagram and
renders both formats without network access. It uses the already locked development dependency on
Pillow:

```bash
UV_CACHE_DIR=.cache/uv uv run --frozen --no-sync \
  python scripts/export_portfolio_architecture.py
```

## Official Mermaid CLI alternative

Requirements: Node.js 20 or newer, npm/npx, network access to install the pinned package, and a
Chromium-compatible environment. From the repository root:

```bash
npx --yes @mermaid-js/mermaid-cli@11.15.0 \
  -i portfolio/architecture.mmd \
  -o portfolio/assets/modelguard-architecture.svg \
  -b white

npx --yes @mermaid-js/mermaid-cli@11.15.0 \
  -i portfolio/architecture.mmd \
  -o portfolio/assets/modelguard-architecture.png \
  -b white -w 2400 -H 1600
```

`@mermaid-js/mermaid-cli` is pinned here only for deterministic portfolio export; it is not a
project runtime dependency. The repository-local output and Mermaid CLI output may differ in visual
layout while preserving the same nodes and edges. Review the rendered labels and `git diff` before
publishing. The official CLI accepts Mermaid input and emits SVG or PNG; its upstream usage is
documented at <https://github.com/mermaid-js/mermaid-cli>.

## Verification

```bash
file portfolio/assets/modelguard-architecture.svg \
  portfolio/assets/modelguard-architecture.png
sha256sum portfolio/architecture.mmd \
  portfolio/assets/modelguard-architecture.svg \
  portfolio/assets/modelguard-architecture.png
```

The diagram contains generic AWS service names only. It must not include an account ID, repository
secret, endpoint, IP address, notification address, resource ARN, or customer data.
