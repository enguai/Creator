# Creator Website Agent Guide

## Project purpose

Official website for the Creator live-commerce department, focused on three skincare products: red camellia soft mask, polishing mask, and ice agate eye mask.

## Stack and layout

- `creator_project/`: Django 6 project configuration.
- `core/`: Django app for administrative data and user profiles.
- `frontend/`: Vue 3 + Vite public website.
- `.venv/`: local Python virtual environment (never commit it).
- `db.sqlite3`: local development database (never commit it).

## Local commands (PowerShell)

PowerShell script execution may be restricted on this machine. Prefer direct executables:

```powershell
.\.venv\Scripts\python.exe manage.py runserver
cd frontend
npm.cmd install
npm.cmd run dev
npm.cmd run build
```

## Development rules

- Keep the public website entirely inside `frontend/`; do not add Django templates for it.
- Maintain five independent Vue routes: `/`, `/products`, `/features`, `/brand`, and `/contact`.
- Preserve the quiet luxury visual language: editorial typography, warm neutrals, restrained burgundy accents, real product photography, and minimal motion.
- Reuse shared layout, navigation, footer, and product data instead of duplicating markup.
- Keep pages responsive and keyboard accessible; include visible focus states, meaningful alt text, and semantic landmarks.
- Do not commit credentials, `.venv`, `node_modules`, `dist`, or local databases.

## Verification

Before handing off frontend changes:

```powershell
cd frontend
npm.cmd run build
```

For Django changes:

```powershell
.\.venv\Scripts\python.exe manage.py check
```

Visually verify all five routes at desktop and mobile widths, including navigation active states and the mobile menu.
