import os
import re
import time
import json

from openai import OpenAI
import openai

from .base_llm import BaseLLM
from pyopenagi.utils.chat_template import Response


class LocalLLM(BaseLLM):
    """OpenAI-compatible backend for a locally served model (e.g. vLLM).

    Mirrors ``GPTLLM`` but points the OpenAI client at ``LOCAL_BASE_URL`` /
    ``LOCAL_API_KEY`` (the same env vars the CaMeL repo's ``src/camel/models.py``
    uses for its ``local:`` prefix) and drops the ``gpt`` model-name assertion, so
    any served model name (e.g. ``Qwen3-30B-A3B-Instruct-2507``) works.

    NOTE: if the local endpoint is on localhost and the environment sets
    HTTP(S)_PROXY, make sure NO_PROXY/no_proxy includes ``localhost,127.0.0.1``.
    """

    def __init__(self, llm_name: str,
                 max_gpu_memory: dict = None,
                 eval_device: str = None,
                 max_new_tokens: int = 1024,
                 log_mode: str = "console"):
        super().__init__(llm_name,
                         max_gpu_memory,
                         eval_device,
                         max_new_tokens,
                         log_mode)

    def load_llm_and_tokenizer(self) -> None:
        base_url = os.getenv("LOCAL_BASE_URL", "http://localhost:8000/v1")
        api_key = os.getenv("LOCAL_API_KEY", "EMPTY")
        self.model = OpenAI(base_url=base_url, api_key=api_key)
        self.tokenizer = None

    def parse_tool_calls(self, tool_calls):
        if tool_calls:
            parsed_tool_calls = []
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)
                parsed_tool_calls.append(
                    {
                        "name": function_name,
                        "parameters": function_args,
                    }
                )
            return parsed_tool_calls
        return None

    def process(self, agent_process, temperature=0.0):
        agent_process.set_status("executing")
        agent_process.set_start_time(time.time())
        messages = agent_process.query.messages
        self.logger.log(
            f"{agent_process.agent_name} is switched to executing.\n",
            level="executing",
        )
        try:
            kwargs = dict(
                model=self.model_name,
                messages=messages,
                tools=agent_process.query.tools,
                max_tokens=self.max_new_tokens,
                seed=0,
                temperature=temperature,
            )
            # Single-tool-call parsers (e.g. vLLM llama3_json) reject parallel calls.
            if agent_process.query.tools:
                kwargs["parallel_tool_calls"] = False
            response = self.model.chat.completions.create(**kwargs)
            response_message = response.choices[0].message.content
            tool_calls = self.parse_tool_calls(
                response.choices[0].message.tool_calls
            )
            agent_process.set_response(
                Response(
                    response_message=response_message,
                    tool_calls=tool_calls,
                )
            )
        except openai.APIConnectionError as e:
            agent_process.set_response(
                Response(response_message=f"Server connection error: {e.__cause__}")
            )
        except openai.RateLimitError as e:
            agent_process.set_response(
                Response(response_message=f"RATE LIMIT error {e.status_code}: (e.response)")
            )
        except openai.APIStatusError as e:
            agent_process.set_response(
                Response(response_message=f"STATUS error {e.status_code}: (e.response)")
            )
        except openai.BadRequestError as e:
            agent_process.set_response(
                Response(response_message=f"BAD REQUEST error {e.status_code}: (e.response)")
            )
        except Exception as e:
            agent_process.set_response(
                Response(response_message=f"An unexpected error occurred: {e}")
            )

        agent_process.set_status("done")
        agent_process.set_end_time(time.time())
