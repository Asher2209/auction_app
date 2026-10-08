"""Logging configuration for production deployment."""

import logging
import logging.handlers
from pathlib import Path


def setup_logging(app):
    """Configure logging for Flask application."""
    # Create logs directory
    log_dir = Path(app.root_path).parent / 'logs'
    log_dir.mkdir(exist_ok=True)
    
    if app.logger.handlers:
        for handler in app.logger.handlers[:]:
            app.logger.removeHandler(handler)
    
    app.logger.setLevel(logging.DEBUG if app.debug else logging.INFO)
    
    # ---- Transaction Log ----
    transaction_handler = logging.handlers.RotatingFileHandler(
        log_dir / 'transactions.log',
        maxBytes=10 * 1024 * 1024,
        backupCount=10
    )
    transaction_handler.setLevel(logging.INFO)
    transaction_formatter = logging.Formatter(
        '%(asctime)s | %(name)s | %(levelname)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    transaction_handler.setFormatter(transaction_formatter)
    
    blockchain_logger = logging.getLogger('app.services.blockchain_service')
    blockchain_logger.addHandler(transaction_handler)
    blockchain_logger.setLevel(logging.INFO)
    
    # ---- Blockchain Errors Log ----
    blockchain_error_handler = logging.handlers.RotatingFileHandler(
        log_dir / 'blockchain_errors.log',
        maxBytes=10 * 1024 * 1024,
        backupCount=10
    )
    blockchain_error_handler.setLevel(logging.ERROR)
    blockchain_error_formatter = logging.Formatter(
        '%(asctime)s | %(name)s | %(levelname)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    blockchain_error_handler.setFormatter(blockchain_error_formatter)
    app.logger.addHandler(blockchain_error_handler)
    
    # ---- General App Log ----
    app_handler = logging.handlers.RotatingFileHandler(
        log_dir / 'app.log',
        maxBytes=20 * 1024 * 1024,
        backupCount=10
    )
    app_handler.setLevel(logging.DEBUG if app.debug else logging.INFO)
    app_formatter = logging.Formatter(
        '%(asctime)s | %(name)s | %(levelname)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    app_handler.setFormatter(app_formatter)
    app.logger.addHandler(app_handler)
    
    # Set library log levels
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('web3').setLevel(logging.WARNING)
    
    app.logger.info("=" * 80)
    app.logger.info(f"LOGGING INITIALIZED | Environment: {app.config.get('APP_ENV', 'development')}")
    app.logger.info(f"Log directory: {log_dir}")
    app.logger.info("=" * 80)


def get_transaction_logger() -> logging.Logger:
    """Get logger for blockchain transaction events"""
    return logging.getLogger('app.services.blockchain_service')


def get_blockchain_error_logger() -> logging.Logger:
    """Get logger for blockchain errors"""
    return logging.getLogger('app.services.blockchain_service_enhanced')


def get_payment_logger() -> logging.Logger:
    """Get logger for payment operations"""
    return logging.getLogger('app.services.payment')
