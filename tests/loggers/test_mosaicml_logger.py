# Copyright 2022 MosaicML Composer authors
# SPDX-License-Identifier: Apache-2.0

import json
import math
from typing import Type

import mcli
import pytest
import torch
from torch.utils.data import DataLoader

from composer.core import Callback
from composer.core.time import TimeUnit
from composer.loggers import InMemoryLogger, WandBLogger
from composer.loggers.mosaicml_logger import (MOSAICML_ACCESS_TOKEN_ENV_VAR, MOSAICML_PLATFORM_ENV_VAR, MosaicMLLogger,
                                              format_data_to_json_serializable)
from composer.trainer import Trainer
from composer.utils import dist
from tests.callbacks.callback_settings import get_cb_kwargs, get_cb_model_and_datasets, get_cbs_and_marks
from tests.common import RandomClassificationDataset, RandomTextLMDataset, SimpleModel, SimpleTransformerMaskedLM
from tests.common.markers import world_size


class MockMAPI:

    def __init__(self):
        self.run_metadata = {}

    def update_run_metadata(self, run_name, new_metadata):
        if run_name not in self.run_metadata:
            self.run_metadata[run_name] = {}
        for k, v in new_metadata.items():
            self.run_metadata[run_name][k] = v
        # Serialize the data to ensure it is json serializable
        json.dumps(self.run_metadata[run_name])


def test_format_data_to_json_serializable():
    data = {
        'key1': 'value1',
        'key2': 42,
        'key3': 3.14,
        'key4': True,
        'key5': torch.tensor([1, 2, 3]),
        'key6': {
            'inner_key': 'inner_value'
        },
        'key7': [1, 2, 3],
    }
    formatted_data = format_data_to_json_serializable(data)

    expected_formatted_data = {
        'key1': 'value1',
        'key2': 42,
        'key3': 3.14,
        'key4': True,
        'key5': 'Tensor of shape torch.Size([3])',
        'key6': {
            'inner_key': 'inner_value'
        },
        'key7': [1, 2, 3],
    }

    assert formatted_data == expected_formatted_data


@pytest.mark.parametrize('callback_cls', get_cbs_and_marks(callbacks=True))
@world_size(1, 2)
def test_logged_data_is_json_serializable(monkeypatch, callback_cls: Type[Callback], world_size):
    """Test that all logged data is json serializable, which is a requirement to use MAPI."""

    mock_mapi = MockMAPI()
    monkeypatch.setattr(mcli, 'update_run_metadata', mock_mapi.update_run_metadata)
    run_name = 'small_chungus'
    monkeypatch.setenv('RUN_NAME', run_name)

    callback_kwargs = get_cb_kwargs(callback_cls)
    callback = callback_cls(**callback_kwargs)
    train_dataset = RandomClassificationDataset()
    model, train_dataloader, _ = get_cb_model_and_datasets(callback, sampler=dist.get_sampler(train_dataset))
    trainer = Trainer(
        model=model,
        train_dataloader=train_dataloader,
        train_subset_num_batches=1,
        max_duration='1ep',
        callbacks=callback,
        loggers=MosaicMLLogger(),
    )
    trainer.fit()

    if dist.get_global_rank() == 0:
        assert len(mock_mapi.run_metadata[run_name].keys()) > 0
    else:
        assert len(mock_mapi.run_metadata.keys()) == 0


def test_metric_partial_filtering(monkeypatch):
    mock_mapi = MockMAPI()
    monkeypatch.setattr(mcli, 'update_run_metadata', mock_mapi.update_run_metadata)
    run_name = 'small_chungus'
    monkeypatch.setenv('RUN_NAME', run_name)

    trainer = Trainer(
        model=SimpleModel(),
        train_dataloader=DataLoader(RandomClassificationDataset()),
        train_subset_num_batches=2,
        max_duration='1ep',
        loggers=MosaicMLLogger(ignore_keys=['loss', 'accuracy']),
    )
    trainer.fit()

    assert 'mosaicml/num_nodes' in mock_mapi.run_metadata[run_name]
    assert 'mosaicml/loss' not in mock_mapi.run_metadata[run_name]


