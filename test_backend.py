from contextlib import asynccontextmanager
import asyncio

import httpx
import pytest

import backend

app = backend.app


@asynccontextmanager
async def disabled_lifespan(_app):
    yield


app.router.lifespan_context = disabled_lifespan


class ASGITestClient:
    def request(self, method, url, **kwargs):
        async def run_request():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
                return await c.request(method, url, **kwargs)

        return asyncio.run(run_request())

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)


@pytest.fixture(scope="module")
def client():
    return ASGITestClient()


@pytest.fixture(autouse=True)
def stable_backend(monkeypatch):
    backend.rate_limit_hits.clear()
    monkeypatch.setattr(backend, "gemini_client", None)
    monkeypatch.setattr(backend, "chroma_collection", None)


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_health_has_status_key(self, client):
        response = client.get("/api/health")
        assert "status" in response.json()

    def test_health_has_services_key(self, client):
        response = client.get("/api/health")
        assert "services" in response.json()

    def test_health_timestamp_is_string(self, client):
        response = client.get("/api/health")
        assert isinstance(response.json().get("timestamp"), str)

    def test_api_responses_include_security_headers(self, client):
        response = client.get("/api/health")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"
        assert "default-src 'self'" in response.headers.get("Content-Security-Policy", "")
        assert response.headers.get("Cache-Control") == "no-store"


class TestSecurityConfig:
    def test_default_cors_origins_are_explicit(self):
        assert "*" not in backend.ALLOWED_ORIGINS
        assert "http://localhost:8000" in backend.ALLOWED_ORIGINS

    def test_default_trusted_hosts_are_not_wildcard(self):
        assert "*" not in backend.ALLOWED_HOSTS
        assert "testserver" in backend.ALLOWED_HOSTS


class TestStatusEndpoint:
    def test_status_returns_200(self, client):
        response = client.get("/api/status")
        assert response.status_code == 200

    def test_status_has_total_queries(self, client):
        response = client.get("/api/status")
        assert "total_queries" in response.json()

    def test_status_has_rag_chunks_loaded(self, client):
        response = client.get("/api/status")
        assert "rag_chunks_loaded" in response.json()

    def test_status_has_memory_info(self, client):
        response = client.get("/api/status")
        data = response.json()
        assert "memory_used_mb" in data
        assert "memory_percent" in data

    def test_status_reports_google_services(self, client):
        response = client.get("/api/status")
        data = response.json()
        services = data.get("google_services", {})
        assert "gemini" in services
        assert "firebase" in services
        assert "cloud_logging" in services
        assert isinstance(data.get("google_services_total_active"), int)
        assert isinstance(data.get("google_services_timestamp"), str)


