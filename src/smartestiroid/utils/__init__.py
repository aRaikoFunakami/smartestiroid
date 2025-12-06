"""
Utility modules for SmartestiRoid test framework.
"""

from .allure_logger import (
    AllureToolCallbackHandler,
    log_openai_timeout_to_allure,
    log_openai_error_to_allure
)
from .device_info import write_device_info_once
from .structured_logger import StructuredLogger, SLog, LogCategory, LogEvent
from .log_analyzer import LogAnalyzer, LogEntry, AnalysisResult
from .failure_report_generator import (
    FailureReportGenerator,
    FailureAnalysis,
    FailedTestInfo,
)

__all__ = [
    'AllureToolCallbackHandler',
    'log_openai_timeout_to_allure',
    'log_openai_error_to_allure',
    'write_device_info_once',
    'StructuredLogger',
    'SLog',
    'LogCategory',
    'LogEvent',
    'LogAnalyzer',
    'LogEntry',
    'AnalysisResult',
    'FailureReportGenerator',
    'FailureAnalysis',
    'FailedTestInfo',
]
