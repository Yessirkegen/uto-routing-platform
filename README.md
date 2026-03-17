# UTO Routing Platform

Прототип backend-сервиса для интеллектуальной маршрутизации и диспетчеризации спецтехники на нефтяных месторождениях.

Продукт включает:
- построение маршрутов по графу дорог
- рекомендации `top-k` техники под заявку с объяснимым score
- batch-планирование по стратегиям `baseline`, `priority_greedy`, `multistop_heuristic`
- более сильный batch solver `ortools_solver`
- оценку выгодности multi-stop группировки
- benchmark/simulation для сравнения подходов на сотнях и тысячах сценариев
- встроенный sample dataset для мгновенного старта
- сгенерированный `CSV`-dataset для file-based тестов
- встроенный web dashboard без отдельного frontend build step
- live-state endpoint и dispatcher audit trail
- Leaflet map с vehicle/task overlay и последними route/plan результатами
- корректную модель времени для `day/night` смен, включая ночные задачи после полуночи
- richer diagnostics: task context, warnings, score breakdown, plan metrics и сравнение с baseline
- прямой PostgreSQL adapter в дополнение к `sample` и `directory` режимам
- persistent benchmark reports с export в `CSV`
- historical replay для визуализации и анимации движения техники
- weight tuning для greedy scoring
- optional API-key auth, structured logging и CI workflow

## Стек
- `Python 3.11+`
- `FastAPI`
- чистый Python core без тяжелых обязательных зависимостей

## Запуск для ревьювера
Самый простой путь:

```bash
docker compose up --build
```

Если нужна публичная reviewer-ссылка через quick tunnel:

```bash
docker compose --profile share up --build
```

Получить текущий публичный URL:

```bash
python3 scripts/print_share_url.py
```

или

```bash
make docker-share-url
```

После старта:

- `http://127.0.0.1:8000/` - web dashboard
- `http://127.0.0.1:8000/docs` - Swagger UI
- `http://127.0.0.1:8000/health` - healthcheck

Для `share`-режима публичный URL появится в логах сервиса `cloudflared`.

Остановка:

```bash
docker compose down
```

Если нужно полностью пересоздать и PostgreSQL volume с demo-данными:

```bash
docker compose down -v
docker compose up --build
```

В `docker-compose.yml` теперь поднимаются:
- `postgres` с auto-seeded demo dataset
- `uto-routing-platform`, который читает данные уже напрямую из PostgreSQL
- опционально `cloudflared` profile для публичной reviewer-ссылки

UI теперь включает:
- Leaflet карту с vehicle/task overlay
- replay animation поверх карты
- dispatcher audit trail
- benchmark report export
- weight tuning panel

## Быстрый старт
Если у вас есть обычный `pip`:

```bash
python3 -m pip install -r requirements-dev.txt
PYTHONPATH=. python3 -m uvicorn uto_routing.main:app --reload
```

Сервис поднимется на `http://127.0.0.1:8000`.

Откройте в браузере:

- `http://127.0.0.1:8000/` - web dashboard
- `http://127.0.0.1:8000/docs` - Swagger UI

## Основные эндпоинты
- `GET /health`
- `GET /app-config`
- `GET /api/catalog`
- `GET /api/live-state`
- `GET /api/audit/trail`
- `GET /api/benchmark/reports`
- `GET /api/benchmark/reports/latest`
- `GET /api/benchmark/reports/latest.csv`
- `GET /api/dataset/summary`
- `POST /api/recommendations`
- `POST /api/route`
- `POST /api/multitask`
- `POST /api/plan`
- `POST /api/benchmark/run`
- `POST /api/replay/run`
- `POST /api/tuning/run`
- `POST /api/dataset/reload`

## Примеры запросов

### 1. Рекомендации по существующей заявке
```bash
curl -X POST http://127.0.0.1:8000/api/recommendations \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "T-2026-0001",
    "strategy": "priority_greedy",
    "top_k": 3
  }'
```

### 2. Рекомендации по новой заявке
```bash
curl -X POST http://127.0.0.1:8000/api/recommendations \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "CUSTOM-1",
    "priority": "high",
    "destination_uwi": "05-1200-501",
    "planned_start": "2026-03-17T09:00:00",
    "start_day": "2026-03-17",
    "duration_hours": 4.5,
    "task_type": "acidizing",
    "strategy": "priority_greedy"
  }'
```

