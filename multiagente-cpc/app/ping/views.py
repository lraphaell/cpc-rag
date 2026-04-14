"""Module with ping endpoint."""
import newrelic.agent
from flask import Blueprint


ping = Blueprint("ping", __name__)


@ping.route("/ping")
def main():
    """Ping endpoint, used to know if the app is up."""
    newrelic.agent.ignore_transaction(flag=True)
    return "pong"
