import pytest
import requests

from news_politica.sources.http import (
    USER_AGENT,
    Blocked,
    Disallowed,
    PoliteClient,
    TransientError,
)

from .conftest import FakeRaw

CHALLENGE = "<!DOCTYPE html><html><head><title>Just a moment...</title></head></html>"
NOTE = "https://www.example.com/politica/nota/"


def request_times(session, url):
    return [at for _, at, _ in session.requested(url)]


def test_disallowed_url_is_never_sent(client, session):
    with pytest.raises(Disallowed):
        client.get("https://www.example.com/pf/api/v3/content/")
    assert session.requested("https://www.example.com/pf/api/v3/content/") == []


def test_requests_to_one_host_are_spaced(client, session):
    session.routes.update({NOTE: FakeRaw(200, "a"), NOTE + "2": FakeRaw(200, "b")})
    client.get(NOTE)
    client.get(NOTE + "2")
    starts = [at for _, at, _ in session.calls]
    assert all(later - earlier >= 2 for earlier, later in zip(starts, starts[1:]))


def test_other_hosts_are_not_delayed(client, session):
    other = "https://www.other.com/politica/nota/"
    session.routes.update({NOTE: FakeRaw(200, "a"), other: FakeRaw(200, "b")})
    client.get(NOTE)
    first_note = request_times(session, NOTE)[0]
    client.get(other)
    # The other host waits for nothing but its own robots.txt.
    assert request_times(session, "https://www.other.com/robots.txt")[0] == first_note


def test_every_request_names_the_project(client, session):
    session.routes[NOTE] = FakeRaw(200, "a")
    client.get(NOTE)
    assert {agent for _, _, agent in session.calls} == {USER_AGENT}
    assert "github.com" in USER_AGENT


def test_recovers_after_a_503(client, session):
    session.routes[NOTE] = [FakeRaw(503), FakeRaw(200, "ok")]
    assert client.get(NOTE).status == 200
    assert len(session.requested(NOTE)) == 2


def test_gives_up_after_four_attempts(client, session):
    session.routes[NOTE] = FakeRaw(500)
    with pytest.raises(TransientError):
        client.get(NOTE)
    times = request_times(session, NOTE)
    assert len(times) == 4
    assert [round(b - a) for a, b in zip(times, times[1:])] == [2, 8, 32]


def test_network_errors_are_retried(client, session):
    session.routes[NOTE] = [requests.Timeout(), requests.ConnectionError(), FakeRaw(200, "ok")]
    assert client.get(NOTE).status == 200
    assert len(session.requested(NOTE)) == 3


def test_retry_after_is_honoured(client, session):
    session.routes[NOTE] = [FakeRaw(429, headers={"Retry-After": "60"}), FakeRaw(200, "ok")]
    client.get(NOTE)
    first, second = request_times(session, NOTE)
    assert second - first >= 60


def test_retry_after_is_capped(client, session):
    session.routes[NOTE] = [FakeRaw(429, headers={"Retry-After": "86400"}), FakeRaw(200, "ok")]
    client.get(NOTE)
    first, second = request_times(session, NOTE)
    assert second - first == pytest.approx(300)


def test_404_is_not_retried(client, session):
    session.routes[NOTE] = FakeRaw(404)
    assert client.get(NOTE).status == 404
    assert len(session.requested(NOTE)) == 1


def test_challenge_on_a_note_blocks_the_host(client, session):
    session.routes[NOTE] = FakeRaw(403, CHALLENGE, {"cf-mitigated": "challenge"})
    with pytest.raises(Blocked):
        client.get(NOTE)
    assert len(session.requested(NOTE)) == 1


def test_just_a_moment_page_is_a_challenge(client, session):
    session.routes[NOTE] = FakeRaw(403, CHALLENGE)
    with pytest.raises(Blocked):
        client.get(NOTE)


def test_blocked_host_gets_no_more_requests(client, session):
    session.routes[NOTE] = FakeRaw(403, CHALLENGE, {"cf-mitigated": "challenge"})
    with pytest.raises(Blocked):
        client.get(NOTE)
    sent = len(session.calls)
    with pytest.raises(Blocked):
        client.get(NOTE + "otra/")
    assert len(session.calls) == sent


def test_unreadable_robots_blocks_the_host(client, session):
    session.routes["https://www.example.com/robots.txt"] = FakeRaw(403, "forbidden")
    with pytest.raises(Blocked):
        client.get(NOTE)
    assert session.requested(NOTE) == []


def test_plain_403_is_returned(client, session):
    session.routes[NOTE] = FakeRaw(403, "<html>forbidden</html>")
    assert client.get(NOTE).status == 403


def test_redirect_records_the_final_url(client, session):
    session.routes[NOTE] = FakeRaw(200, "home", url="https://www.example.com/")
    response = client.get(NOTE)
    assert response.url == NOTE
    assert response.final_url == "https://www.example.com/"


def test_default_client_uses_a_requests_session():
    assert isinstance(PoliteClient().session, requests.Session)
