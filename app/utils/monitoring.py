"""Monitoring and metrics collection for blockchain auction system."""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List
from dataclasses import dataclass
from enum import Enum

from flask import current_app
from ..extensions import db

logger = logging.getLogger(__name__)


class MetricType(Enum):
    """Types of metrics tracked"""
    TRANSACTION_SUCCESS = "tx_success"
    TRANSACTION_FAILURE = "tx_failure"
    RPC_ERROR = "rpc_error"
    VALIDATION_ERROR = "validation_error"
    GAS_USAGE = "gas_usage"
    CONFIRMATION_TIME = "confirmation_time"


@dataclass
class Metric:
    """Individual metric data point"""
    timestamp: datetime
    metric_type: str
    value: float
    tags: Dict[str, str]


class MetricsCollector:
    """Collects and stores metrics for monitoring."""
    
    def __init__(self):
        self.metrics = []
        self.max_metrics = 10000
    
    def record(self, metric_type: MetricType, value: float, tags: Dict = None):
        """Record a metric data point."""
        tags = tags or {}
        metric = Metric(
            timestamp=datetime.utcnow(),
            metric_type=metric_type.value,
            value=value,
            tags=tags
        )
        self.metrics.append(metric)
        
        if len(self.metrics) > self.max_metrics:
            self.metrics = self.metrics[-self.max_metrics:]
    
    def get_metrics(self, metric_type: MetricType = None, minutes: int = 60) -> List:
        """Get metrics from last N minutes."""
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        results = [m for m in self.metrics if m.timestamp >= cutoff]
        
        if metric_type:
            results = [m for m in results if m.metric_type == metric_type.value]
        
        return results
    
    def get_stats(self, minutes: int = 60) -> Dict:
        """Get aggregated statistics for the time window."""
        metrics = self.get_metrics(minutes=minutes)
        
        if not metrics:
            return {"error": "No metrics"}
        
        by_type = {}
        for metric in metrics:
            if metric.metric_type not in by_type:
                by_type[metric.metric_type] = []
            by_type[metric.metric_type].append(metric.value)
        
        stats = {}
        for metric_type, values in by_type.items():
            stats[metric_type] = {
                "count": len(values),
                "sum": sum(values),
                "avg": sum(values) / len(values) if values else 0,
                "min": min(values) if values else 0,
                "max": max(values) if values else 0,
            }
        
        return {"window_minutes": minutes, "metrics": stats}


class HealthChecker:
    """Checks system health and availability."""
    
    def check_database(self) -> Dict:
        """Check database connectivity."""
        try:
            db.session.execute(db.text("SELECT 1"))
            return {"status": "healthy", "component": "database"}
        except Exception as e:
            logger.error(f"Database check failed: {str(e)}")
            return {"status": "unhealthy", "component": "database", "error": str(e)}
    
    def check_rpc(self) -> Dict:
        """Check RPC node connectivity."""
        try:
            from .blockchain_service import get_web3
            
            w3 = get_web3()
            if not w3:
                return {"status": "unavailable", "component": "rpc"}
            
            block_number = w3.eth.block_number
            return {
                "status": "healthy",
                "component": "rpc",
                "block_number": block_number
            }
        except Exception as e:
            logger.error(f"RPC check failed: {str(e)}")
            return {"status": "unhealthy", "component": "rpc", "error": str(e)}
    
    def check_contract(self) -> Dict:
        """Check smart contract is accessible."""
        try:
            from .blockchain_service import crypto_enabled
            
            if not crypto_enabled():
                return {"status": "unavailable", "component": "contract"}
            
            addr = current_app.config.get("CONTRACT_ADDRESS", "N/A")
            return {"status": "healthy", "component": "contract", "address": addr[:10]}
        except Exception as e:
            return {"status": "unhealthy", "component": "contract", "error": str(e)}
    
    def check_all(self) -> Dict:
        """Check all system components."""
        checks = {
            "database": self.check_database(),
            "rpc": self.check_rpc(),
            "contract": self.check_contract()
        }
        
        all_healthy = all(c.get("status") == "healthy" for c in checks.values())
        
        return {
            "overall": "healthy" if all_healthy else "degraded",
            "components": checks
        }


# Global instances
metrics_collector = MetricsCollector()
health_checker = HealthChecker()
