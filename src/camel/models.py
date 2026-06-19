import os
import time
import warnings

import anthropic
import openai
from agentdojo import agent_pipeline, functions_runtime
from agentdojo import types as ad_types
from agentdojo.agent_pipeline.agent_pipeline import load_system_message
from agentdojo.models import MODEL_NAMES
from google import genai
from openai.types.chat import ChatCompletionReasoningEffort
from pydantic_ai.models import KnownModelName

from src.camel.interpreter.interpreter import MetadataEvalMode
from src.camel.pipeline_elements.anthropic_tool_filter import AnthropicLLMToolFilter
from src.camel.pipeline_elements.privileged_llm import PrivilegedLLM
from src.camel.pipeline_elements.replay_privileged_llm import PrivilegedLLMReplayer, UserInjectionTasksGetter
from src.camel.pipeline_elements.security_policies import (
    ADNoSecurityPolicyEngine,
    AgentDojoSecurityPolicyEngine,
    BankingSecurityPolicyEngine,
    SlackSecurityPolicyEngine,
    TravelSecurityPolicyEngine,
    WorkspaceSecurityPolicyEngine,
)

_thinking_efforts = ["low", "medium", "high"]
_oai_thinking_models = {
    "o4-mini-2025-04-16": "ChatGPT",
    "o3-2025-04-16": "ChatGPT",
    "o3-mini-2025-01-31": "ChatGPT",
    "o1-2024-12-17": "ChatGPT",
    "codex-mini-latest": "ChatGPT",
}
_oai_thinking_models_with_effort = {
    f"{model}-{effort}": name for model, name in _oai_thinking_models.items() for effort in _thinking_efforts
}
_supported_model_names = {
    "gemini-2.5-flash-preview-05-20": "AI model developed by Google",
    "gemini-2.5-flash": "AI model developed by Google",
    "gemini-2.5-pro-preview-06-05": "AI model developed by Google",
    "gemini-2.0-flash-lite-001": "AI model developed by Google",
     "claude-3-5-haiku-20241022": "Claude",
    "claude-3-5-sonnet-20241022": "Claude",
    "claude-3-7-sonnet-20250219": "Claude",
    "claude-sonnet-4-20250514": "Claude",
    "claude-opus-4-20250514": "Claude",
    "claude-sonnet-4-5-20250929": "Claude",
    "gpt-4o-2024-08-06": "GPT-4",
    "gpt-4o-mini-2024-07-18": "GPT-4",
    "gpt-4.1-2025-04-14": "ChatGPT",
    "gpt-4.1-nano-2025-04-14": "ChatGPT",
    "Llama-3.3-70B-Instruct": "Llama",
} | _oai_thinking_models_with_effort
suffixes = ["", "+camel", "+camel+secpol", "+camel+secpol+strict"]

CAMEL_MODEL_NAMES = {f"{model}{suffix}": name for model, name in _supported_model_names.items() for suffix in suffixes}

_SECURITY_POLICY_ENGINES: dict[str, type[AgentDojoSecurityPolicyEngine]] = {
    "workspace": WorkspaceSecurityPolicyEngine,
    "travel": TravelSecurityPolicyEngine,
    "banking": BankingSecurityPolicyEngine,
    "slack": SlackSecurityPolicyEngine,
}


def _is_oai_reasoning_model(model: str) -> bool:
    return "o4" in model or "o3" in model or "o1" in model or "codex" in model


MODEL_NAMES.update(CAMEL_MODEL_NAMES)


class Sleep(agent_pipeline.BasePipelineElement):
    def __init__(self, amount: int) -> None:
        super().__init__()
        self._amount = amount

    def query(
        self,
        query: str,
        runtime,
        env=functions_runtime.EmptyEnv(),
        messages=[],
        extra_args={},
    ) -> tuple:
        if self._amount > 0:
            time.sleep(self._amount)
        return query, runtime, env, messages, extra_args


