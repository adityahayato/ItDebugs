from unittest.mock import Mock

from itdebugs.llm.reasoning_agent import LLMReasoningAgent


def test_llm_reasoning_agent_parses_structured_response():
    client = Mock()

    client.chat.return_value = """
    {
        "root_cause": "Incorrect status comparison",
        "file": "task_manager/manager.py",
        "line": 71,
        "faulty_code": "return [t for t in self._tasks if t.status != \\"complete\\"]",
        "expected_behavior": "Completed tasks should not appear in pending tasks.",
        "actual_behavior": "Completed tasks appear in pending tasks.",
        "reasoning": [
            "The filter compares against the wrong status value.",
            "The canonical completed status is completed."
        ],
        "supporting_evidence": [
            "Failing test: test_pending_tasks_excludes_completed",
            "Canonical status is completed."
        ],
        "alternative_hypotheses": [],
        "confidence": "high",
        "suggested_fix": "Use the canonical completed status.",
        "verification_plan": [
            "Rerun the failing test.",
            "Run the full test suite."
        ]
    }
    """

    agent = LLMReasoningAgent(client=client)

    result = agent.investigate(
        bug_description="Completed tasks appear in pending tasks.",
        failing_tests=[
            "test_pending_tasks_excludes_completed"
        ],
        evidence=[
            {
                "file": "task_manager/manager.py",
                "line": 71,
                "code": 'return [t for t in self._tasks if t.status != "complete"]',
            }
        ],
    )

    assert result.root_cause == "Incorrect status comparison"
    assert result.file == "task_manager/manager.py"
    assert result.line == 71
    assert result.faulty_code is not None
    assert result.reasoning
    assert result.supporting_evidence
    assert result.verification_plan

    client.chat.assert_called_once()