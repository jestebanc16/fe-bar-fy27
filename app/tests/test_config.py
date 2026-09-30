from server.config import pick_acted_by
from server.db import resolve_conn_params


def test_pick_acted_by_prefers_forwarded_email():
    hdrs = {"X-Forwarded-Email": "rev@corp.com"}
    assert pick_acted_by(hdrs, is_app=True, cli_user="ignored") == "rev@corp.com"


def test_pick_acted_by_falls_back_to_preferred_username():
    hdrs = {"X-Forwarded-Preferred-Username": "rev.manager"}
    assert pick_acted_by(hdrs, is_app=True, cli_user=None) == "rev.manager"


def test_pick_acted_by_local_uses_cli_user():
    assert pick_acted_by({}, is_app=False, cli_user="me@corp.com") == "me@corp.com"


def test_pick_acted_by_final_fallback():
    assert pick_acted_by({}, is_app=False, cli_user=None) == "local-dev"
    assert pick_acted_by({}, is_app=True, cli_user=None) == "local-dev"


def test_resolve_conn_params_uses_injected_pghost():
    env = {"PGHOST": "injected-host", "PGUSER": "sp-id", "PGDATABASE": "hotel",
           "DATABRICKS_INSTANCE_NAME": "hotel-lakebase"}
    params = resolve_conn_params(
        env, dns_lookup=lambda n: "should-not-be-called", user_lookup=lambda: "cli-user",
    )
    assert params["host"] == "injected-host"
    assert params["user"] == "sp-id"
    assert params["dbname"] == "hotel"
    assert params["sslmode"] == "require"
    assert params["instance"] == "hotel-lakebase"


def test_resolve_conn_params_falls_back_to_dns_and_cli_user():
    env = {"DATABRICKS_INSTANCE_NAME": "hotel-lakebase"}  # no PGHOST/PGUSER (local)
    params = resolve_conn_params(
        env, dns_lookup=lambda n: f"dns-of-{n}", user_lookup=lambda: "me@corp.com",
    )
    assert params["host"] == "dns-of-hotel-lakebase"
    assert params["user"] == "me@corp.com"
    assert params["dbname"] == "hotel"    # default
    assert params["port"] == "5432"       # default
