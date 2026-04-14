"""Dummy views module."""

from flask import Blueprint
from flask_restx import Api, Resource

dummy = Blueprint("dummy", __name__)

api = Api(
    dummy, title="Dummy API object", description="For python-init demostration purposes"
)


@api.route("/")
class DummyResource(Resource):
    """Dummy resource."""

    # Remove this if you add more methods.
    # pylint: disable=too-few-public-methods

    @staticmethod
    def get():
        """Dummy get."""
        return "Hello World."
