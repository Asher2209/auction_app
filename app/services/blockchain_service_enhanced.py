"""Enhanced blockchain service with comprehensive error handling and logging."""

import logging
import time
from typing import Optional, Dict, Any
from functools import wraps
from decimal import Decimal

from flask import current_app
from web3.exceptions import TransactionNotFound, BlockNotFound
from web3 import Web3

logger = logging.getLogger(__name__)

DEFAULT_RETRIES = 3
DEFAULT_BACKOFF_BASE = 2
DEFAULT_TIMEOUT = 30


class BlockchainError(Exception):
    """Base exception for blockchain operations"""
    def __init__(self, message: str, status: int = 500, original_error: Exception = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.original_error = original_error


class RPCError(BlockchainError):
    """RPC connectivity or response error"""
    pass


class TransactionError(BlockchainError):
    """Transaction-specific error"""
    pass


class ValidationError(BlockchainError):
    """Input validation error"""
    pass


def retry_with_backoff(max_retries=DEFAULT_RETRIES, base_delay=DEFAULT_BACKOFF_BASE):
    """Decorator for automatic retry with exponential backoff."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (TransactionNotFound, BlockNotFound) as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        delay = base_delay ** attempt
                        logger.warning(
                            f"Attempt {attempt + 1}/{max_retries} failed for {func.__name__}: {str(e)}. "
                            f"Retrying in {delay}s..."
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            f"All {max_retries} attempts failed for {func.__name__}: {str(e)}"
                        )
                except Exception as e:
                    logger.error(f"Non-retryable error in {func.__name__}: {str(e)}", exc_info=True)
                    raise
            
            if last_error:
                raise RPCError(
                    f"Transaction operation timed out after {max_retries} attempts. "
                    f"Please try again later.",
                    status=503,
                    original_error=last_error
                )
        
        return wrapper
    return decorator


def handle_rpc_errors(func):
    """Decorator to catch and log RPC errors with user-friendly messages."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (ConnectionError, TimeoutError) as e:
            logger.error(f"RPC connection error in {func.__name__}: {str(e)}", exc_info=True)
            raise RPCError(
                "Unable to connect to blockchain network. Please try again later.",
                status=503,
                original_error=e
            )
        except ValidationError as e:
            logger.warning(f"Validation error in {func.__name__}: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in {func.__name__}: {str(e)}", exc_info=True)
            raise RPCError(
                "An unexpected error occurred while processing your blockchain request. "
                "Please contact support if this continues.",
                status=500,
                original_error=e
            )
    return wrapper


def log_transaction_event(tx_hash: str, event_type: str, details: Dict[str, Any]):
    """Log a blockchain transaction event for audit trail."""
    logger.info(f"BLOCKCHAIN_EVENT | type={event_type} | tx={tx_hash[:10] if tx_hash else 'pending'}... | details={details}")


def log_blockchain_error(error_type: str, details: Dict[str, Any], user_id: Optional[int] = None):
    """Log a blockchain error for monitoring."""
    log_msg = f"BLOCKCHAIN_ERROR | type={error_type} | details={details}"
    if user_id:
        log_msg += f" | user={user_id}"
    logger.error(log_msg)
