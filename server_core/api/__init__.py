"""The REST API under /api/ (docs/contracts/ingest-api.md).

Two kinds of caller, and every view accepts exactly one of them:

- Plugin containers send their data and their board's reports with
  `Authorization: Plugin <token>` (authentication.py). The token decides the
  instance, and the instance decides the board, so no URL carries a plugin or
  device id a plugin could use to speak for someone else.
- The person using PluTO, through the front end, with `Authorization: Bearer
  <jwt>` from /api/auth/token. That is the project-wide default (settings.py),
  so the front-end views declare nothing.
"""
