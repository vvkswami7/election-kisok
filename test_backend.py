# pytest.ini: asyncio_mode = auto, testpaths = .

from fastapi.testclient import TestClient
import pytest

from backend import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


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
        assert response.json().get("grounded") is True

    def test_query_rejects_empty_question(self, client):
        response = client.post(
            "/api/query",
            json={"question": "", "source": "text"},
        )
        assert response.status_code == 422 or "error" in response.json()


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
