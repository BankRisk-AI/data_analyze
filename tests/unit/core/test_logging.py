import logging

from app.core.logging import LoggerService, configure_logging


def test_logger_service_preserves_exception_traceback(caplog):
    configure_logging()
    with caplog.at_level(logging.DEBUG):
        try:
            raise RuntimeError("traceback sentinel")
        except RuntimeError:
            LoggerService("tests.logging").exception("operation failed")

    record = next(record for record in caplog.records if record.name == "tests.logging")
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None
    assert "traceback sentinel" in caplog.text
