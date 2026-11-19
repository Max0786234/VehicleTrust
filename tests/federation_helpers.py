"""Test helpers: route federated HTTP calls to in-process ASGI service apps (same HTTP code path)."""
import asyncio

import httpx

SERVICE_PORTS = {"vehicle_registry": 8101, "insurance_records": 8102, "registration_authority": 8103,
                 "theft_scrapping": 8104, "audit_log": 8105}
TEST_URLS = {key: f"http://{key}.test:{port}" for key, port in SERVICE_PORTS.items()}


def service_apps():
    from service_audit import app as audit_app
    from service_insurance import app as insurance_app
    from service_registration import app as registration_app
    from service_registry import app as registry_app
    from service_theft import app as theft_app
    return {"vehicle_registry": registry_app, "insurance_records": insurance_app,
            "registration_authority": registration_app, "theft_scrapping": theft_app, "audit_log": audit_app}


class RouterTransport(httpx.AsyncBaseTransport):
    """Dispatches by host to an ASGI app. `down` = refuse connection, `slow` = {service: seconds}."""

    def __init__(self, apps, down=(), slow=None, http_error=()):
        self.transports = {f"{k}.test": httpx.ASGITransport(app=a) for k, a in apps.items()}
        self.down, self.slow, self.http_error = set(down), dict(slow or {}), set(http_error)
        self.calls = []

    async def handle_async_request(self, request):
        service = request.url.host.replace(".test", "")
        self.calls.append(service)
        if service in self.down:
            raise httpx.ConnectError(f"Connection refused by {service}", request=request)
        if service in self.http_error:
            return httpx.Response(500, text="internal error", request=request)
        if service in self.slow:
            await asyncio.sleep(self.slow[service])
        return await self.transports[request.url.host].handle_async_request(request)
