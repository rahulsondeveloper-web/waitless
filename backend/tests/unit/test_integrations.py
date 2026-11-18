"""Phase 12: production adapters (S3, maps, SMS/WhatsApp/e-mail), production settings safety, security headers
and metrics — all without network access (stubbed clients and mock HTTP transports)."""

import json

import boto3
import httpx
import pytest
from botocore.stub import ANY, Stubber

from app.core import config
from app.core.config import Settings
from app.core.errors import AppError
from app.core.storage import S3Storage
from app.integrations import maps, messaging

# ---------- S3 ----------


async def test_s3_storage_puts_and_deletes_with_random_keys() -> None:
    client = boto3.client("s3", region_name="ap-south-1", aws_access_key_id="x", aws_secret_access_key="y")
    stub = Stubber(client)
    stub.add_response(
        "put_object",
        {},
        {"Bucket": "wl-media", "Key": ANY, "Body": b"img", "ContentType": "image/webp", "CacheControl": ANY},
    )
    stub.add_response("delete_object", {}, {"Bucket": "wl-media", "Key": ANY})
    store = S3Storage(
        "wl-media", region="ap-south-1", prefix="media", public_base_url="https://cdn.waitless.app/", client=client
    )
    with stub:
        f = await store.save("tenants/t1/gallery", b"img", extension="WEBP", content_type="image/webp")
        assert f.key.startswith("tenants/t1/gallery/") and f.key.endswith(".webp") and len(f.key.split("/")[-1]) == 37
        assert f.url == f"https://cdn.waitless.app/media/{f.key}"
        await store.delete(f.key)
    stub.assert_no_pending_responses()
    with pytest.raises(AppError):
        await store.save("../etc", b"x", extension="png", content_type="image/png")
    with pytest.raises(AppError):
        await store.save("ok", b"x", extension="p/ng", content_type="image/png")
    plain = S3Storage("b", region="eu-west-1", client=client)
    assert plain.url_for("a/b.png") == "https://b.s3.eu-west-1.amazonaws.com/a/b.png"
    minio = S3Storage("b", region="x", endpoint_url="http://minio:9000/", client=client)
    assert minio.url_for("a.png") == "http://minio:9000/b/a.png"


# ---------- messaging ----------


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if "fail" in str(request.url):
            return httpx.Response(500, json={"error": "down"})
        return httpx.Response(200, json={"sid": "SM1", "messages": [{"id": "wamid"}]})

    messaging.set_transport(httpx.MockTransport(handler))
    yield calls
    messaging.set_transport(None)


def _settings(monkeypatch: pytest.MonkeyPatch, **kw) -> None:  # type: ignore[no-untyped-def]
    s = Settings(**kw)
    monkeypatch.setattr(config, "get_settings", lambda: s)
    monkeypatch.setattr(messaging, "get_settings", lambda: s)
    monkeypatch.setattr(maps, "get_settings", lambda: s)


async def test_otp_via_msg91_and_twilio(monkeypatch: pytest.MonkeyPatch, sent: list[httpx.Request]) -> None:
    _settings(monkeypatch, sms_provider="msg91", msg91_auth_key="K", msg91_otp_template_id="T1")
    await messaging.send_otp("+919812345678", "482913")
    r = sent[-1]
    assert r.url.host == "control.msg91.com" and r.headers["authkey"] == "K"
    assert r.url.params["mobile"] == "919812345678" and r.url.params["otp"] == "482913"

    _settings(
        monkeypatch,
        sms_provider="twilio",
        twilio_account_sid="AC1",
        twilio_auth_token="tok",
        twilio_sms_from="+15550001",
    )
    await messaging.send_otp("+919812345678", "111222")
    r = sent[-1]
    assert r.url.path == "/2010-04-01/Accounts/AC1/Messages.json" and r.headers["authorization"].startswith("Basic ")
    assert "111222" in r.content.decode() and "To=%2B919812345678" in r.content.decode()


async def test_otp_failure_is_a_friendly_503(monkeypatch: pytest.MonkeyPatch, sent: list[httpx.Request]) -> None:
    _settings(monkeypatch, sms_provider="msg91", msg91_auth_key="K", msg91_otp_template_id="fail")
    with pytest.raises(AppError) as err:
        await messaging.send_otp("+919812345678", "1")
    assert err.value.status_code == 503 and err.value.code == "SMS_FAILED"