### 3. Построение маршрута
```bash
curl -X POST http://127.0.0.1:8000/api/route \
  -H "Content-Type: application/json" \
  -d '{
    "from": {"wialon_id": 10202},
    "to": {"uwi": "05-1200-501"}
  }'
```

### 4. Анализ multi-stop
```bash
curl -X POST http://127.0.0.1:8000/api/multitask \
  -H "Content-Type: application/json" \
  -d '{
    "task_ids": ["T-2026-0001", "T-2026-0002", "T-2026-0003"],
    "constraints": {
      "max_total_time_minutes": 480,
      "max_detour_ratio": 1.3
    }
  }'
```

### 5. Batch-план по всем задачам
```bash
curl -X POST http://127.0.0.1:8000/api/plan \
  -H "Content-Type: application/json" \
  -d '{
    "strategy": "multistop_heuristic"
  }'
```

### 6. Benchmark на 1000 сценариев
```bash
curl -X POST http://127.0.0.1:8000/api/benchmark/run \
  -H "Content-Type: application/json" \
  -d '{
    "scenarios": 1000,
    "min_tasks": 6,
    "max_tasks": 12,
    "min_vehicles": 4,
    "max_vehicles": 7,
    "seed": 42
  }'
```

## Как устроены стратегии

### `baseline`
Наивное назначение: ближайшая совместимая техника, свободная к моменту начала работ.

### `priority_greedy`
Скоринг-кандидат для одиночной заявки и жадное batch-назначение с учетом:
- расстояния по графу
- ETA
- времени освобождения техники
- риска нарушения SLA
- совместимости по типу работ

### `multistop_heuristic`
Формирует компактные пары задач, если это реально снижает пробег, после чего назначает группы на одну единицу техники.

### `ortools_solver`
Глобальный solver на `OR-Tools`, который одновременно учитывает:
- множественные стартовые позиции техники
- совместимость техники и типа работ
- временные окна
- soft penalties по SLA
- multi-stop последовательности внутри маршрутов

## Replay и анимация
`/api/replay/run` строит replay timeline по выбранной стратегии и возвращает playback frames.

В UI benchmark-кнопка автоматически запускает replay animation параллельно с benchmark запросом, чтобы было видно, как техника движется по маршрутам.

## Benchmark reports
После каждого benchmark запуска отчет сохраняется в persistent store.

Доступно:
- `GET /api/benchmark/reports`
- `GET /api/benchmark/reports/latest`
- `GET /api/benchmark/reports/latest.csv`

## Weight tuning
`/api/tuning/run` подбирает более удачные scoring weights для `priority_greedy` стратегии и сохраняет tuning report.

## Auth и logging
Опционально можно включить API key auth:

```bash
export UTO_API_KEY=supersecret
```

Тогда для `API` запросов нужно передавать:
- `X-API-Key: supersecret`
или
- `Authorization: Bearer supersecret`

Structured logging настраивается через:

```bash
export UTO_LOG_FORMAT=json
export UTO_LOG_LEVEL=INFO
```

## Реальные данные
По умолчанию сервис запускается на встроенном sample dataset.

Также в репозитории уже лежит готовый file-based dataset:

```bash
sample_dataset_csv/
```

Чтобы запустить сервис именно на `CSV`-файлах, а не на in-memory sample mode:

```bash
export UTO_DATA_DIR=/absolute/path/to/uto-routing-platform/sample_dataset_csv
PYTHONPATH=. python3 -m uvicorn uto_routing.main:app --reload
```

В Docker этот режим уже включен по умолчанию через:

```bash
UTO_DATA_DIR=/app/sample_dataset_csv
```

Для подключения собственного набора данных задайте:

```bash
export UTO_DATA_DIR=/absolute/path/to/dataset
```

Для прямого PostgreSQL режима:

```bash
export UTO_DATA_SOURCE=postgres
export UTO_DATABASE_URL=postgresql://user:password@host:5432/dbname
```

Опционально можно переопределить имена таблиц:

