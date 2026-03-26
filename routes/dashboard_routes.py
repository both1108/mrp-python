from flask import Blueprint, jsonify
from services.dashboard_service import build_dashboard_data

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/api/dashboard")
def api_dashboard():
    return jsonify(build_dashboard_data())