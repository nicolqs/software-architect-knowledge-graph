"""LangChain @tool wrappers expose the right names and schemas to an LLM."""

from architect.agents.common.tools import langgraph_tools


def test_tool_set_is_complete() -> None:
    tools = {t.name for t in langgraph_tools()}
    assert tools == {"find_function", "callers_of", "dependents_of", "subgraph_around"}


def test_tool_descriptions_are_present() -> None:
    for t in langgraph_tools():
        assert t.description, f"tool {t.name} is missing a description"


def test_find_function_argument_shape() -> None:
    [find_fn] = [t for t in langgraph_tools() if t.name == "find_function"]
    schema = find_fn.args_schema.model_json_schema()
    props = schema["properties"]
    assert "repo" in props
    assert "name" in props
    assert "limit" in props
    # `limit` is bounded so the LLM can't request a 1M-row result.
    assert props["limit"].get("maximum") == 100
