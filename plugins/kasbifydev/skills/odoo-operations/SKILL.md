---
name: odoo-operations
description: Use KasbifyDev for Odoo 19+ inspection, project/task/CRM operations, schema discovery, troubleshooting, and safe record changes. Trigger when the user asks to inspect Odoo, find records, explain project state, create or edit Odoo records, diagnose Odoo API/model issues, or perform Odoo engineering operations through the connected KasbifyDev app.
---

# KasbifyDev Odoo Operations

Use the connected KasbifyDev app as the execution layer for Odoo work.

## Core workflow

1. Determine the Odoo model or business concept involved.
2. Discover the live schema or model metadata before constructing queries. Never invent field names.
3. Prefer read operations first when the user asks to inspect, diagnose, summarize, or clean up data.
4. Use the narrowest operation that satisfies the request. Avoid broad searches and bulk writes when a targeted query is possible.
5. For relational fields, resolve names to record IDs before writes rather than assuming IDs.
6. For state transitions, prefer the model's action/workflow method instead of directly writing a state field.
7. For destructive or high-impact changes, surface the exact affected records and respect the MCP confirmation gate. Never fabricate or bypass a confirmation token.
8. After a write, read back the changed records when practical and report what actually changed.

## Safety and precision

- Treat live Odoo schema and method discovery as authoritative.
- Do not guess field names, action names, record IDs, or company/project scope.
- Keep mutations scoped to records clearly identified by the user's request.
- If the server reports `pending_confirmation=true`, explain the proposed operation and wait for explicit approval before the confirmed re-call.
- Do not substitute browser automation when the connected app can perform the operation directly.
- Preserve existing data unless deletion or replacement is explicitly requested.

## Response style

For inspection tasks, summarize findings with important record names/IDs and any inconsistencies found.
For mutation tasks, state the records changed, operation performed, and verification result.
For failures, report the server error and the next concrete diagnostic step rather than guessing.
