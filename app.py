from flask import Flask, render_template
from routes.dashboard_routes import dashboard_bp


def create_app():
    app = Flask(__name__)
    app.register_blueprint(dashboard_bp)

    @app.route("/")
    def index():
        return render_template("index.html")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, use_reloader=False, host="0.0.0.0", port=5000)