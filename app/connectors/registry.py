from app.connectors.base import PlatformConnector
from app.connectors.generic_api import GenericApiConnector
from app.connectors.mock import MockConnector
from app.connectors.telegram import TelegramConnector
from app.connectors.vk import VkConnector
from app.connectors.webpage import WebpageConnector

CONNECTOR_TYPES: dict[str, PlatformConnector] = {
    "mock": MockConnector(),
    "vk": VkConnector(),
    "telegram": TelegramConnector(),
    "webpage": WebpageConnector(),
    "generic_api": GenericApiConnector(),
}


def get_connector(connector_type: str) -> PlatformConnector:
    connector = CONNECTOR_TYPES.get(connector_type)
    if connector is None:
        raise ValueError(f"Неизвестный connector_type: {connector_type!r}")
    return connector
