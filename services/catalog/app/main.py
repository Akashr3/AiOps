import asyncio
import os
import random
import logging
from typing import Any, Dict

from fastapi import FastAPI, HTTPException

# --- LOGGING IMPORTS ---
from app.logging_config import setup_logging
from app.middleware import StructuredLoggingMiddleware
from app.db import Database

# --- TRACING IMPORTS ---
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# --- METRICS IMPORTS ---
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

SERVICE = "catalog"

# --- SETUP LOGGING FIRST (before FastAPI app creation) ---
setup_logging()
logger = logging.getLogger(f"{SERVICE}.main")

app = FastAPI(title="Catalog Service")

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
        "Catalog service starting",
        extra={
            "service": SERVICE,
            "environment": os.getenv("ENVIRONMENT", "development")
        }
    )
    await Database.connect(SERVICE)


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Catalog service shutting down", extra={"service": SERVICE})
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


@app.get("/items/{item_id}")
async def item(item_id: int) -> Dict[str, Any]:
    await maybe_delay()
    maybe_fail()

    row = await Database.fetch_one(
        "SELECT id, name, price, category, in_stock FROM catalog_items WHERE id = $1",
        item_id,
    )
    if not row:
        logger.warning("Item not found", extra={"item_id": item_id})
        raise HTTPException(status_code=404, detail=f"Item {item_id} not found")

    logger.info(
        "Item retrieved",
        extra={
            "item_id": row["id"],
            "price": float(row["price"]),
            "category": row["category"],
        }
    )

    return {
        "item_id": row["id"],
        "name": row["name"],
        "price": float(row["price"]),
        "category": row["category"],
        "in_stock": row["in_stock"],
    }