class TestQueryEndpoint:
    def test_query_returns_200_with_valid_payload(self, client):
        response = client.post(
            "/api/query",
            json={"question": "What is the voting age in India?", "source": "text"},
        )
        assert response.status_code == 200

    def test_query_response_has_answer_key(self, client):
        response = client.post(
            "/api/query",
            json={"question": "What is the voting age in India?", "source": "text"},
        )
        assert "answer" in response.json()

    def test_query_response_has_latency(self, client):
        response = client.post(
            "/api/query",
            json={"question": "What is the voting age in India?", "source": "text"},
        )
        assert "latency_seconds" in response.json()

    def test_query_response_has_grounded_flag(self, client):
        response = client.post(
            "/api/query",
            json={"question": "What is the voting age in India?", "source": "text"},
        )
        assert isinstance(response.json().get("grounded"), bool)

    def test_query_rejects_empty_question(self, client):
        response = client.post(
            "/api/query",
            json={"question": "", "source": "text"},
        )
        assert response.status_code == 422 or "error" in response.json()

    def test_query_rejects_extra_fields(self, client):
        response = client.post(
            "/api/query",
            json={
                "question": "What documents should I bring?",
                "source": "text",
                "unexpected": "field",
            },
        )
        assert response.status_code == 422

    def test_query_rejects_unknown_source(self, client):
        response = client.post(
            "/api/query",
            json={"question": "What documents should I bring?", "source": "unknown"},
        )
        assert response.status_code == 422

    def test_query_rate_limit_returns_429(self, client, monkeypatch):
        monkeypatch.setattr(backend, "RATE_LIMIT_MAX_REQUESTS", 1)
        monkeypatch.setattr(backend, "RATE_LIMIT_WINDOW_SECONDS", 60)

        first = client.post(
            "/api/query",
            json={"question": "What documents should I bring?", "source": "text"},
        )
        second = client.post(
            "/api/query",
            json={"question": "When is phase 1 polling?", "source": "text"},
        )

        assert first.status_code == 200
        assert second.status_code == 429

    def test_check_rate_limit_helper_returns_boolean(self, monkeypatch):
        monkeypatch.setattr(backend, "RATE_LIMIT_MAX_REQUESTS", 1)
        monkeypatch.setattr(backend, "RATE_LIMIT_WINDOW_SECONDS", 60)

        assert backend.check_rate_limit("198.51.100.9") is True
        backend.record_rate_limit_hit("198.51.100.9")
        assert backend.check_rate_limit("198.51.100.9") is False

    def test_query_uses_local_fallback_when_gemini_unavailable(self, client, monkeypatch):
        monkeypatch.setattr(backend, "gemini_client", None)
        monkeypatch.setattr(
            backend,
            "retrieve_context",
            lambda _: "[Source: eligibility.txt]\nBring a valid EPIC or Voter ID.",
        )

        response = client.post(
            "/api/query",
            json={"question": "What document should I bring?", "source": "text"},
        )

        data = response.json()
        assert response.status_code == 200
        assert data["model"] == "local-rag-fallback"
        assert "EPIC" in data["answer"]
        assert data["grounded"] is True
        assert data["context_used"] == ["eligibility.txt"]

    def test_legacy_chat_endpoint_returns_edge_response(self, client, monkeypatch):
        monkeypatch.setattr(backend, "gemini_client", None)
        monkeypatch.setattr(
            backend,
            "retrieve_context",
            lambda _: "[Source: timeline.txt]\nPhase 1 Polling is May 15, 2026.",
        )

        response = client.post(
            "/api/chat",
            json={"query": "When is phase 1 polling?"},
        )

        data = response.json()
        assert response.status_code == 200
        assert data["response"] == data["answer"]
        assert "May 15, 2026" in data["response"]

    def test_google_services_endpoint_returns_service_summary(self, client):
        response = client.get("/api/google-services")
        data = response.json()
        assert response.status_code == 200
        assert "services" in data
        assert "gemini" in data["services"]
        assert "description" in data["services"]["gemini"]
        assert isinstance(data["total_active"], int)
        assert isinstance(data["timestamp"], str)

    def test_retrieve_context_sources_preserves_string_context_contract(self, monkeypatch):
        monkeypatch.setattr(
            backend,
            "retrieve_context",
            lambda _query, n=4: "[Source: eligibility.txt]\nVoter ID details.",
        )

        assert backend.retrieve_context_sources("What ID should I bring?") == ["eligibility.txt"]


class TestLoraEndpoint:
    def test_lora_update_returns_200(self, client):
        response = client.post(
            "/api/lora-update",
            json={
                "update_type": "timeline_update",
                "message": "Test update",
                "timestamp": "2024-01-01T00:00:00Z",
            },
        )
        assert response.status_code == 200

    def test_lora_response_has_status_received(self, client):
        response = client.post(
            "/api/lora-update",
            json={
                "update_type": "timeline_update",
                "message": "Test update",
                "timestamp": "2024-01-01T00:00:00Z",
            },
        )
        assert response.json().get("status") == "received"

    def test_lora_increments_stats(self, client):
        before = client.get("/api/status").json().get("total_lora_updates", 0)
        client.post(
            "/api/lora-update",
            json={
                "update_type": "timeline_update",
                "message": "Test update",
                "timestamp": "2024-01-01T00:00:00Z",
            },
        )
        after = client.get("/api/status").json().get("total_lora_updates", 0)
        assert after == before + 1

    def test_mesh_update_alias_returns_200(self, client):
        response = client.post(
            "/api/mesh-update",
            json={
                "status": "Network Sync OK",
                "rssi": -75,
                "messages_queued": 0,
                "last_sync": "2026-05-01T00:00:00Z",
            },
        )

        assert response.status_code == 200
        assert response.json().get("status") == "received"

    def test_lora_rejects_invalid_timestamp(self, client):
        response = client.post(
            "/api/lora-update",
            json={
                "update_type": "timeline_update",
                "message": "Test update",
                "timestamp": "not-a-date",
            },
        )
        assert response.status_code == 422