def test_metric_full_filtering(monkeypatch):
    mock_mapi = MockMAPI()
    monkeypatch.setattr(mcli, 'update_run_metadata', mock_mapi.update_run_metadata)
    run_name = 'small_chungus'
    monkeypatch.setenv('RUN_NAME', run_name)

    trainer = Trainer(
        model=SimpleModel(),
        train_dataloader=DataLoader(RandomClassificationDataset()),
        train_subset_num_batches=2,
        max_duration='1ep',
        loggers=MosaicMLLogger(ignore_keys=['*']),
    )
    trainer.fit()

    assert len(mock_mapi.run_metadata[run_name].keys()) == 0


class SetWandBRunURL(Callback):
    """Sets run_url attribute on WandB for offline unit testing."""

    def __init__(self, run_url) -> None:
        self.run_url = run_url

    def init(self, state, event) -> None:
        for callback in state.callbacks:
            if isinstance(callback, WandBLogger):
                callback.run_url = self.run_url


def test_wandb_run_url(monkeypatch):
    mock_mapi = MockMAPI()
    monkeypatch.setattr(mcli, 'update_run_metadata', mock_mapi.update_run_metadata)
    run_name = 'small_chungus'
    monkeypatch.setenv('RUN_NAME', run_name)

    run_url = 'my_run_url'
    monkeypatch.setenv('WANDB_MODE', 'offline')

    Trainer(model=SimpleModel(), loggers=[
        MosaicMLLogger(),
        WandBLogger(),
    ], callbacks=[
        SetWandBRunURL(run_url),
    ])

    assert mock_mapi.run_metadata[run_name]['mosaicml/wandb/run_url'] == run_url


@pytest.mark.parametrize('platform_env_var', ['True', 'None'])
@pytest.mark.parametrize('access_token_env_var', ['my-token', 'None'])
@pytest.mark.parametrize('logger_set', [True, False])
def test_auto_add_logger(monkeypatch, platform_env_var, access_token_env_var, logger_set):
    mock_mapi = MockMAPI()
    monkeypatch.setattr(mcli, 'update_run_metadata', mock_mapi.update_run_metadata)
    run_name = 'small_chungus'
    monkeypatch.setenv('RUN_NAME', run_name)

    monkeypatch.setenv(MOSAICML_PLATFORM_ENV_VAR, platform_env_var)
    monkeypatch.setenv(MOSAICML_ACCESS_TOKEN_ENV_VAR, access_token_env_var)

    trainer = Trainer(
        model=SimpleModel(),
        train_dataloader=DataLoader(RandomClassificationDataset()),
        train_subset_num_batches=2,
        max_duration='1ep',
        loggers=MosaicMLLogger() if logger_set else None,
    )

    logger_count = 0
    for callback in trainer.state.callbacks:
        if isinstance(callback, MosaicMLLogger):
            logger_count += 1
    # If logger is specified manually, ensure only 1
    if logger_set:
        assert logger_count == 1
    # Otherwise, auto-add only if platform and access token are set
    elif platform_env_var.lower() == 'true' and access_token_env_var is not None:
        assert logger_count == 1
    # Otherwise, no logger
    else:
        assert logger_count == 0


def test_model_initialized_time_logged(monkeypatch):
    mock_mapi = MockMAPI()
    monkeypatch.setattr(mcli, 'update_run_metadata', mock_mapi.update_run_metadata)
    run_name = 'test-run-name'
    monkeypatch.setenv('RUN_NAME', run_name)
    trainer = Trainer(model=SimpleModel(),
                      train_dataloader=DataLoader(RandomClassificationDataset()),
                      train_subset_num_batches=1,
                      max_duration='1ep',
                      loggers=[MosaicMLLogger()])
    trainer.fit()
    assert isinstance(mock_mapi.run_metadata[run_name]['mosaicml/model_initialized_time'], float)


