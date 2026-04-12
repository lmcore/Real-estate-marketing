"""Forecaster module — profit-margin calculation for buy-renovate-sell projects."""

from shadow_tester.forecaster.engine import calculate_forecast
from shadow_tester.forecaster.models import ForecastParams, ForecastResult
from shadow_tester.forecaster.repo import (
    delete_forecast,
    get_forecast,
    list_forecasts,
    save_forecast,
)

__all__ = [
    "ForecastParams",
    "ForecastResult",
    "calculate_forecast",
    "delete_forecast",
    "get_forecast",
    "list_forecasts",
    "save_forecast",
]
