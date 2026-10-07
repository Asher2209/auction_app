"""Health check and monitoring endpoints."""

from flask import Blueprint, jsonify, current_app
from app.utils.monitoring import get_health_checker, get_metrics_collector

bp = Blueprint("health", __name__, url_prefix="/api/health")


@bp.route("/ready", methods=["GET"])
def readiness_check():
    """Readiness check - is the app ready to serve requests?"""
    checker = get_health_checker()
    health = checker.check_all()
    
    status_code = 200 if health["overall"] == "healthy" else 503
    return jsonify(health), status_code


@bp.route("/live", methods=["GET"])
def liveness_check():
    """Liveness check - is the app running?"""
    return jsonify({
        "status": "alive",
        "version": current_app.config.get("VERSION", "1.0.0")
    }), 200


@bp.route("/metrics", methods=["GET"])
def get_metrics():
    """Get recent metrics."""
    collector = get_metrics_collector()
    stats = collector.get_stats(minutes=60)
    return jsonify(stats), 200


@bp.route("/metrics/summary", methods=["GET"])
def get_metrics_summary():
    """Get metrics summary with alerts."""
    collector = get_metrics_collector()
    checker = get_health_checker()
    
    metrics = collector.get_metrics(minutes=60)
    health = checker.check_all()
    
    # Count transaction types
    success_count = len([m for m in metrics if m.metric_type == "tx_success"])
    failure_count = len([m for m in metrics if m.metric_type == "tx_failure"])
    
    return jsonify({
        "health": health,
        "transactions": {
            "success": success_count,
            "failure": failure_count,
            "success_rate": success_count / (success_count + failure_count) if (success_count + failure_count) > 0 else 0
        },
        "metrics": collector.get_stats(minutes=60)
    }), 200


def init_health_endpoints(app):
    """Initialize health check endpoints."""
    app.register_blueprint(bp)
    current_app.logger.info("Health check endpoints registered")
