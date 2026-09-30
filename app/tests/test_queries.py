import pytest
from server import queries as q


def test_action_type_validation():
    assert q.validate_action_type("reconfirmed") is True
    assert q.validate_action_type("released") is True
    assert q.validate_action_type("bogus") is False
    assert set(q.VALID_ACTION_TYPES) == {
        "reconfirmed", "deposit_requested", "overbooked_backup", "released", "note",
    }


def test_clamp_limit_bounds():
    assert q.clamp_limit(None) == q.DEFAULT_LIMIT
    assert q.clamp_limit("10") == 10
    assert q.clamp_limit(0) == 1
    assert q.clamp_limit(9999) == q.MAX_LIMIT
    assert q.clamp_limit("junk") == q.DEFAULT_LIMIT


def test_clamp_offset_bounds():
    assert q.clamp_offset(None) == 0
    assert q.clamp_offset("40") == 40
    assert q.clamp_offset(-5) == 0
    assert q.clamp_offset("junk") == 0


def test_build_filters_empty():
    where, params = q.build_reservation_filters()
    assert where == ""
    assert params == []


def test_build_filters_all():
    where, params = q.build_reservation_filters(
        hotel="City Hotel", risk_band="high", market_segment="Online TA", min_lead_time=30,
    )
    assert where.startswith(" WHERE ")
    assert where.count("%s") == 4
    assert "hotel = %s" in where
    assert "risk_band = %s" in where
    assert "market_segment = %s" in where
    assert "lead_time >= %s" in where
    assert params == ["City Hotel", "high", "Online TA", 30]


def test_build_filters_rejects_bad_risk_band():
    with pytest.raises(ValueError):
        q.build_reservation_filters(risk_band="extreme")


def test_reservations_query_orders_and_pages():
    sql = q.reservations_query(" WHERE hotel = %s")
    assert q.SERVING_TABLE in sql
    assert "ORDER BY cancel_probability DESC" in sql
    assert "LIMIT %s OFFSET %s" in sql
    assert "WHERE hotel = %s" in sql


def test_count_query_uses_same_where():
    sql = q.count_query(" WHERE risk_band = %s")
    assert sql.strip().lower().startswith("select count(*)")
    assert q.SERVING_TABLE in sql
    assert "WHERE risk_band = %s" in sql


def test_detail_and_actions_queries():
    assert "WHERE reservation_id = %s" in q.detail_query()
    assert q.SERVING_TABLE in q.detail_query()
    pa = q.prior_actions_query()
    assert q.ACTION_TABLE in pa
    assert "ORDER BY acted_at DESC" in pa
    assert "WHERE reservation_id = %s" in pa


def test_insert_action_query_shape():
    ins = q.insert_action_query()
    assert q.ACTION_TABLE in ins
    assert "(reservation_id, action_type, note, acted_by)" in ins
    assert "VALUES (%s, %s, %s, %s)" in ins
    assert "RETURNING id, reservation_id, action_type, note, acted_by, acted_at" in ins


def test_kpi_query_has_filtered_counts():
    sql = q.kpi_query()
    assert "count(*)" in sql.lower()
    assert "filter (where risk_band='high')" in sql.lower()
    assert "avg(cancel_probability)" in sql.lower()
    assert q.SERVING_TABLE in sql
