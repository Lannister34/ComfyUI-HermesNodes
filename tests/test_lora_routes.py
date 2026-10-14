import asyncio

from hermes_nodes.nodes.wan_dual_lora import routes as lora_routes


class FakeRequest:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


def test_find_match_rejects_a_non_string_lora_name():
    request = FakeRequest({"lora_name": ["x"], "source_type": "high"})
    response = asyncio.run(lora_routes.find_match(request))
    assert response.status == 400