_CONTEXT_ERROR_MARKERS = (
    "context length",
    "context_length",
    "maximum context",
    "reduce the length",
    "too many tokens",
)


def _is_context_length_error(exc: Exception) -> bool:
    """Best-effort detection of a 'prompt longer than the context window' error."""
    message = str(exc).lower()
    return any(marker in message for marker in _CONTEXT_ERROR_MARKERS)


def _force_single_tool_calls(client: openai.OpenAI) -> None:
    """Force ``parallel_tool_calls=False`` on a client's chat completions.

    Some local servers (e.g. vLLM with the ``llama3_json`` tool-call parser) only
    support a single tool call per turn and return a 400 otherwise. This only affects
    requests that actually pass ``tools`` (i.e. the native ``--use-original`` baseline);
    CaMeL's privileged LLM sends no tools, so it is unaffected.
    """
    original_create = client.chat.completions.create

    def create(*args, **kwargs):
        if kwargs.get("tools"):
            kwargs.setdefault("parallel_tool_calls", False)
        return original_create(*args, **kwargs)

    try:
        client.chat.completions.create = create  # type: ignore[method-assign]
    except (AttributeError, TypeError) as e:  # pragma: no cover - SDK internals may change
        warnings.warn(
            "Could not force parallel_tool_calls=False on the local client "
            f"({e}); native (--use-original) tool calling may fail on single-tool-call "
            "parsers like vLLM's llama3_json."
        )


def _make_context_safe(llm: agent_pipeline.BasePipelineElement) -> agent_pipeline.BasePipelineElement:
    """Wraps an LLM element so a context-length overflow fails the task instead of crashing.

    When the prompt exceeds the model's context window (common with local models that
    have a small window), the underlying client raises a 400 BadRequestError that would
    otherwise abort the whole benchmark. Here we catch it, emit a warning, and return an
    empty assistant turn so the pipeline ends gracefully and the task is scored as failed.
    """
    original_query = llm.query

    def safe_query(
        query,
        runtime,
        env=functions_runtime.EmptyEnv(),
        messages=[],
        extra_args={},
    ):
        try:
            return original_query(query, runtime, env, messages, extra_args)
        except openai.BadRequestError as e:
            if not _is_context_length_error(e):
                raise
            warnings.warn(f"Skipping turn: prompt exceeded the model's context window ({e}).")
            empty_message = ad_types.ChatAssistantMessage(role="assistant", content=None, tool_calls=None)
            return query, runtime, env, [*messages, empty_message], extra_args

    llm.query = safe_query  # type: ignore[method-assign]
    return llm


def _disable_google_safety(client) -> None:
    """Inject ``safety_settings=OFF`` into a google-genai client's generate_content.

    Gemini's safety filters can return a candidate with no content parts (logged by
    AgentDojo as "no content parts"), which silently fails the turn. AgentDojo's
    GoogleLLM does not expose safety settings, so we wrap the client to set them when
    the caller hasn't. Set CAMEL_KEEP_GOOGLE_SAFETY=1 to keep the default filters.
    """
    if os.getenv("CAMEL_KEEP_GOOGLE_SAFETY"):
        return
    try:
        from google.genai import types

        off_settings = [
            types.SafetySetting(category=category, threshold="OFF")
            for category in (
                "HARM_CATEGORY_HARASSMENT",
                "HARM_CATEGORY_HATE_SPEECH",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "HARM_CATEGORY_DANGEROUS_CONTENT",
            )
        ]
    except Exception as e:  # pragma: no cover - depends on google-genai internals
        warnings.warn(f"Could not build Google safety settings ({e}); leaving defaults.")
        return

    original_generate = client.models.generate_content

    def generate_content(*args, **kwargs):
        config = kwargs.get("config")
        if config is not None and getattr(config, "safety_settings", None) is None:
            try:
                config.safety_settings = off_settings
            except Exception:
                pass
        return original_generate(*args, **kwargs)

    try:
        client.models.generate_content = generate_content  # type: ignore[method-assign]
    except (AttributeError, TypeError) as e:  # pragma: no cover
        warnings.warn(f"Could not disable Google safety filters ({e}).")


