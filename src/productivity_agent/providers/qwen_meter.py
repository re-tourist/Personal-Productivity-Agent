"""Bounded, content-free provider metering; no credentials, prompts or raw replies logged."""
import json
import threading
from dataclasses import dataclass
from decimal import Decimal
from time import perf_counter

from langchain_core.utils.function_calling import convert_to_openai_tool


class QwenValidationError(RuntimeError):
    """Sanitized provider/parse failure, safe to record without the original exception."""


@dataclass(frozen=True)
class ValidationBudget:
    max_calls: int = 12
    input_per_call: int = 8000
    output_reserve: int = 610  # API docs allow up to 10 tokens above max_completion_tokens=600.
    max_cny: Decimal = Decimal("0.05")


class QwenMeter:
    """One meter per validation run; failed/unknown usage keeps its full reservation.

    Prices are the 2026-11-03 Beijing qwen3.7-flash <=32K list prices,
    not a provider billing receipt. Validation runner enforces this exact profile.
    """

    def __init__(self, model, budget=None, on_record=None):
        self.model = model
        self.budget = budget
        self.on_record = on_record
        self.records = []
        self.scenario = "unspecified"
        self.stopped = False
        self._lock = threading.Lock()

    def _invoke(self, runnable, messages, tools, *, structured=False):
        # UTF-8 bytes + framing reserve is a conservative request-size guard, NOT token usage.
        content = [m.model_dump() if hasattr(m, "model_dump") else m for m in messages]
        wire_bytes = len(json.dumps({"messages": content, "tools": tools},
                                   ensure_ascii=False, default=str).encode("utf-8")) + 1024
        with self._lock:
            if self.budget:
                b = self.budget
                reserve = Decimal(b.input_per_call) * Decimal("0.2") / 1000000
                reserve += Decimal(b.output_reserve) * Decimal("0.8") / 1000000
                if (self.stopped or len(self.records) >= b.max_calls or wire_bytes > b.input_per_call
                        or reserve * (len(self.records) + 1) > b.max_cny):
                    raise QwenValidationError("validation_budget_exhausted")
            record = {"scenario": self.scenario, "attempt": len(self.records) + 1,
                      "status": "started", "input_tokens": None, "output_tokens": None,
                      "estimated_cny": None, "latency_ms": None,
                      "reserved_estimate_cny": float(reserve) if self.budget else None}
            self.records.append(record)
            if not self.budget:
                self.records[:] = self.records[-100:]
            self._save()
        start = perf_counter()
        try:
            response = runnable.invoke(messages)
            raw = response.get("raw") if structured else response
            usage = getattr(raw, "usage_metadata", None) or {}
            incoming, outgoing = usage.get("input_tokens"), usage.get("output_tokens")
            if type(incoming) is int and type(outgoing) is int and incoming >= 0 and outgoing >= 0:
                record.update(input_tokens=incoming, output_tokens=outgoing,
                              estimated_cny=float((Decimal(incoming) * Decimal("0.2")
                                                   + Decimal(outgoing) * Decimal("0.8")) / 1000000)
                              if self.budget else None)
                if self.budget and (incoming > self.budget.input_per_call
                                    or outgoing > self.budget.output_reserve):
                    self.stopped = True
                    raise QwenValidationError("provider_usage_exceeded_reserve")
            else:
                self.stopped = True
            if structured and (response.get("parsing_error") is not None or response.get("parsed") is None):
                raise QwenValidationError("structured_output_invalid")
            record["status"] = "parsed" if structured else "received"
            return response["parsed"] if structured else response
        except Exception:  # noqa: BLE001 -- provider boundary discards unsafe SDK error text.
            self.stopped = True
            record["status"] = "failed_unknown_usage" if record["input_tokens"] is None else "failed"
            raise QwenValidationError("qwen_call_or_parse_failed") from None
        finally:
            record["latency_ms"] = round((perf_counter() - start) * 1000, 2)
            self._save()

    def _save(self):
        if self.on_record:
            self.on_record(self.records)

    def structured(self, schema):
        runnable = self.model.with_structured_output(schema, method="function_calling", include_raw=True)
        meter = self
        tool_schema = convert_to_openai_tool(schema)

        class Extractor:
            mode = "qwen"

            def invoke(self, messages):
                return meter._invoke(runnable, messages, [tool_schema], structured=True)

        return Extractor()

    def bind_tools(self, tools):
        runnable = self.model.bind_tools(tools, parallel_tool_calls=False)
        schemas = [convert_to_openai_tool(t) for t in tools]
        meter = self

        class Bound:
            def invoke(self, messages):
                return meter._invoke(runnable, messages, schemas)

        return Bound()
