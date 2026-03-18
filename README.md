# Aegis-K8s Sample Microservices (App Code Only)

This repo contains five minimal Python FastAPI microservices with OpenTelemetry tracing wired in. It is just application code + Dockerfiles (no Kubernetes/observability stack manifests).

## Services
- `gateway`: entrypoint; calls users, catalog, orders
- `users`: basic profile lookup
- `catalog`: item + price lookup
- `orders`: creates an order and calls payments
- `payments`: simulates a charge

## OpenTelemetry (OTEL)
Tracing is enabled in each service using the OTLP HTTP exporter. Set your collector endpoint via `OTEL_EXPORTER_OTLP_ENDPOINT` (for example, `http://otel-collector:4318/v1/traces`).

Each service also respects:
- `OTEL_SERVICE_NAME` (optional override)
- `REQUEST_DELAY_MS` (simulate latency)
- `FAIL_RATE` (0.0 to 1.0, simulate random 5xx)

## Service-specific env vars
- `gateway`:
  - `USERS_URL` (default `http://users:8000`)
  - `CATALOG_URL` (default `http://catalog:8000`)
  - `ORDERS_URL` (default `http://orders:8000`)
- `orders`:
  - `PAYMENTS_URL` (default `http://payments:8000`)

## Endpoints
- `gateway`
  - `GET /checkout?user_id=1&item_id=1&force_fail=false`
- `users`
  - `GET /profile/{user_id}`
- `catalog`
  - `GET /items/{item_id}`
- `orders`
  - `POST /orders` (JSON: `user_id`, `item_id`, `price`, `force_fail`)
- `payments`
  - `POST /charge` (JSON: `order_id`, `amount`, `force_fail`)

## Build a service image
Example (gateway):

```bash
docker build -t aegis-gateway ./services/gateway
```

## Run locally (no collector)
Each service runs on port 8000 inside the container. You can override ports as needed when running locally.

```bash
docker build -t aegis-users ./services/users
docker run --rm -p 8001:8000 --name users aegis-users
```

If you want traces, set `OTEL_EXPORTER_OTLP_ENDPOINT` to your collector.





(Think)

1) Find scenarios of pod/Node failures in production , How can we fix it without stretching budget.
2) Need to find each scenario and its solutions.
3) differnce between predictive scaling and Event based scaling 


(Concepts)
- Kubernetes
- Istio service mesh 
- Elasticcloud (Anomaly detection)
	- Single metric job
	- multi metrics job 
- Helm 
- Gitlab 
- KEDA / HPA 
- Circuit Breaking pattern 






(A) Phase 1

1) Containerize all the services 
2) first run  using docker-compose 
3) Run using kubernetes 
4) integrate elasticcloud , prometheus , elastic-cloud , grafana , Newrelic


(B) Phase 2 

1) Test scenarios of pod failure in current cluster (eg increase CPU usage , decreasing pod limits )
2) Find metrics that can be used for Event based autoscaling , APM , predictive scaling , Monitroing and tracing of application 
3) Document all the scenarios with solution 
4) Test the solution 