def make_tools_pipeline(
    model: KnownModelName,
    use_original: bool,
    replay_with_policies: bool,
    attack_name: str,
    reasoning_effort: ChatCompletionReasoningEffort,
    thinking_budget_tokens: int | None,
    suite: str,
    ad_defense: str | None,
    eval_mode: MetadataEvalMode,
    q_llm: KnownModelName | None,
) -> agent_pipeline.AgentPipeline:
    if "google" in model:
        # vertexai.init(project=os.getenv("GCP_PROJECT"), location=os.getenv("GCP_LOCATION"))
        # llm = GoogleLLM(model.split(":")[1])
        # client = genai.Client(vertexai=True, project=os.getenv("GCP_PROJECT"), location=os.getenv("GCP_LOCATION"))
        client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
        _disable_google_safety(client)
        if model == "google:gemini-2.0-flash-lite-001":
            max_tokens = 8192
        else:
            max_tokens = 65535
        llm = agent_pipeline.GoogleLLM(model.split(":")[1], client, max_tokens=max_tokens)
    elif "openai" in model:
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        # reasoning models do not support temperature and their "system" message is called "developer" message
        if _is_oai_reasoning_model(model):
            llm = agent_pipeline.OpenAILLM(client, model.split(":")[1], reasoning_effort, None)
        else:
            llm = agent_pipeline.OpenAILLM(client, model.split(":")[1], None)
    elif "anthropic" in model:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        if thinking_budget_tokens:
            max_tokens = 8192 + thinking_budget_tokens
        else:
            max_tokens = 8192
        llm = agent_pipeline.AnthropicLLM(
            client, model.split(":")[1], thinking_budget_tokens=thinking_budget_tokens, max_tokens=max_tokens
        )
    elif model.startswith("local:"):
        # Local / self-hosted model exposed via an OpenAI-compatible server
        # (vLLM, Ollama, TGI, SGLang, ...). Configure the endpoint with the
        # LOCAL_BASE_URL and (optional) LOCAL_API_KEY environment variables.
        base_url = os.getenv("LOCAL_BASE_URL", "http://localhost:8000/v1")
        client = openai.OpenAI(api_key=os.getenv("LOCAL_API_KEY", "EMPTY"), base_url=base_url)
        # Many local tool-call parsers (e.g. vLLM's llama3_json) only support a single
        # tool call per turn, which the native (--use-original) loop would otherwise
        # violate. Force parallel_tool_calls=False for this client.
        _force_single_tool_calls(client)
        llm = agent_pipeline.OpenAILLM(client, model.split(":", 1)[1], None)
    else:
        raise ValueError("Invalid model")

    llm.name = model.split(":", 1)[1]
    # Make context-window overflows fail the task gracefully instead of crashing the run.
    llm = _make_context_safe(llm)

    # The quarantined LLM is invoked through pydantic-ai. For local models we
    # build an explicit OpenAI-compatible model object pointing at the same
    # endpoint; for the hosted providers we keep passing the model string.
    if model.startswith("local:"):
        from pydantic_ai.models.openai import OpenAIModel
        from pydantic_ai.providers.openai import OpenAIProvider

        quarantined_llm_model = OpenAIModel(
            model.split(":", 1)[1],
            provider=OpenAIProvider(
                base_url=os.getenv("LOCAL_BASE_URL", "http://localhost:8000/v1"),
                api_key=os.getenv("LOCAL_API_KEY", "EMPTY"),
            ),
        )
    else:
        quarantined_llm_model = model

    engine = _SECURITY_POLICY_ENGINES[suite]

    if use_original:
        if "exp" in model:
            print("Adding 'Sleep' pipeline element.")
            tools_loop = agent_pipeline.ToolsExecutionLoop([agent_pipeline.ToolsExecutor(), Sleep(6), llm])
        else:
            tools_loop = agent_pipeline.ToolsExecutionLoop([agent_pipeline.ToolsExecutor(), llm])

        tools_pipeline = agent_pipeline.AgentPipeline(
            [agent_pipeline.SystemMessage(load_system_message(None)), agent_pipeline.InitQuery(), llm, tools_loop]
        )

        if ad_defense == "tool_filter" and isinstance(llm, agent_pipeline.AnthropicLLM):
            tools_pipeline = agent_pipeline.AgentPipeline(
                [
                    agent_pipeline.SystemMessage(load_system_message(None)),
                    agent_pipeline.InitQuery(),
                    AnthropicLLMToolFilter(llm.client, llm.name),
                    llm,
                    tools_loop,
                ]
            )
        elif ad_defense is not None:
            tools_pipeline = agent_pipeline.AgentPipeline.from_config(
                agent_pipeline.PipelineConfig(
                    llm=llm, defense=ad_defense, system_message_name=None, system_message=None
                )
            )

        if _is_oai_reasoning_model(model):
            tools_pipeline.name = f"{model.split(':')[1]}-{reasoning_effort}"
        elif "anthropic" in model and (("3-7-sonnet" in model or "sonnet-4" in model) and thinking_budget_tokens):
            tools_pipeline.name = f"{model.split(':')[1]}-{thinking_budget_tokens}"
        else:
            tools_pipeline.name = model.split(":")[1]
        if ad_defense is not None:
            tools_pipeline.name += f"+{ad_defense}"

    elif replay_with_policies:
        if _is_oai_reasoning_model(model):
            pipeline_name = f"{model.split(':')[1]}-{reasoning_effort}+camel"
        else:
            pipeline_name = f"{model.split(':')[1]}+camel"
        tools_pipeline = agent_pipeline.AgentPipeline(
            [
                agent_pipeline.InitQuery(),
                UserInjectionTasksGetter(),
                PrivilegedLLMReplayer(pipeline_name, attack_name, engine, eval_mode),
            ]
        )
        # Used for logging
        if "openai" in model and _is_oai_reasoning_model(model):
            tools_pipeline.name = f"{model.split(':')[1]}-{reasoning_effort}+camel+secpol"
        elif "anthropic" in model and (("3-7-sonnet" in model or "sonnet-4" in model) and thinking_budget_tokens):
            tools_pipeline.name = f"{model.split(':')[1]}-{thinking_budget_tokens}+camel+secpol"
        else:
            tools_pipeline.name = f"{model.split(':')[1]}+camel+secpol"
        if eval_mode == MetadataEvalMode.STRICT:
            tools_pipeline.name += "+strict"
    else:
        tools_pipeline = agent_pipeline.AgentPipeline(
            [
                # Adds the user query to the history
                agent_pipeline.InitQuery(),
                # Generates the code and writes it to `extra_args`
                PrivilegedLLM(
                    llm,
                    ADNoSecurityPolicyEngine,
                    q_llm or quarantined_llm_model,
                ),
            ]
        )
        # Used for logging
        if "openai" in model and _is_oai_reasoning_model(model):
            tools_pipeline.name = f"{model.split(':')[1]}-{reasoning_effort}+camel"
        elif "anthropic" in model and (("3-7-sonnet" in model or "sonnet-4" in model) and thinking_budget_tokens):
            tools_pipeline.name = f"{model.split(':')[1]}-{thinking_budget_tokens}+camel"
        else:
            tools_pipeline.name = f"{model.split(':')[1]}+camel"

        if q_llm:
            tools_pipeline.name += f"-q:{q_llm.split(':')[1]}"

    return tools_pipeline