def test_token_training_progress_logged(monkeypatch, tiny_bert_tokenizer):
    transformers = pytest.importorskip('transformers')
    mock_mapi = MockMAPI()
    monkeypatch.setattr(mcli, 'update_run_metadata', mock_mapi.update_run_metadata)
    run_name = 'test-run-name'
    monkeypatch.setenv('RUN_NAME', run_name)
    pretraining_train_dataset = RandomTextLMDataset(size=8,
                                                    vocab_size=tiny_bert_tokenizer.vocab_size,
                                                    sequence_length=8,
                                                    use_keys=True)
    collator = transformers.DataCollatorForLanguageModeling(tokenizer=tiny_bert_tokenizer, mlm_probability=0.15)
    dataloader = DataLoader(pretraining_train_dataset,
                            batch_size=4,
                            sampler=dist.get_sampler(pretraining_train_dataset),
                            collate_fn=collator)
    trainer = Trainer(model=SimpleTransformerMaskedLM(vocab_size=tiny_bert_tokenizer.vocab_size),
                      train_dataloader=dataloader,
                      max_duration='64tok',
                      loggers=[MosaicMLLogger()])
    trainer.fit()
    assert 'mosaicml/training_progress_unit' in mock_mapi.run_metadata[run_name]
    assert mock_mapi.run_metadata[run_name]['mosaicml/training_progress_unit'] == str(TimeUnit.TOKEN)
    assert 'mosaicml/training_progress' in mock_mapi.run_metadata[run_name]
    assert mock_mapi.run_metadata[run_name]['mosaicml/training_progress'] == '[token=64/64]'
    assert 'mosaicml/training_sub_progress' not in mock_mapi.run_metadata[run_name]


def test_batch_training_progress_logged(monkeypatch):
    mock_mapi = MockMAPI()
    monkeypatch.setattr(mcli, 'update_run_metadata', mock_mapi.update_run_metadata)
    run_name = 'test-run-name'
    monkeypatch.setenv('RUN_NAME', run_name)
    trainer = Trainer(model=SimpleModel(),
                      train_dataloader=DataLoader(RandomClassificationDataset()),
                      train_subset_num_batches=1,
                      max_duration='4ba',
                      loggers=[MosaicMLLogger()])
    trainer.fit()
    assert 'mosaicml/training_progress_unit' in mock_mapi.run_metadata[run_name]
    assert mock_mapi.run_metadata[run_name]['mosaicml/training_progress_unit'] == str(TimeUnit.BATCH)
    assert 'mosaicml/training_progress' in mock_mapi.run_metadata[run_name]
    assert mock_mapi.run_metadata[run_name]['mosaicml/training_progress'] == '[batch=4/4]'
    assert 'mosaicml/training_sub_progress' not in mock_mapi.run_metadata[run_name]


def test_epoch_training_progress_logged(monkeypatch):
    mock_mapi = MockMAPI()
    monkeypatch.setattr(mcli, 'update_run_metadata', mock_mapi.update_run_metadata)
    run_name = 'test-run-name'
    monkeypatch.setenv('RUN_NAME', run_name)
    # Because batch timestamp resets to 0 at the end of the train, we use in memory logger to check an intermediate epoch timestamp
    in_memory_logger = InMemoryLogger()
    trainer = Trainer(model=SimpleModel(),
                      train_dataloader=DataLoader(RandomClassificationDataset(), batch_size=2),
                      train_subset_num_batches=2,
                      max_duration='2ep',
                      loggers=[MosaicMLLogger(), in_memory_logger])
    trainer.fit()
    assert 'mosaicml/training_progress_unit' in mock_mapi.run_metadata[run_name]
    assert mock_mapi.run_metadata[run_name]['mosaicml/training_progress_unit'] == str(TimeUnit.EPOCH)
    assert 'mosaicml/training_progress' in mock_mapi.run_metadata[run_name]
    assert mock_mapi.run_metadata[run_name]['mosaicml/training_progress'] == '[epoch=2/2]'
    assert 'mosaicml/training_sub_progress' in mock_mapi.run_metadata[run_name]
    # Check that the sub progress is calculated correctly by looking at the first batch of the second epoch
    first_batch_ep2 = in_memory_logger.data['time/epoch'][2][0]
    batches_per_epoch = math.ceil(
        (first_batch_ep2.batch.value - first_batch_ep2.batch_in_epoch.value) // first_batch_ep2.epoch.value)
    assert first_batch_ep2.batch_in_epoch.value < batches_per_epoch
    assert batches_per_epoch < first_batch_ep2.batch
