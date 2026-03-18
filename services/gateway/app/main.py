import asyncio
import os
import random
import logging
from typing import Any, Dict

import httpx
from fastapi import FastAPI, HTTPException

# --- LOGGING IMPORTS ---
from app.logging_config import setup_logging
from app.middleware import StructuredLoggingMiddleware

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

SERVICE = "gateway"

# --- SETUP LOGGING FIRST ---
setup_logging()
logger = logging.getLogger(f"{SERVICE}.main")

app = FastAPI(title="Aegis Gateway")

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
        "Gateway service starting",
        extra={
            "service": SERVICE,
            "environment": os.getenv("ENVIRONMENT", "development")
        }
    )


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Gateway service shutting down", extra={"service": SERVICE})


@app.get("/")
async def root() -> Dict[str, Any]:
    await maybe_delay()
    maybe_fail()
    logger.debug("Root endpoint accessed")
    return {"service": SERVICE, "status": "ok"}


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/checkout")
async def checkout(user_id: int = 1, item_id: int = 1, force_fail: bool = False) -> Dict[str, Any]:
    await maybe_delay()
    maybe_fail()

    users_url = os.getenv("USERS_URL", "http://users:8000")
    catalog_url = os.getenv("CATALOG_URL", "http://catalog:8000")
    orders_url = os.getenv("ORDERS_URL", "http://orders:8000")

    logger.info(
        "Checkout initiated",
        extra={
            "user_id": user_id,
            "item_id": item_id,
            "force_fail": force_fail
        }
    )

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            user_resp = await client.get(f"{users_url}/profile/{user_id}")
            user_resp.raise_for_status()
            user = user_resp.json()

            item_resp = await client.get(f"{catalog_url}/items/{item_id}")
            item_resp.raise_for_status()
            item = item_resp.json()

            order_resp = await client.post(
                f"{orders_url}/orders",
                json={
                    "user_id": user_id,
                    "item_id": item_id,
                    "price": item.get("price", 0),
                    "force_fail": force_fail,
                },
            )
            order_resp.raise_for_status()
            order = order_resp.json()

            logger.info(
                "Checkout completed successfully",
                extra={
                    "user_id": user_id,
                    "item_id": item_id,
                    "order_id": order.get("order_id")
                }
            )

            return {"user": user, "item": item, "order": order}
    
    except httpx.HTTPStatusError as exc:
        logger.error(
            f"HTTP error during checkout: {exc.response.status_code}",
            extra={
                "user_id": user_id,
                "item_id": item_id,
                "error": {
                    "status_code": exc.response.status_code,
                    "url": str(exc.request.url),
                    "message": str(exc)
                }
            }
        )
        raise
    except Exception as exc:
        logger.error(
            f"Unexpected error during checkout: {str(exc)}",
            extra={
                "user_id": user_id,
                "item_id": item_id,
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc)
                }
            }
        )
        raise
