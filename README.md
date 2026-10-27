# 🛗 Vertex Elevator Fleet Simulation System

A production-grade, distributed, containerized elevator fleet simulation built with **FastAPI**, **Redis** (durable with PVC and atomic Lua scripts), and deployable to **Kubernetes** as 16-replica StatefulSets with a live real-time web monitoring UI.

---

## 🏛️ System Architecture

```mermaid
flowchart TD
    subgraph UI ["User Interface (Browser)"]
        WebUI["Web Dashboard\n(Shaft Animation & Hall Call Station)"]
    end

    subgraph Orchestration ["Orchestration Tier"]
        Orchestrator["lift-orchestrator (StatefulSet)\nFastAPI + WebSocket Server"]
    end

    subgraph Storage ["Durable Persistence Tier"]
        Redis[("Redis 7 (StatefulSet + PVC)\nAOF & Snapshot Durability")]
    end

    subgraph Lifts ["Lift Execution Tier (16 StatefulSet Pods)"]
        L0["lift-service-0\n(LOOK Algorithm)"]
        L1["lift-service-1\n(LOOK Algorithm)"]
        Ldots["..."]
        L15["lift-service-15\n(LOOK Algorithm)"]
    end

    WebUI <-->|WebSocket & REST API| Orchestrator
    Orchestrator -->|Atomic Claim & Assign (Lua)| Redis
    Orchestrator -->|HTTP POST /trigger| L0
    Orchestrator -->|HTTP POST /trigger| L1
    Orchestrator -->|HTTP POST /trigger| L15

    L0 <-->|HKEYS / HDEL: lift-service-0.service_queue\nSET: lift-service-0.status| Redis
    L1 <-->|HKEYS / HDEL: lift-service-1.service_queue\nSET: lift-service-1.status| Redis
    L15 <-->|HKEYS / HDEL: lift-service-15.service_queue\nSET: lift-service-15.status| Redis
```

---

## 🚀 Key Features

1. **Durable & Concurrency-Safe Redis**:
   - Redis runs as a **Kubernetes StatefulSet** with a dedicated PersistentVolumeClaim (PVC) mounted to `/data`.
   - Durability guaranteed using `appendonly yes` and `appendfsync everysec`.
   - Concurrency safety guaranteed using an **atomic Redis Lua script** (`ASSIGN_REQUEST_LUA`) that claims a hall request from `hall-request` and pushes it into `<lift-id>.service_queue` atomically with zero race conditions.

2. **16-Replica StatefulSet `lift-service`**:
   - Kubernetes StatefulSet with 16 pods (`lift-service-0` through `lift-service-15`).
   - Uses the Kubernetes **Downward API** (`metadata.name`) to automatically identify its pod name `POD_NAME`.
   - Dedicated headless service `lift-service` provides DNS resolution for each pod:
     `http://lift-service-<N>.lift-service.lift-system.svc.cluster.local:8000`.

3. **LOOK Elevator Algorithm**:
   - Pure async loop running as long as floors exist in `<lift-id>.service_queue`.
   - Continues in current direction servicing requests ahead.
   - When no further requests exist in current direction, smoothly reverses and services floors in opposite direction.
   - Transitions to **IDLE** state when queue is empty and waits for the `/trigger` endpoint.

4. **Fractional Floor Telemetry & Deliberate Pacing**:
   - Deliberately paced with ~1.0 second transit per floor (5 sub-steps of 0.2s each).
   - Redis status updated at each sub-step:
     - IDLE on floor 9: `{"floor": 9, "direction": 0}`
     - Moving UP: `{"floor": 7.2, "direction": 1}`
     - Moving DOWN: `{"floor": 5.4, "direction": -1}`
   - Simulates door open/close dwell time on floor arrival.

5. **Heuristic Dispatcher in `lift-orchestrator`**:
   - Evaluates all 16 lifts for incoming requests `(floor, direction)`:
     1. **Nearest Approaching in Same Direction**: Lowest cost (picks up passenger en-route).
     2. **IDLE Lift**: Second lowest cost (immediately mobilizes).
     3. **Approaching in Opposite Direction**: Moderate penalty.
     4. **Moving Away**: Highest penalty (turnaround distance).

6. **Interactive Real-Time Web UI**:
   - Real-time 16-shaft building visualization.
   - Live animated elevator cars displaying fractional floor positions, direction arrows, and door opening glow.
   - Interactive Hall Call station to dispatch `(floor, direction)` tuples.
   - Traffic simulation presets (Morning Rush, Evening Rush, Random Burst).
   - Live streaming terminal log of assignments.

---

## 📂 Project Structure

