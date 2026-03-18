import asyncio
import os
import random
import logging
from typing import Any, Dict

import uuid

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
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# --- METRICS IMPORTS ---
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

SERVICE = "payments"

# --- SETUP LOGGING FIRST ---
setup_logging()
logger = logging.getLogger(f"{SERVICE}.main")

app = FastAPI(title="Payments Service")

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


class ChargeRequest(BaseModel):
    order_id: str
    amount: float
    force_fail: bool = False


async def maybe_delay() -> None:
    delay_ms = float(os.getenv("REQUEST_DELAY_MS", "0"))
    if delay_ms > 0:
        await asyncio.sleep(delay_ms / 1000.0)


def maybe_fail(force_fail: bool = False) -> None:
    if force_fail:
        logger.warning(
            "Forced payment failure triggered",
            extra={"force_fail": True}
        )
        raise HTTPException(status_code=500, detail="forced payment failure")
    rate = float(os.getenv("FAIL_RATE", "0"))
    if rate > 0 and random.random() < rate:
        logger.warning("Simulated failure triggered", extra={"fail_rate": rate})
        raise HTTPException(status_code=500, detail="simulated failure")


@app.on_event("startup")
async def startup_event():
    logger.info(
        "Payments service starting",
        extra={
            "service": SERVICE,
            "environment": os.getenv("ENVIRONMENT", "development")
        }
    )
    await Database.connect(SERVICE)


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Payments service shutting down", extra={"service": SERVICE})
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


@app.post("/charge")
async def charge(request: ChargeRequest) -> Dict[str, Any]:
    await maybe_delay()

    payment_id = f"pay-{uuid.uuid4().hex[:12]}"

    logger.info(
        "Processing payment charge",
        extra={
            "payment_id": payment_id,
            "order_id": request.order_id,
            "amount": request.amount,
            "force_fail": request.force_fail
        }
    )

    try:
        maybe_fail(request.force_fail)

        # Record approved payment in DB
        await Database.execute(
            "INSERT INTO payments (id, order_id, amount, status) VALUES ($1, $2, $3, $4)",
            payment_id, request.order_id, request.amount, "approved",
        )

        logger.info(
            "Payment approved",
            extra={
                "payment_id": payment_id,
                "order_id": request.order_id,
                "amount": request.amount,
                "status": "approved"
            }
        )

        return {
            "payment_id": payment_id,
            "order_id": request.order_id,
            "amount": request.amount,
            "status": "approved",
        }

    except HTTPException as exc:
        # Record declined payment in DB
        await Database.execute(
            "INSERT INTO payments (id, order_id, amount, status) VALUES ($1, $2, $3, $4)",
            payment_id, request.order_id, request.amount, "declined",
        )

        logger.error(
            f"Payment failed: {exc.detail}",
            extra={
                "payment_id": payment_id,
                "order_id": request.order_id,
                "amount": request.amount,
                "error": {
                    "status_code": exc.status_code,
                    "detail": exc.detail
                }
            }
        )
        raise
