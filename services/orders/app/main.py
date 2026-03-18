import asyncio
import os
import random
import time
import logging
from typing import Any, Dict

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# --- LOGGING IMPORTS ---
from app.logging_config import setup_logging
from app.middleware import StructuredLoggingMiddleware
from app.db import Database

# --- TRACING IMPORTS ---
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# --- METRICS IMPORTS ---
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

SERVICE = "orders"

# --- SETUP LOGGING FIRST ---
setup_logging()
logger = logging.getLogger(f"{SERVICE}.main")

app = FastAPI(title="Orders Service")

# --- Add structured logging middleware ---
app.add_middleware(StructuredLoggingMiddleware)

# Resource for both tracing and metrics
resource = Resource.create(
    attributes={
        SERVICE_NAME: os.getenv("OTEL_SERVICE_NAME", SERVICE),
        "service.instance.id": os.getenv("HOSTNAME")
    }
)


def setup_tracing() -> None:
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter()
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    logger.info("Tracing initialized", extra={"component": "opentelemetry"})


def setup_metrics() -> None:
    otlp_metric_exporter = OTLPMetricExporter(
        endpoint=os.getenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "http://otel-collector:4317"),
        insecure=True
    )
    metric_reader = PeriodicExportingMetricReader(
        otlp_metric_exporter,
        export_interval_millis=5000
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)
    logger.info("Metrics initialized", extra={"component": "opentelemetry"})


setup_tracing()
setup_metrics()

# Instrument FastAPI for both traces and metrics
FastAPIInstrumentor.instrument_app(
    app, 
    tracer_provider=trace.get_tracer_provider(), 
    meter_provider=metrics.get_meter_provider()
)

# Instrument HTTPX for metrics and traces
HTTPXClientInstrumentor().instrument(meter_provider=metrics.get_meter_provider())


class OrderRequest(BaseModel):
    user_id: int
    item_id: int
    price: float
    force_fail: bool = False


async def maybe_delay() -> None:
    delay_ms = float(os.getenv("REQUEST_DELAY_MS", "0"))
    if delay_ms > 0:
        await asyncio.sleep(delay_ms / 1000.0)


def maybe_fail() -> None:
    rate = float(os.getenv("FAIL_RATE", "0"))
    if rate > 0 and random.random() < rate:
        logger.warning("Simulated failure triggered", extra={"fail_rate": rate})
        raise HTTPException(status_code=500, detail="simulated failure")


@app.on_event("startup")
async def startup_event():
    logger.info(
        "Orders service starting",
        extra={
            "service": SERVICE,
            "environment": os.getenv("ENVIRONMENT", "development")
        }
    )
    await Database.connect(SERVICE)


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Orders service shutting down", extra={"service": SERVICE})
    await Database.disconnect()


@app.get("/")
async def root() -> Dict[str, Any]:
    await maybe_delay()
    maybe_fail()
    logger.debug("Root endpoint accessed")
    return {"service": SERVICE, "status": "ok"}


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/orders")
async def create_order(order: OrderRequest) -> Dict[str, Any]:
    await maybe_delay()
    maybe_fail()

    order_id = f"ord-{int(time.time() * 1000)}-{order.user_id}"
    payments_url = os.getenv("PAYMENTS_URL", "http://payments:8000")

    logger.info(
        "Creating order",
        extra={
            "order_id": order_id,
            "user_id": order.user_id,
            "item_id": order.item_id,
            "amount": order.price,
            "force_fail": order.force_fail
        }
    )

    # Insert order into DB with pending status
    await Database.execute(
        "INSERT INTO orders (id, user_id, item_id, amount, status) VALUES ($1, $2, $3, $4, $5)",
        order_id, order.user_id, order.item_id, order.price, "pending",
    )

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            pay_resp = await client.post(
                f"{payments_url}/charge",
                json={
                    "order_id": order_id,
                    "amount": order.price,
                    "force_fail": order.force_fail,
                },
            )
            pay_resp.raise_for_status()
            payment = pay_resp.json()

        # Update order status to paid
        await Database.execute(
            "UPDATE orders SET status = $1, updated_at = NOW() WHERE id = $2",
            "paid", order_id,
        )

        logger.info(
            "Order created successfully",
            extra={
                "order_id": order_id,
                "user_id": order.user_id,
                "item_id": order.item_id,
                "amount": order.price,
                "payment_status": payment.get("status")
            }
        )

        return {
            "order_id": order_id,
            "user_id": order.user_id,
            "item_id": order.item_id,
            "amount": order.price,
            "payment": payment,
            "status": "paid",
        }

    except httpx.HTTPStatusError as exc:
        # Update order status to failed
        await Database.execute(
            "UPDATE orders SET status = $1, updated_at = NOW() WHERE id = $2",
            "failed", order_id,
        )
        logger.error(
            f"Payment service error: {exc.response.status_code}",
            extra={
                "order_id": order_id,
                "user_id": order.user_id,
                "error": {
                    "status_code": exc.response.status_code,
                    "url": str(exc.request.url),
                    "message": str(exc)
                }
            }
        )
        raise
    except Exception as exc:
        await Database.execute(
            "UPDATE orders SET status = $1, updated_at = NOW() WHERE id = $2",
            "failed", order_id,
        )
        logger.error(
            f"Unexpected error creating order: {str(exc)}",
            extra={
                "order_id": order_id,
                "user_id": order.user_id,
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc)
                }
            }
        )
        raise


@app.get("/orders/{order_id}")
async def get_order(order_id: str) -> Dict[str, Any]:
    await maybe_delay()
    maybe_fail()

    row = await Database.fetch_one(
        "SELECT id, user_id, item_id, amount, status, created_at, updated_at FROM orders WHERE id = $1",
        order_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")

    logger.info("Order retrieved", extra={"order_id": order_id, "status": row["status"]})

    return {
        "order_id": row["id"],
        "user_id": row["user_id"],
        "item_id": row["item_id"],
        "amount": float(row["amount"]),
        "status": row["status"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }
