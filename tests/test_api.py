from fastapi.testclient import TestClient

from uto_routing.api import app, get_platform


def test_api_endpoints_smoke() -> None:
    get_platform.cache_clear()
    client = TestClient(app)

    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "Панель управления спецтехникой" in dashboard.text

    catalog = client.get("/api/catalog")
    assert catalog.status_code == 200
    assert len(catalog.json()["tasks"]) > 0

    live_state = client.get("/api/live-state")
    assert live_state.status_code == 200
    assert "vehicles" in live_state.json()

    summary = client.get("/api/dataset/summary")
    assert summary.status_code == 200
    task_id = get_platform().dataset.tasks[0].task_id

    recommendations = client.post(
        "/api/recommendations",
        json={
            "task_id": task_id,
            "strategy": "priority_greedy",
            "top_k": 3,
        },
    )
    assert recommendations.status_code == 200
    assert len(recommendations.json()["units"]) == 3

    custom_recommendations = client.post(
        "/api/recommendations",
        json={
            "task_id": "CUSTOM-API-1",
            "priority": "high",
            "destination_uwi": get_platform().dataset.wells[0].uwi,
            "planned_start": "2026-03-17T09:00:00",
            "duration_hours": 3.5,
            "task_type": "acidizing",
            "strategy": "priority_greedy",
            "top_k": 2,
        },
    )
    assert custom_recommendations.status_code == 200
    assert len(custom_recommendations.json()["units"]) == 2
    assert "task_context" in custom_recommendations.json()
    assert "score_breakdown" in custom_recommendations.json()["units"][0]

    benchmark = client.post(
        "/api/benchmark/run",
        json={
            "scenarios": 3,
            "min_tasks": 4,
            "max_tasks": 5,
            "min_vehicles": 3,
            "max_vehicles": 4,
            "seed": 2,
        },
    )
    assert benchmark.status_code == 200
    assert benchmark.json()["scenarios"] == 3

    replay = client.post(
        "/api/replay/run",
        json={
            "strategy": "priority_greedy",
            "frame_interval_minutes": 30,
        },
    )
    assert replay.status_code == 200
    assert replay.json()["playback"]["frames"]

    tuning = client.post(
        "/api/tuning/run",
        json={"candidate_limit": 4},
    )
    assert tuning.status_code == 200
    assert tuning.json()["best_candidate"]["weights"]

    audit = client.get("/api/audit/trail?limit=10")
    assert audit.status_code == 200
    assert len(audit.json()["events"]) >= 1

    latest_benchmark_report = client.get("/api/benchmark/reports/latest")
    assert latest_benchmark_report.status_code == 200

    latest_benchmark_csv = client.get("/api/benchmark/reports/latest.csv")
    assert latest_benchmark_csv.status_code == 200
    assert "report_id,strategy" in latest_benchmark_csv.text

    with client.websocket_connect("/ws/live") as websocket:
        connected = websocket.receive_json()
        assert connected["type"] == "connection"
        snapshot = websocket.receive_json()
        assert snapshot["type"] == "snapshot"
        assert "vehicles" in snapshot["payload"]

    invalid_custom_request = client.post(
        "/api/recommendations",
        json={
            "task_id": "UNKNOWN-CUSTOM",
            "strategy": "priority_greedy",
        },
    )
    assert invalid_custom_request.status_code == 400

