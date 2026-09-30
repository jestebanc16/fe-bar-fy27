"""Dual-mode auth + identity helpers.

Detects Databricks Apps (service-principal creds) vs local (CLI profile), and
derives `acted_by` for write-back attribution from the forwarded end-user
identity headers. No on-behalf-of DB auth — the app SP owns the connection.
"""
from __future__ import annotations

import os
from typing import Mapping, Optional

from databricks.sdk import WorkspaceClient

IS_DATABRICKS_APP = bool(os.environ.get("DATABRICKS_APP_NAME"))


def get_workspace_client() -> WorkspaceClient:
    if IS_DATABRICKS_APP:
        return WorkspaceClient()  # auto-injected service-principal creds
    return WorkspaceClient(profile=os.environ.get("DATABRICKS_PROFILE", "DEFAULT"))


def pick_acted_by(headers: Mapping[str, str], *, is_app: bool,
                  cli_user: Optional[str]) -> str:
    """Pure identity resolution (unit-tested).

    Priority: forwarded email -> forwarded preferred-username -> CLI user
    (local only) -> "local-dev".
    """
    email = headers.get("X-Forwarded-Email") or headers.get("X-Forwarded-Preferred-Username")
    if email:
        return email
    if not is_app and cli_user:
        return cli_user
    return "local-dev"


def _cli_user() -> Optional[str]:
    try:
        return get_workspace_client().current_user.me().user_name
    except Exception:
        return None


def resolve_acted_by(headers: Mapping[str, str]) -> str:
    cli_user = None if IS_DATABRICKS_APP else _cli_user()
    return pick_acted_by(headers, is_app=IS_DATABRICKS_APP, cli_user=cli_user)
