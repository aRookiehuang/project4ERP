import httpx
import pytest

from backend.app.errors import DomainError
from backend.app.llm import PlannerAdapter


@pytest.mark.asyncio
async def test_api_adapter_contract(config):
    config.model_mode = "api"
    config.model_api_key = "test-key"
    adapter = PlannerAdapter(config)
    await adapter.client.aclose()
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": '{"metrics":["sales_amount"],"time_range":{"start":"2026-09-01","end":"2026-10-01"}}'
                        },
                    }
                ],
                "usage": {"total_tokens": 42},
            },
        )

    adapter.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    plan, metadata = await adapter.plan("2026年9月销售额", [], "2026-10-14")
    assert plan.metrics == ["sales_amount"] and metadata["tokens"]["total_tokens"] == 42
    assert len(seen) == 1 and seen[0].headers["authorization"] == "Bearer test-key"
    assert b"test-key" not in seen[0].content
    await adapter.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ['{"sql":"DELETE FROM orders"}', '{"metrics":["profit"]}', "not json"])
async def test_bad_model_output_never_falls_back(config, content):
    config.model_mode = "api"
    config.model_api_key = "test-key"
    adapter = PlannerAdapter(config)
    await adapter.client.aclose()
    adapter.client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
        )
    )
    with pytest.raises(DomainError) as error:
        await adapter.plan("2026年9月销售额", [], "2026-10-14")
    assert error.value.code == "INVALID_PLAN"
    await adapter.close()


@pytest.mark.asyncio
async def test_missing_key_fails_explicitly(config):
    config.model_mode = "api"
    config.model_api_key = ""
    adapter = PlannerAdapter(config)
    with pytest.raises(DomainError) as error:
        await adapter.plan("销售额", [], "2026-10-14")
    assert error.value.code == "MODEL_UNAVAILABLE"
    await adapter.close()
