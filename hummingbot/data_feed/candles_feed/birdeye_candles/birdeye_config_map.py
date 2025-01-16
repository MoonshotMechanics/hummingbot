from pydantic import Field, SecretStr
from hummingbot.client.config.config_data_types import (
    BaseConnectorConfigMap,
    ClientFieldData,
)


class BirdeyeConfigMap(BaseConnectorConfigMap):
    connector: str = Field(default="birdeye", const=True, client_data=None)
    birdeye_api_key: SecretStr = Field(
        default=...,
        client_data=ClientFieldData(
            prompt=lambda cm: "Enter your Birdeye API key",
            is_secure=True,
            is_connect_key=True,
            prompt_on_new=True,
        ),
    )

    class Config:
        title = "birdeye"


KEYS = BirdeyeConfigMap.construct()
