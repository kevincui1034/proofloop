import json

import pytest

from proofloop.tasksource import TaskSourceError, select_benchmark_task


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_select_next_task_persists_state(tmp_repo):
    source = tmp_repo.write(
        "tasks.jsonl",
        json.dumps({"task_id": "btb_001", "final_prompt": "Build model one."})
        + "\n"
        + json.dumps({"task_id": "btb_002", "final_prompt": "Build model two."})
        + "\n",
    )

    first = select_benchmark_task(
        tmp_repo.root, "bankertoolbench", str(source), "next"
    )
    second = select_benchmark_task(
        tmp_repo.root, "bankertoolbench", str(source), "next"
    )

    assert first["task_id"] == "btb_001"
    assert first["task"] == "Build model one."
    assert second["task_id"] == "btb_002"
    state = json.loads(
        (
            tmp_repo.root
            / ".proofloop"
            / "benchmark-state"
            / "bankertoolbench.json"
        ).read_text()
    )
    assert state["last_task_id"] == "btb_002"
    assert state["next_index"] == 2


def test_select_task_from_directory_with_filters_and_inputs(tmp_repo):
    root = tmp_repo.root / "btb"
    _write_jsonl(
        root / "tasks.jsonl",
        [
            {
                "task_id": "btb_a",
                "final_prompt": "Run A.",
                "product": "M&A",
                "workflow_cat": "deck",
            },
            {
                "task_id": "btb_b",
                "final_prompt": "Run B.",
                "product": "ECM",
                "workflow_cat": "model",
            },
        ],
    )
    input_file = root / "task-data" / "btb_a" / "Inputs" / "input.xlsx"
    input_file.parent.mkdir(parents=True)
    input_file.write_text("xlsx placeholder", encoding="utf-8")

    selected = select_benchmark_task(
        tmp_repo.root,
        "bankertoolbench",
        str(root),
        "next",
        filters={"product": "m&a"},
    )

    assert selected["task_id"] == "btb_a"
    assert selected["metadata"]["workflow_cat"] == "deck"
    assert "btb/task-data/btb_a/Inputs/input.xlsx" in selected["input_refs"]


def test_select_random_task_is_seeded(tmp_repo):
    source = tmp_repo.write(
        "tasks.json",
        json.dumps(
            [
                {"task_id": "a", "final_prompt": "A"},
                {"task_id": "b", "final_prompt": "B"},
                {"task_id": "c", "final_prompt": "C"},
            ]
        ),
    )

    one = select_benchmark_task(tmp_repo.root, "bankertoolbench", str(source), "random", seed=7)
    two = select_benchmark_task(tmp_repo.root, "bankertoolbench", str(source), "random", seed=7)

    assert one["task_id"] == two["task_id"]
    assert one["selection"]["mode"] == "random"


def test_select_explicit_task_id(tmp_repo):
    source = tmp_repo.write(
        "tasks.jsonl",
        json.dumps({"task_id": "wanted", "final_prompt": "Do wanted."}) + "\n",
    )

    selected = select_benchmark_task(
        tmp_repo.root,
        "bankertoolbench",
        str(source),
        "next",
        task_id="wanted",
    )

    assert selected["task"] == "Do wanted."
    assert selected["selection"]["mode"] == "task_id"


def test_select_errors_when_filters_empty_source(tmp_repo):
    source = tmp_repo.write(
        "tasks.jsonl",
        json.dumps({"task_id": "btb_001", "final_prompt": "Do it.", "product": "DCM"})
        + "\n",
    )

    with pytest.raises(TaskSourceError, match="no tasks matched"):
        select_benchmark_task(
            tmp_repo.root,
            "bankertoolbench",
            str(source),
            "next",
            filters={"product": "M&A"},
        )
