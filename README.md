# Loans & Real Estate Platform

A production full-stack monorepo for a web-only Loans & Real Estate platform. It supports two segregated business lines (Loans, Real Estate) in one ecosystem, utilizing a single Postgres DB with Row-Level Security.

## Stack
- **Backend:** Python, FastAPI, SQLAlchemy 2, PostgreSQL
- **Frontend:** Next.js App Router, TypeScript, shadcn/ui, Tailwind CSS

## MCP servers (Claude Code)
`.mcp.json` is gitignored so each developer keeps their own. To start from the
shared baseline:

```bash
cp mcp.example.json .mcp.json
```

| Server | Purpose |
| --- | --- |
| `playwright` | Drives the web app (`http://localhost:3001` under docker compose) in a headless browser; artifacts go to the ignored `.playwright-mcp/`. |
| `postgres` | Read-only (`--access-mode=restricted`) queries against the dev Postgres on `localhost:5432`. Override with `MCP_DATABASE_URI`; never point it at production. |
| `next-devtools` | Next.js runtime errors, routes and docs from the running dev server. |

Requires Node (`npx`) and uv (`uvx`). Run `claude mcp list` to confirm the servers connect.
