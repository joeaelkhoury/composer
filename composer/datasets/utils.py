# Copyright 2022 MosaicML Composer authors
# SPDX-License-Identifier: Apache-2.0

"""Utility and helper functions for datasets."""

import logging
import textwrap
import warnings
from typing import Callable, List, Optional, Tuple, Union

import numpy as np
import torch
from PIL import Image
from torchvision import transforms
from torchvision.datasets import VisionDataset

from composer.core import Batch

__all__ = [
    'add_vision_dataset_transform',
    'NormalizationFn',
    'pil_image_collate',
]

log = logging.getLogger(__name__)


class NormalizationFn:
    """Normalizes input data and removes the background class from target data if desired.

    An instance of this class can be used as the ``device_transforms`` argument
    when constructing a :class:`~composer.core.data_spec.DataSpec`. When used here,
    the data will normalized after it has been loaded onto the device (i.e., GPU).

    Args:
        mean (Tuple[float, float, float]): The mean pixel value for each channel (RGB) for
            the dataset.
        std (Tuple[float, float, float]): The standard deviation pixel value for each
            channel (RGB) for the dataset.
        ignore_background (bool): If ``True``, ignore the background class in the training
            loss. Only used in semantic segmentation. Default: ``False``.
    """

    def __init__(self,
                 mean: Tuple[float, float, float],
                 std: Tuple[float, float, float],
                 ignore_background: bool = False):
        warnings.warn(DeprecationWarning('NormalizationFn is deprecated and will be removed in v0.18'))
        self.mean = mean
        self.std = std
        self.ignore_background = ignore_background

    def __call__(self, batch: Batch):
        xs, ys = batch
        assert isinstance(xs, torch.Tensor)
        assert isinstance(ys, torch.Tensor)
        device = xs.device

        if not isinstance(self.mean, torch.Tensor):
            self.mean = torch.tensor(self.mean, device=device)
            self.mean = self.mean.view(1, 3, 1, 1)
        if not isinstance(self.std, torch.Tensor):
            self.std = torch.tensor(self.std, device=device)
            self.std = self.std.view(1, 3, 1, 1)

        xs = xs.float()
        xs = xs.sub_(self.mean).div_(self.std)
        if self.ignore_background:
            ys = ys.sub_(1)
        return xs, ys


def pil_image_collate(
        batch: List[Tuple[Image.Image, Union[Image.Image, np.ndarray]]],
        memory_format: torch.memory_format = torch.contiguous_format) -> Tuple[torch.Tensor, torch.Tensor]:
    """Constructs a length 2 tuple of torch.Tensors from datasets that yield samples of type
    :class:`PIL.Image.Image`.

    This function can be used as the ``collate_fn`` argument of a :class:`torch.utils.data.DataLoader`.

    Args:
        batch (List[Tuple[Image.Image, Union[Image.Image, np.ndarray]]]): List of (image, target) tuples
            that will be aggregated and converted into a single (:class:`~torch.Tensor`, :class:`~torch.Tensor`)
            tuple.

        memory_format (torch.memory_format): The memory format for the input and target tensors.

    Returns:
        (torch.Tensor, torch.Tensor): Tuple of (image tensor, target tensor)
            The image tensor will be four-dimensional (NCHW or NHWC, depending on the ``memory_format``).
    """
    warnings.warn(DeprecationWarning('pil_image_collate is deprecated and will be removed in v0.18'))
    imgs = [sample[0] for sample in batch]
    w, h = imgs[0].size
    image_tensor = torch.zeros((len(imgs), 3, h, w), dtype=torch.uint8).contiguous(memory_format=memory_format)

    # Convert targets to torch tensor
    targets = [sample[1] for sample in batch]
    if isinstance(targets[0], Image.Image):
        target_dims = (len(targets), targets[0].size[1], targets[0].size[0])
    else:
        target_dims = (len(targets),)
    target_tensor = torch.zeros(target_dims, dtype=torch.int64).contiguous(memory_format=memory_format)

    for i, img in enumerate(imgs):
        nump_array = np.asarray(img, dtype=np.uint8)
        if nump_array.ndim < 3:
            nump_array = np.expand_dims(nump_array, axis=-1)

        nump_array = np.rollaxis(nump_array, 2).copy()
        if nump_array.shape[0] != 3:
            assert nump_array.shape[0] == 1, 'unexpected shape'
            nump_array = np.resize(nump_array, (3, h, w))
        assert image_tensor.shape[1:] == nump_array.shape, 'shape mismatch'

        image_tensor[i] += torch.from_numpy(nump_array)
        target_tensor[i] += torch.from_numpy(np.array(targets[i], dtype=np.int64))

    return image_tensor, target_tensor