```bash
export UTO_PG_TABLE_ROAD_NODES=road_nodes
export UTO_PG_TABLE_ROAD_EDGES=road_edges
export UTO_PG_TABLE_WELLS=wells
export UTO_PG_TABLE_VEHICLES=vehicles
export UTO_PG_TABLE_TASKS=tasks
export UTO_PG_TABLE_COMPATIBILITY=compatibility
```

Для persistent app storage без Postgres можно задать:

```bash
export UTO_APP_DB_PATH=.data/uto_app.db
```

Для отдельной app database:

```bash
export UTO_APP_DATABASE_URL=postgresql://user:password@host:5432/app_db
```

В папке должны лежать файлы:
- `road_nodes.csv` или `road_nodes.json`
- `road_edges.csv` или `road_edges.json`
- `wells.csv` или `wells.json`
- `vehicles.csv` или `vehicles.json`
- `tasks.csv` или `tasks.json`
- `compatibility.csv` или `compatibility.json`

Минимальные поля:

### `road_nodes`
- `node_id`
- `lon`
- `lat`

### `road_edges`
- `source`
- `target`
- `weight` или `weight_m`

### `wells`
- `uwi`
- `longitude`/`latitude` или `lon`/`lat`
- опционально `nearest_node_id`

### `vehicles`
- `vehicle_id`
- `name`
- `vehicle_type`
- `current_node`
- `lon`
- `lat`
- `available_at` в ISO формате
- `avg_speed_kmph`
- опционально `skills` как `task_a|task_b|task_c`

### `tasks`
- `task_id`
- `priority`
- `planned_start` в ISO формате
- `start_day` в ISO формате для корректной интерпретации смены, особенно `night`
- `planned_duration_hours`
- `destination_uwi`
- `task_type`
- `shift`

### `compatibility`
- `task_type`
- `vehicle_type`

## Docker-файлы
- `Dockerfile` - production-like image with bundled app code
- `docker-compose.yml` - one-command reviewer startup with `postgres + app`
- `.dockerignore` - excludes local caches, tests, and virtualenv artifacts from build context
- `db/init/` - postgres schema + seed scripts
- `.github/workflows/ci.yml` - tests + docker build in CI

## Структура проекта
```text
sample_dataset_csv/     # generated CSV dataset for tests and demos
db/init/                # Postgres schema and seed scripts
scripts/
  export_sample_csv.py  # regenerate sample CSV exports
uto_routing/
  config.py         # runtime settings and env parsing
  audit.py          # dispatcher audit trail store
  storage.py        # persistent audit/report storage + migrations
  api.py            # FastAPI endpoints
  service.py        # orchestration layer
  graph.py          # graph index, shortest path, map-matching
  planners.py       # recommenders and batch planners
  ortools_solver.py # stronger OR-Tools batch optimizer
  scoring.py        # explainable scoring
  benchmark.py      # synthetic scenarios and benchmark runner
  replay.py         # historical replay and playback timeline generation
  tuning.py         # scoring weight search
  logging_utils.py  # structured logging setup
  data_loading.py   # sample/file-based dataset loading
  sample_data.py    # built-in demo dataset
  models.py         # domain models
  static/           # built-in browser UI
tests/
  test_graph.py
  test_service.py
  test_api.py
  test_benchmark.py
```

## Тесты
```bash
python3 -m pip install -r requirements-dev.txt
PYTHONPATH=. pytest
```

## Полезные команды
```bash
make run
make test
make export-csv
make docker-up
make docker-share
make docker-down
make docker-reset
```

## Что уже готово
- Полностью рабочий backend
- Встроенный demo dataset
- Generated `CSV` dataset for tests and demos
- Dockerfile + docker compose for reviewer startup
- PostgreSQL direct data source mode
- End-to-end API
- Browser UI on `/` with Leaflet map and audit trail
- Benchmark framework для сравнения подходов
- Расширенный regression test suite

## Дальнейшее развитие
- подключение к PostgreSQL напрямую вместо file export
- более сильный batch solver (`OR-Tools`)
- richer объяснения и audit trail для диспетчера
- полноценная карта с leaflet/mapbox и live vehicle state