```
LiftApplication/
├── app/
│   ├── __init__.py
│   ├── config.py                 # Central config reading ConfigMap & Downward API
│   ├── models.py                 # Pydantic models for Status, HallRequest, etc.
│   ├── redis_client.py           # Concurrency-safe Redis manager & Lua scripts
│   ├── lift/
│   │   ├── __init__.py
│   │   ├── look_algorithm.py     # Deterministic LOOK algorithm logic
│   │   ├── service.py            # Async movement loop with sub-stepping
│   │   └── main.py               # FastAPI app (/trigger, /status, /queue, /healthz)
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   ├── dispatcher.py         # Elevator dispatch heuristics
│   │   ├── service.py            # Continuous dispatch loop & WebSocket broadcaster
│   │   └── main.py               # FastAPI app (/api/requests, /api/lifts, UI static mount)
│   └── static/                   # Rich UI Dashboard
│       ├── index.html            # 16-shaft elevator visualizer & call station
│       ├── style.css             # Modern dark glassmorphic styling
│       └── app.js                # WebSocket client with live smooth animations
├── k8s/
│   ├── 00-namespace.yaml         # Namespace 'lift-system'
│   ├── 01-configmap.yaml         # ConfigMap 'lift-config' (floor_count: 20)
│   ├── 02-redis-statefulset.yaml # Redis StatefulSet + PVC + Service
│   ├── 03-lift-service-statefulset.yaml # 16 StatefulSet lift replicas + Headless Service
│   ├── 04-orchestrator-statefulset.yaml # Orchestrator StatefulSet + NodePort 30080 Service
│   ├── kustomization.yaml        # Kustomize manifest
│   └── deploy-all.yaml           # Consolidated all-in-one manifest
├── docker-compose.yml            # Local multi-container setup (Redis + 16 lifts + orchestrator)
├── Dockerfile                    # Multi-purpose Python 3.11 slim container image
├── requirements.txt              # FastAPI, Redis, Uvicorn, HTTPX
├── tests/                        # 23 Automated Unit Tests
│   ├── test_look_algorithm.py    # LOOK algorithm tests
│   ├── test_dispatcher.py        # Dispatcher heuristic tests
│   ├── test_models.py            # Model serialization tests
│   ├── test_redis_lua.py         # Redis concurrency and Lua tests
│   ├── test_lift_controller.py   # Controller async loop tests
│   └── test_api_endpoints.py     # API validation tests
└── README.md
```

---

## 🛠️ Quick Deployment

### Option A: Kubernetes Deployment (Recommended)

1. **Build and Tag the Docker Image**:
   ```bash
   docker build -t lift-app:latest .
   ```
   *(If using Minikube or Kind, run `eval $(minikube docker-env)` or `kind load docker-image lift-app:latest`)*

2. **Apply All Manifests**:
   ```bash
   kubectl apply -k k8s/
   # or: kubectl apply -f k8s/deploy-all.yaml
   ```

3. **Verify StatefulSets and Pods**:
   ```bash
   kubectl get statefulsets -n lift-system
   kubectl get pods -n lift-system
   ```

   Expected output:
   - `redis-0` (1/1 Running)
   - `lift-orchestrator-0` (1/1 Running)
   - `lift-service-0` through `lift-service-15` (16 pods Running)

4. **Access the Web UI**:
   - Via NodePort: `http://<node-ip>:30080`
   - Or port-forward the orchestrator service:
     ```bash
     kubectl port-forward -n lift-system svc/lift-orchestrator 8000:8000
     ```
     Then open `http://localhost:8000` in your web browser.

---

### Option B: Local Docker Compose (Single Lift for Local Dev)

For rapid local testing without spinning up a full 16-replica cluster, `docker-compose.yml` provides a streamlined 3-container environment:
1. `redis`: Durable Redis container with volume
2. `lift-orchestrator`: Orchestrator & UI dashboard
3. `lift-service`: Single lift service container (`lift-service-0`)

```bash
docker compose up --build
```

Then navigate to:
```
http://localhost:8000
```

*(Note: In Kubernetes, the application automatically scales to the full 16-replica StatefulSet `lift-service-0` through `lift-service-15` using `k8s/`)*

---

## 🧪 Running Unit Tests

The test suite covers the pure LOOK scheduling algorithm, the heuristic cost calculator, Redis Lua scripting, and model serialization:

```bash
python3 -m unittest discover -s tests
```

Output:
```
.......................
----------------------------------------------------------------------
Ran 23 tests in 0.011s

OK
```

---

## 📡 REST API Reference

### Orchestrator Service (`http://localhost:8000`)

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/requests` | Submit hall request: `{"floor": 8, "direction": "UP"}` |
| `GET` | `/api/requests` | List all pending hall requests |
| `DELETE` | `/api/requests/{floor}/{direction}` | Cancel/delete a hall request |
| `GET` | `/api/lifts` | Get live telemetry of all 16 lifts |
| `GET` | `/api/queues` | Get current floor queues of all 16 lifts |
| `POST` | `/api/dispatch` | Force an immediate dispatch evaluation cycle |
| `POST` | `/api/reset` | Reset all queues and lifts to Floor 0 IDLE |
| `GET` | `/api/config` | Read building configuration (`floor_count`, etc.) |
| `GET` | `/healthz` | Orchestrator health check probe |
| `WS` | `/ws` | Real-time WebSocket telemetry stream |

### Individual Lift Service (`http://<lift-service-N>:8000`)

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/trigger` | Start LOOK processing loop if stopped |
| `GET` | `/status` | Return current floor, direction, and state |
| `GET` | `/queue` | Return list of floors in this lift's queue |
| `GET` | `/healthz` | Lift service health check probe |

---

## 🔐 Redis Key Specifications & Concurrency

| Redis Key | Type | Description |
|---|---|---|
| `<lift-id>.service_queue` | **Hash (HashSet)** | Field: `floor` (str), Value: `timestamp`. Stores floors currently scheduled for this lift. |
| `<lift-id>.status` | **String (JSON)** | Current status: `{"floor": 7.2, "direction": 1}` or `{"floor": 9, "direction": 0}`. |
| `hall-request` | **Hash (HashSet)** | Field: `"{floor}:{direction}"`, Value: JSON request data. Stores unassigned hall requests. |
| `lift-events` | **List** | Rolling buffer of recent dispatch and arrival events for the UI. |

### Atomic Assignment Lua Script
```lua
local hall_key = KEYS[1]
local queue_key = KEYS[2]
local req_field = ARGV[1]
local floor_val = ARGV[2]
local timestamp = ARGV[3]

if redis.call('HEXISTS', hall_key, req_field) == 1 then
    redis.call('HDEL', hall_key, req_field)
    redis.call('HSET', queue_key, floor_val, timestamp)
    return 1
else
    return 0
end
```
Executed via `EVALSHA`, this guarantees that no hall request can ever be double-assigned even under heavy concurrent load.

