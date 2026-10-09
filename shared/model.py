import json
import os
import re
import time
from openai import AsyncOpenAI


async def structured(system, payload, schema):
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise ValueError("请先在本地 .env 配置模型密钥。")
    started = time.monotonic()
    async with AsyncOpenAI(
        api_key=key,
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        timeout=45,
        max_retries=1,
    ) as client:
        response = await client.chat.completions.create(
            model=os.getenv("AI_MODEL", "qwen-plus"),
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": system
                    + "\n只返回符合以下 JSON Schema 的 JSON 对象："
                    + json.dumps(schema.model_json_schema(), ensure_ascii=False),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        )
    text = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        (response.choices[0].message.content or "").strip(),
    )
    data = schema.model_validate_json(text)
    usage = response.usage
    return data, {
        "latency_ms": round((time.monotonic() - started) * 1000),
        "input_tokens": usage.prompt_tokens if usage else None,
        "output_tokens": usage.completion_tokens if usage else None,
    }
