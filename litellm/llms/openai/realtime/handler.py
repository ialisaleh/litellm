"""
This file contains the calling Azure OpenAI's `/openai/realtime` endpoint.

This requires websockets, and is currently only supported on LiteLLM Proxy.
"""

from typing import Any, Optional, cast

from ....litellm_core_utils.litellm_logging import Logging as LiteLLMLogging
from ....litellm_core_utils.realtime_streaming import RealTimeStreaming
from ..openai import OpenAIChatCompletion
from litellm.types.realtime import RealtimeQueryParams


class OpenAIRealtime(OpenAIChatCompletion):
    def _construct_url(self, api_base: str, query_params: RealtimeQueryParams) -> str:
        """
        Construct the backend websocket URL with all query parameters (excluding 'model' if present).
        """
        from httpx import URL

        api_base = api_base.replace("https://", "wss://")
        api_base = api_base.replace("http://", "ws://")
        url = URL(api_base)
        # Set the correct path
        url = url.copy_with(path="/v1/realtime")
        # Build query dict excluding 'model'
        query_dict = {k: v for k, v in query_params.items() if k != "model"}
        if query_dict:
            url = url.copy_with(params=query_dict)
        return str(url)

    async def async_realtime(
        self,
        model: str,
        websocket: Any,
        logging_obj: LiteLLMLogging,
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
        client: Optional[Any] = None,
        timeout: Optional[float] = None,
        query_params: Optional[RealtimeQueryParams] = None,
    ):
        import websockets
        from websockets.asyncio.client import ClientConnection

        if api_base is None:
            raise ValueError("api_base is required for Azure OpenAI calls")
        if api_key is None:
            raise ValueError("api_key is required for Azure OpenAI calls")

        # Use all query params if provided, else fallback to just model
        if query_params is None:
            query_params = {"model": model}
        url = self._construct_url(api_base, query_params)

        try:
            async with websockets.connect(  # type: ignore
                url,
                extra_headers={
                    "Authorization": f"Bearer {api_key}",  # type: ignore
                    "OpenAI-Beta": "realtime=v1",
                },
            ) as backend_ws:
                realtime_streaming = RealTimeStreaming(
                    websocket, cast(ClientConnection, backend_ws), logging_obj
                )
                await realtime_streaming.bidirectional_forward()

        except websockets.exceptions.InvalidStatusCode as e:  # type: ignore
            await websocket.close(code=e.status_code, reason=str(e))
        except Exception as e:
            try:
                await websocket.close(
                    code=1011, reason=f"Internal server error: {str(e)}"
                )
            except RuntimeError as close_error:
                if "already completed" in str(close_error) or "websocket.close" in str(
                    close_error
                ):
                    # The WebSocket is already closed or the response is completed, so we can ignore this error
                    pass
                else:
                    # If it's a different RuntimeError, we might want to log it or handle it differently
                    raise Exception(
                        f"Unexpected error while closing WebSocket: {close_error}"
                    )
