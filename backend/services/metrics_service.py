from __future__ import annotations

import threading
from collections import defaultdict
from typing import Dict, Iterable, Tuple

_lock = threading.Lock()
_counters: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = defaultdict(float)
_seconds_sum: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = defaultdict(float)
_seconds_count: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = defaultdict(float)


def _norm_labels(labels: Dict[str, object]) -> Tuple[Tuple[str, str], ...]:
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))


def _inc(store, name: str, labels: Dict[str, object], value: float = 1.0) -> None:
    key = (name, _norm_labels(labels))
    with _lock:
        store[key] += float(value)


def observe_duration(name: str, seconds: float, labels: Dict[str, object]) -> None:
    key = (name, _norm_labels(labels))
    with _lock:
        _seconds_sum[key] += float(seconds)
        _seconds_count[key] += 1.0


def increment_counter(name: str, labels: Dict[str, object], value: float = 1.0) -> None:
    _inc(_counters, name, labels, value)


def record_llm_call(
    provider: str,
    status: str,
    elapsed_seconds: float,
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
) -> None:
    labels = {"provider": provider or "unknown", "status": status}
    increment_counter("ainovel_llm_request_total", labels, 1)
    observe_duration("ainovel_llm_request_seconds", elapsed_seconds, labels)
    if prompt_tokens:
        increment_counter("ainovel_llm_prompt_tokens_total", {"provider": provider or "unknown"}, prompt_tokens)
    if completion_tokens:
        increment_counter("ainovel_llm_completion_tokens_total", {"provider": provider or "unknown"}, completion_tokens)
    if total_tokens:
        increment_counter("ainovel_llm_total_tokens_total", {"provider": provider or "unknown"}, total_tokens)


def record_image_call(provider: str, status: str, elapsed_seconds: float) -> None:
    labels = {"provider": provider or "unknown", "status": status}
    increment_counter("ainovel_image_request_total", labels, 1)
    observe_duration("ainovel_image_request_seconds", elapsed_seconds, labels)


def record_task_finished(kind: str, final_state: str) -> None:
    increment_counter(
        "ainovel_task_finished_total",
        {"kind": kind or "unknown", "final_state": final_state or "unknown"},
        1,
    )


def _format_labels(labels: Iterable[Tuple[str, str]]) -> str:
    pairs = [f'{key}="{value}"' for key, value in labels]
    return f'{{{",".join(pairs)}}}' if pairs else ""


def render_metrics() -> str:
    lines = []
    with _lock:
        counter_items = list(_counters.items())
        duration_sum_items = list(_seconds_sum.items())
        duration_count_items = list(_seconds_count.items())

    seen_types = set()
    for (name, labels), value in counter_items:
        if name not in seen_types:
            lines.append(f"# TYPE {name} counter")
            seen_types.add(name)
        lines.append(f"{name}{_format_labels(labels)} {value}")

    seen_summaries = set()
    for (name, labels), value in duration_sum_items:
        if name not in seen_summaries:
            lines.append(f"# TYPE {name} summary")
            seen_summaries.add(name)
        lines.append(f"{name}_sum{_format_labels(labels)} {value}")
        count = duration_count_items.get((name, labels), 0.0)
        lines.append(f"{name}_count{_format_labels(labels)} {count}")

    return "\n".join(lines) + "\n"