def add_vision_dataset_transform(dataset: VisionDataset, transform: Callable, is_tensor_transform: bool = False):
    """Add a transform to a dataset's collection of transforms.

    Args:
        dataset (VisionDataset): A torchvision dataset.
        transform (Callable): Function to be added to the dataset's collection of
            transforms.
        is_tensor_transform (bool): Whether ``transform`` acts on data of the type
            :class:`~torch.Tensor`. default: ``False``.

            * If ``True``, and :class:`~torchvision.transforms.ToTensor` is present in the transforms of the
              ``dataset``, then ``transform`` will be inserted after the
              :class:`~torchvision.transforms.ToTensor` transform.
            * If ``False`` and :class:`~torchvision.transforms.ToTensor` is present, the ``transform`` will be
              inserted before :class:`~torchvision.transforms.ToTensor`.
            * If :class:`~torchvision.transforms.ToTensor` is not present, the transform will be appended to
              the end of collection of transforms.

    Returns:
        None: The ``dataset`` is modified in-place.
    """
    warnings.warn(DeprecationWarning('add_vision_dataset_transform is deprecated and will be removed in v0.18'))

    transform_added_logstring = textwrap.dedent(f"""\
        Transform {transform} added to dataset.
        Dataset now has the following transforms: {dataset.transform}""")

    if dataset.transform is None:
        dataset.transform = transform
        log.warning(transform_added_logstring)
    elif isinstance(dataset.transform, transforms.Compose):
        insertion_index = len(dataset.transform.transforms)
        for i, t in enumerate(dataset.transform.transforms):
            if isinstance(t, transforms.ToTensor):
                insertion_index = i
                break
        if is_tensor_transform:
            insertion_index += 1
        dataset.transform.transforms.insert(insertion_index, transform)
        log.warning(transform_added_logstring)
    else:  # transform is some other basic transform, join using Compose
        if isinstance(dataset.transform, transforms.ToTensor) and not is_tensor_transform:
            dataset.transform = transforms.Compose([transform, dataset.transform])
            log.warning(transform_added_logstring)
        else:
            dataset.transform = transforms.Compose([dataset.transform, transform])
            log.warning(transform_added_logstring)


try:
    import transformers

    class MultiTokenEOSCriteria(transformers.StoppingCriteria):
        """Criteria to stop on the specified multi-token sequence.
        Slightly modified from: https://github.com/EleutherAI/lm-evaluation-harness/blob/78545d42f2ca95c6fe0ed220d456eeb94f4485e9/lm_eval/utils.py#L614-L649
        """

        def __init__(
            self,
            stop_sequence: str,
            tokenizer: transformers.PreTrainedTokenizer,
            batch_size: int,
        ) -> None:
            self.done_tracker = [False] * batch_size
            self.stop_sequence = stop_sequence
            self.stop_sequence_ids = tokenizer.encode(stop_sequence, add_special_tokens=False)

            # we look back for 2 more tokens than it takes to encode our stop sequence
            # because tokenizers suck, and a model might generate `['\n', '\n']` but our `sequence` is `['\n\n']`
            # and we don't want to mistakenly not stop a generation because our
            # (string) stop sequence was output in a different tokenization

            # NOTE: there is a minor danger that this will end up looking back 2 tokens into the past, into the inputs to the model,
            # and stopping generation immediately as a result. With only 2 extra tokens of lookback, this risk is minimized
            self.stop_sequence_id_len = len(self.stop_sequence_ids) + 2
            self.tokenizer = tokenizer

        def __call__(self, input_ids, scores: Optional[torch.FloatTensor] = None, **kwargs) -> bool:
            # For efficiency, we compare the last n tokens where n is the number of tokens in the stop_sequence
            lookback_ids_batch = input_ids[:, :][:, -self.stop_sequence_id_len:]

            lookback_tokens_batch = self.tokenizer.batch_decode(lookback_ids_batch)
            for i, done in enumerate(self.done_tracker):
                if i >= len(lookback_tokens_batch):
                    # The last batch of a dataset may be smaller than `batch_size`
                    # Automatically set those indices in the done_tracker to True
                    # since those indices don't show up in the current batch
                    self.done_tracker[i] = True
                    break
                elif not done:
                    self.done_tracker[i] = self.stop_sequence in lookback_tokens_batch[i]
            return False not in self.done_tracker

    def stop_sequences_criteria(
        tokenizer: transformers.PreTrainedTokenizer,
        stop_sequences: List[str],
        batch_size: int,
    ) -> transformers.StoppingCriteriaList:
        return transformers.StoppingCriteriaList([
            *[MultiTokenEOSCriteria(sequence, tokenizer, batch_size) for sequence in stop_sequences],
        ])

except ImportError as e:
    stop_sequences_criteria = None  # pyright: ignore [reportGeneralTypeIssues]
    MultiTokenEOSCriteria = None  # pyright: ignore [reportGeneralTypeIssues]
