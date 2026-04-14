"""Run flask app."""

# pylint: disable=import-outside-toplevel

import os

import newrelic.agent

# Initialize newrelic agent before importing anything else
# The newrelic config file is hardcoded because we can't import nothing before this :-(
newrelic.agent.initialize(f"{os.getcwd()}/newrelic.ini")


from . import create_app  # noqa: E402

app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080, debug=os.getenv("FLASK_DEBUG", "0") == "1")
