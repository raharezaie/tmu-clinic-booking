"""TMU Clinic Booking System - Sprint 1.

Run:  flask --app app run --debug
"""
import os

from flask import Flask, g, redirect, render_template, url_for

import admin
import auth
import booking
import db


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
        DATABASE=os.path.join(app.root_path, "clinic.db"),
        ADMIN_INVITE_CODE=os.environ.get("ADMIN_INVITE_CODE", "TMU-STAFF-2026"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if test_config:
        app.config.update(test_config)

    db.init_app(app)
    app.register_blueprint(auth.bp)
    app.register_blueprint(booking.bp)
    app.register_blueprint(admin.bp)
    app.jinja_env.globals["csrf_token"] = auth.csrf_token

    @app.route("/")
    def index():
        if g.user:
            return redirect(auth.home_for(g.user))
        return redirect(url_for("auth.login"))

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("error.html", title="No access",
                               message="Your account doesn't have access to that page."), 403

    @app.errorhandler(400)
    def bad_request(e):
        return render_template("error.html", title="Something went wrong", message=e.description), 400

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", title="Page not found",
                               message="Check the address, or use the links above."), 404

    return app


app = create_app()
