import os
import unittest
from unittest.mock import patch
from quant_lab import api

class AnalyticsApiTests(unittest.TestCase):
    def setUp(self):
        self.client = api.app.test_client()

    def test_event_requires_storage(self):
        with patch.object(api.analytics_store, "is_configured", return_value=False):
            response = self.client.post("/api/analytics/event", json={
                "event_type": "page_view", "visitor_id": "v1", "session_id": "s1", "page_path": "/"
            })
        self.assertEqual(response.status_code, 503)

    def test_report_requires_admin_token(self):
        with patch.dict(os.environ, {"QUANT_ADMIN_TOKEN": "test-secret"}):
            response = self.client.get("/api/analytics/report")
        self.assertEqual(response.status_code, 401)

    def test_report_returns_aggregate(self):
        report = {
            "period_days": 7, "unique_visitors": 4, "page_views": 9, "sessions": 5,
            "strategies_saved": 2, "interpretations": 3, "backtests": 2, "client_errors": 0,
            "top_pages": [], "event_breakdown": [], "generated_at": "2026-11-08T00:00:00+00:00",
            "storage": "postgresql"
        }
        with patch.dict(os.environ, {"QUANT_ADMIN_TOKEN": "test-secret"}), \
             patch.object(api.analytics_store, "is_configured", return_value=True), \
             patch.object(api.analytics_store, "daily_report", return_value=report):
            response = self.client.get("/api/analytics/report?days=7",
                headers={"Authorization": "Bearer test-secret"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["unique_visitors"], 4)

    def test_event_accepts_anonymous_event(self):
        captured = {}
        with patch.object(api.analytics_store, "is_configured", return_value=True), \
             patch.object(api.analytics_store, "record_event", side_effect=lambda payload: captured.update(payload)):
            response = self.client.post("/api/analytics/event", json={
                "event_type": "page_view", "visitor_id": "anonymous-id",
                "session_id": "session-id", "page_path": "/", "metadata": {}
            })
        self.assertEqual(response.status_code, 202)
        self.assertEqual(captured["visitor_id"], "anonymous-id")

if __name__ == "__main__":
    unittest.main()