async def test_notifications_prefer_whatsapp_and_never_raise(
    monkeypatch: pytest.MonkeyPatch, sent: list[httpx.Request]
) -> None:
    _settings(monkeypatch, whatsapp_provider="meta", meta_whatsapp_token="W", meta_whatsapp_phone_id="123")
    assert await messaging.send_text("+919812345678", "Your table is ready") == "whatsapp"
    body = json.loads(sent[-1].content)
    assert (
        sent[-1].url.path == "/v20.0/123/messages"
        and body["to"] == "919812345678"
        and body["text"]["body"] == "Your table is ready"
    )
    _settings(monkeypatch, whatsapp_provider="meta", meta_whatsapp_token="W", meta_whatsapp_phone_id="fail")
    assert await messaging.send_text("+919812345678", "x") == "failed"  # logged, not raised
    _settings(monkeypatch)
    assert await messaging.send_text("+919812345678", "x") == "console"
    assert await messaging.send_email("a@b.c", "Hi", "Body") == "console"


# ---------- maps ----------


async def test_geocoders_parse_nominatim_and_google(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "nominatim.openstreetmap.org":
            assert request.headers["user-agent"].startswith("WaitLess")
            return httpx.Response(
                200,
                json=[
                    {
                        "lat": "18.53",
                        "lon": "73.89",
                        "display_name": "Koregaon Park, Pune",
                        "address": {"suburb": "Koregaon Park", "state": "Maharashtra", "postcode": "411001"},
                    }
                ],
            )
        assert request.url.params["key"] == "G"
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "results": [
                    {
                        "formatted_address": "MG Road, Pune",
                        "geometry": {"location": {"lat": 18.51, "lng": 73.87}},
                        "address_components": [
                            {"long_name": "Pune", "types": ["locality"]},
                            {"long_name": "411001", "types": ["postal_code"]},
                        ],
                    }
                ],
            },
        )

    t = httpx.MockTransport(handler)
    _settings(monkeypatch)
    osm = await maps.geocode("Koregaon Park Pune", maps.NominatimGeocoder(transport=t))
    assert osm[0].lat == 18.53 and osm[0].city == "Koregaon Park" and osm[0].postal_code == "411001"
    _settings(monkeypatch, maps_provider="google", google_maps_api_key="G")
    g = await maps.geocode("MG Road Pune", maps.GoogleGeocoder(transport=t))
    assert (g[0].lat, g[0].city, g[0].label) == (18.51, "Pune", "MG Road, Pune")
    assert await maps.geocode("ab") == []  # too short: no lookup

    broken = httpx.MockTransport(lambda r: httpx.Response(503))
    with pytest.raises(AppError) as err:
        await maps.geocode("Some street name", maps.NominatimGeocoder(transport=broken))
    assert err.value.code == "GEOCODER_ERROR"


# ---------- production safety ----------


def test_production_refuses_development_defaults() -> None:
    with pytest.raises(ValueError) as err:
        Settings(_env_file=None, environment="production")  # type: ignore[call-arg]
    msg = str(err.value)
    for needle in ("JWT_SECRET", "DB_PASSWORD", "PAYMENT_PROVIDER=mock", "CORS_ORIGINS", "SMS_PROVIDER"):
        assert needle in msg
    ok = Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment="production",
        jwt_secret="x" * 48,
        db_password="secret",
        payment_provider="cashfree",
        cashfree_app_id="cf_app_1",
        cashfree_secret_key="s",
        cashfree_env="production",
        cors_origins=["https://waitless.app"],
        sms_provider="msg91",
    )
    assert ok.docs_enabled is False and ok.expose_dev_codes is False
    assert Settings().docs_enabled is True


# ---------- headers & metrics ----------


async def test_security_headers_and_metrics(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    r = await client.get("/api/v1/public/content")
    for h in ("x-content-type-options", "referrer-policy", "x-frame-options", "permissions-policy"):
        assert h in r.headers
    assert r.headers["cache-control"] == "no-store" and r.headers["x-request-id"]
    assert (await client.get("/api/v1/metrics")).status_code == 404  # off without a token
    s = config.get_settings()
    monkeypatch.setattr(s, "metrics_token", "m-token")
    assert (await client.get("/api/v1/metrics", headers={"Authorization": "Bearer wrong"})).status_code == 404
    m = await client.get("/api/v1/metrics", headers={"Authorization": "Bearer m-token"})
    assert m.status_code == 200 and "waitless_http_requests_total" in m.text and 'le="+Inf"' in m.text
