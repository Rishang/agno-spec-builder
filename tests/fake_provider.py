from agno.models.base import Model


class FakeModel(Model):
    def __init__(self, id: str, reasoning_effort=None, **kwargs):
        super().__init__(id=id, **kwargs)
        self.reasoning_effort = reasoning_effort

    def invoke(self, *args, **kwargs):
        raise NotImplementedError

    async def ainvoke(self, *args, **kwargs):
        raise NotImplementedError

    def invoke_stream(self, *args, **kwargs):
        if False:
            yield None

    async def ainvoke_stream(self, *args, **kwargs):
        if False:
            yield None

    def _parse_provider_response(self, *args, **kwargs):
        raise NotImplementedError

    def _parse_provider_response_delta(self, *args, **kwargs):
        raise NotImplementedError
