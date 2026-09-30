"""Lakebase Postgres connection pool — classic GA Database Instance path.

Credentials come from w.database.generate_database_credential(instance_names=...)
(NOT the Autoscaling w.postgres/ENDPOINT_NAME pattern). Host/user use the
runtime-injected PGHOST/PGUSER when present (Approach A) and fall back to the
SDK read_write_dns + CLI user (Approach B). A fresh OAuth token is minted per
connection; max_lifetime recycles connections before the 1-hour token expiry.

IMPORTANT: importing this module does NO network I/O. The workspace client and
the pool are created lazily in open_pool() (called from the app lifespan), so
unit tests can import resolve_conn_params without credentials.
"""
from __future__ import annotations

import os
import uuid
from typing import Callable, Mapping, Optional

import psycopg
from psycopg_pool import ConnectionPool

from .config import get_workspace_client

INSTANCE_NAME = os.environ.get("DATABRICKS_INSTANCE_NAME", "hotel-lakebase")

_w = None            # lazy WorkspaceClient
pool: Optional[ConnectionPool] = None


def _client():
    global _w
    if _w is None:
        _w = get_workspace_client()
    return _w


def resolve_conn_params(env: Mapping[str, str], *,
                        dns_lookup: Callable[[str], str],
                        user_lookup: Callable[[], str]) -> dict:
    instance = env.get("DATABRICKS_INSTANCE_NAME", "hotel-lakebase")
    host = env.get("PGHOST") or dns_lookup(instance)      # A -> B fallback
    user = env.get("PGUSER") or user_lookup()             # injected SP id, else CLI user
    return {
        "host": host,
        "user": user,
        "port": env.get("PGPORT", "5432"),
        "dbname": env.get("PGDATABASE", "hotel"),
        "sslmode": env.get("PGSSLMODE", "require"),
        "instance": instance,
    }


def _dns_lookup(instance: str) -> str:
    return _client().database.get_database_instance(name=instance).read_write_dns


def _user_lookup() -> str:
    return _client().current_user.me().user_name


class OAuthConnection(psycopg.Connection):
    """Mint a fresh Lakebase OAuth token for every new/recycled connection."""

    @classmethod
    def connect(cls, conninfo="", **kwargs):
        cred = _client().database.generate_database_credential(
            request_id=str(uuid.uuid4()), instance_names=[INSTANCE_NAME],
        )
        kwargs["password"] = cred.token
        return super().connect(conninfo, **kwargs)


def open_pool() -> None:
    """Build + open the pool. Called once from the app lifespan (Task 3)."""
    global pool
    params = resolve_conn_params(
        os.environ, dns_lookup=_dns_lookup, user_lookup=_user_lookup,
    )
    pool = ConnectionPool(
        conninfo=(
            f"dbname={params['dbname']} user={params['user']} "
            f"host={params['host']} port={params['port']} sslmode={params['sslmode']}"
        ),
        connection_class=OAuthConnection,
        min_size=1,
        max_size=10,
        max_lifetime=2700,  # 45 min — recycle before the 1-hour token expiry
        open=False,
    )
    pool.open(wait=True, timeout=30.0)


def close_pool() -> None:
    if pool is not None:
        pool.close()


def get_pool() -> ConnectionPool:
    if pool is None:
        raise RuntimeError("connection pool is not open")
    return pool
