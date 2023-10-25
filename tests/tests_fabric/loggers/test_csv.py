# Copyright The Lightning AI team.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import csv
import itertools
import os
from typing import Dict, List, Set, Tuple
from unittest.mock import MagicMock

import pytest
import torch
from lightning.fabric.loggers import CSVLogger
from lightning.fabric.loggers.csv_logs import _ExperimentWriter


def test_automatic_versioning(tmp_path):
    """Verify that automatic versioning works."""
    (tmp_path / "exp" / "version_0").mkdir(parents=True)
    (tmp_path / "exp" / "version_1").mkdir()
    logger = CSVLogger(root_dir=tmp_path, name="exp")
    assert logger.version == 2


def test_automatic_versioning_relative_root_dir(tmp_path, monkeypatch):
    """Verify that automatic versioning works, when root_dir is given a relative path."""
    (tmp_path / "exp" / "logs" / "version_0").mkdir(parents=True)
    (tmp_path / "exp" / "logs" / "version_1").mkdir()
    monkeypatch.chdir(tmp_path)
    logger = CSVLogger(root_dir="exp", name="logs")
    assert logger.version == 2


def test_manual_versioning(tmpdir):
    """Verify that manual versioning works."""
    root_dir = tmpdir.mkdir("exp")
    root_dir.mkdir("version_0")
    root_dir.mkdir("version_1")
    root_dir.mkdir("version_2")
    logger = CSVLogger(root_dir=root_dir, name="exp", version=1)
    assert logger.version == 1


def test_named_version(tmpdir):
    """Verify that manual versioning works for string versions, e.g. '2020-02-05-162402'."""
    exp_name = "exp"
    tmpdir.mkdir(exp_name)
    expected_version = "2020-02-05-162402"

    logger = CSVLogger(root_dir=tmpdir, name=exp_name, version=expected_version)
    logger.log_metrics({"a": 1, "b": 2})
    logger.save()
    assert logger.version == expected_version
    assert os.listdir(tmpdir / exp_name) == [expected_version]
    assert os.listdir(tmpdir / exp_name / expected_version)


@pytest.mark.parametrize("name", ["", None])
def test_no_name(tmpdir, name):
    """Verify that None or empty name works."""
    logger = CSVLogger(root_dir=tmpdir, name=name)
    logger.log_metrics({"a": 1})
    logger.save()
    assert os.path.normpath(logger._root_dir) == tmpdir  # use os.path.normpath to handle trailing /
    assert os.listdir(tmpdir / "version_0")


@pytest.mark.parametrize("step_idx", [10, None])
def test_log_metrics(tmpdir, step_idx):
    logger = CSVLogger(tmpdir)
    metrics = {"float": 0.3, "int": 1, "FloatTensor": torch.tensor(0.1), "IntTensor": torch.tensor(1)}
    logger.log_metrics(metrics, step_idx)
    logger.save()

    path_csv = os.path.join(logger.log_dir, _ExperimentWriter.NAME_METRICS_FILE)
    with open(path_csv) as fp:
        lines = fp.readlines()
    assert len(lines) == 2
    assert all(n in lines[0] for n in metrics)


def test_log_hyperparams(tmpdir):
    logger = CSVLogger(tmpdir)
    with pytest.raises(NotImplementedError):
        logger.log_hyperparams({})


def test_flush_n_steps(tmpdir):
    logger = CSVLogger(tmpdir, flush_logs_every_n_steps=2)
    metrics = {"float": 0.3, "int": 1, "FloatTensor": torch.tensor(0.1), "IntTensor": torch.tensor(1)}
    logger.save = MagicMock()
    logger.log_metrics(metrics, step=0)

    logger.save.assert_not_called()
    logger.log_metrics(metrics, step=1)
    logger.save.assert_called_once()


def test_metrics_reset_after_save(tmp_path):
    logger = CSVLogger(tmp_path, flush_logs_every_n_steps=2)
    metrics = {"test": 1}
    logger.log_metrics(metrics, step=0)
    assert logger.experiment.metrics
    logger.log_metrics(metrics, step=1)  # flush triggered
    assert not logger.experiment.metrics


def test_automatic_step_tracking(tmp_path):
    """Test that the logger keeps track of the step value if it isn't passed in explicitly."""
    logger = CSVLogger(tmp_path, flush_logs_every_n_steps=3)
    logger.save = MagicMock()
    metrics = {"test": 0.1}
    logger.log_metrics(metrics, step=None)
    logger.save.assert_not_called()
    assert logger.experiment.metrics[0]["step"] == 0
    logger.log_metrics(metrics, step=None)
    logger.save.assert_not_called()
    assert logger.experiment.metrics[1]["step"] == 1
    logger.log_metrics(metrics, step=None)
    logger.save.assert_called_once()
    assert logger.experiment.metrics[2]["step"] == 2


def test_append_metrics_file(tmp_path):
    """Test that the logger appends to the file instead of rewriting it on every save."""
    logger = CSVLogger(tmp_path, name="test", version=0, flush_logs_every_n_steps=1)

    # initial metrics
    logger.log_metrics({"a": 1, "b": 2})
    logger.log_metrics({"a": 3, "b": 4})

    # create a new logger to show we append to the existing file
    logger = CSVLogger(tmp_path, name="test", version=0, flush_logs_every_n_steps=1)
    logger.log_metrics({"a": 100, "b": 200})

    with open(logger.experiment.metrics_file_path) as file:
        lines = file.readlines()
    assert len(lines) == 4  # 1 header + 3 lines of metrics


def test_append_columns(tmp_path):
    """Test that the CSV file gets rewritten with new headers if the columns change."""
    logger = CSVLogger(tmp_path, flush_logs_every_n_steps=1)

    # initial metrics
    logger.log_metrics({"a": 1, "b": 2})
    _assert_csv_content(
        logger.experiment.metrics_file_path,
        expected_headers={"step", "a", "b"},
        expected_content=[{"step": "0", "a": "1", "b": "2"}],
    )

    # new key appears
    logger.log_metrics({"a": 11, "b": 22, "c": 33})
    _assert_csv_content(
        logger.experiment.metrics_file_path,
        expected_headers={"step", "a", "b", "c"},
        expected_content=[
            {"step": "0", "a": "1", "b": "2", "c": ""},
            {"step": "0", "a": "11", "b": "22", "c": "33"},
        ],
    )

    # key disappears
    logger.log_metrics({"a": 111, "c": 333})
    _assert_csv_content(
        logger.experiment.metrics_file_path,
        expected_headers={"step", "a", "b", "c"},
        expected_content=[
            {"step": "0", "a": "1", "b": "2", "c": ""},
            {"step": "0", "a": "11", "b": "22", "c": "33"},
            {"step": "0", "a": "111", "b": "", "c": "333"},
        ],
    )


def _assert_csv_content(
    path: str,
    expected_headers: Set[str],
    expected_content: List[Dict[str, str]],
) -> None:
    """Verifies the content of a local csv file with the expected ones."""
    headers, content = _read_csv(path)
    assert headers == expected_headers
    for actual, expected in itertools.zip_longest(content, expected_content):
        assert actual == expected


def _read_csv(path: str) -> Tuple[Set[str], List[Dict[str, str]]]:
    """Reads a local csv file and returns the headers and content."""
    with open(path) as file:
        reader = csv.DictReader(file)
        headers = set(reader.fieldnames)
        content = list(reader)
    return headers, content
