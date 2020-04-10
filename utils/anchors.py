# Copyright 2020 Google Research. All Rights Reserved.
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
# ==============================================================================
"""Anchors
https://github.com/tensorflow/tpu/blob/master/models/official/retinanet/anchors.py
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import collections
import numpy as np
import torch

# from effdet.object_detection import argmax_matcher
# from effdet.object_detection import box_list
# from effdet.object_detection import faster_rcnn_box_coder
# from effdet.object_detection import region_similarity_calculator
# from effdet.object_detection import target_assigner

# The minimum score to consider a logit for identifying detections.
MIN_CLASS_SCORE = -5.0

# The score for a dummy detection
_DUMMY_DETECTION_SCORE = -1e5

# The maximum number of (anchor,class) pairs to keep for non-max suppression.
MAX_DETECTION_POINTS = 5000

# The maximum number of detections per image.
MAX_DETECTIONS_PER_IMAGE = 100


def sigmoid(x):
    """Sigmoid function for use with Numpy for CPU evaluation."""
    return 1 / (1 + np.exp(-x))


def decode_box_outputs(rel_codes, anchors):
    """Transforms relative regression coordinates to absolute positions.
    Network predictions are normalized and relative to a given anchor; this
    reverses the transformation and outputs absolute coordinates for the input image.
    Args:
        rel_codes: box regression targets.
        anchors: anchors on all feature levels.
    Returns:
        outputs: bounding boxes.
    """
    ycenter_a = (anchors[0] + anchors[2]) / 2
    xcenter_a = (anchors[1] + anchors[3]) / 2
    ha = anchors[2] - anchors[0]
    wa = anchors[3] - anchors[1]
    ty, tx, th, tw = rel_codes

    w = np.exp(tw) * wa
    h = np.exp(th) * ha
    ycenter = ty * ha + ycenter_a
    xcenter = tx * wa + xcenter_a
    ymin = ycenter - h / 2.
    xmin = xcenter - w / 2.
    ymax = ycenter + h / 2.
    xmax = xcenter + w / 2.
    return np.column_stack([ymin, xmin, ymax, xmax])


def nms(dets, thresh):
    """Non-maximum suppression."""
    x1 = dets[:, 0]
    y1 = dets[:, 1]
    x2 = dets[:, 2]
    y2 = dets[:, 3]
    scores = dets[:, 4]

    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = scores.argsort()[::-1]

    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])

        w = np.maximum(0.0, xx2 - xx1 + 1)
        h = np.maximum(0.0, yy2 - yy1 + 1)
        intersection = w * h
        overlap = intersection / (areas[i] + areas[order[1:]] - intersection)

        inds = np.where(overlap <= thresh)[0]
        order = order[inds + 1]
    return keep


def _generate_anchor_configs(min_level, max_level, num_scales, aspect_ratios):
    """Generates mapping from output level to a list of anchor configurations.
    A configuration is a tuple of (num_anchors, scale, aspect_ratio).
    Args:
        min_level: integer number of minimum level of the output feature pyramid.
        max_level: integer number of maximum level of the output feature pyramid.
        num_scales: integer number representing intermediate scales added on each level.
            For instances, num_scales=2 adds two additional anchor scales [2^0, 2^0.5] on each level.
        aspect_ratios: list of tuples representing the aspect ratio anchors added on each level.
            For instances, aspect_ratios = [(1, 1), (1.4, 0.7), (0.7, 1.4)] adds three anchors on each level.
    Returns:
        anchor_configs: a dictionary with keys as the levels of anchors and
            values as a list of anchor configuration.
    """
    anchor_configs = {}
    for level in range(min_level, max_level + 1):
        anchor_configs[level] = []
        for scale_octave in range(num_scales):
            for aspect in aspect_ratios:
                anchor_configs[level].append((2 ** level, scale_octave / float(num_scales), aspect))
    return anchor_configs


def _generate_anchor_boxes(image_size, anchor_scale, anchor_configs):
    """Generates multiscale anchor boxes.
    Args:
        image_size: integer number of input image size. The input image has the same dimension for
            width and height. The image_size should be divided by the largest feature stride 2^max_level.
        anchor_scale: float number representing the scale of size of the base
            anchor to the feature stride 2^level.
        anchor_configs: a dictionary with keys as the levels of anchors and
            values as a list of anchor configuration.
    Returns:
        anchor_boxes: a numpy array with shape [N, 4], which stacks anchors on all feature levels.
    Raises:
        ValueError: input size must be the multiple of largest feature stride.
    """
    boxes_all = []
    for _, configs in anchor_configs.items():
        boxes_level = []
        for config in configs:
            stride, octave_scale, aspect = config
            if image_size % stride != 0:
                raise ValueError("input size must be divided by the stride.")
            base_anchor_size = anchor_scale * stride * 2 ** octave_scale
            anchor_size_x_2 = base_anchor_size * aspect[0] / 2.0
            anchor_size_y_2 = base_anchor_size * aspect[1] / 2.0

            x = np.arange(stride / 2, image_size, stride)
            y = np.arange(stride / 2, image_size, stride)
            xv, yv = np.meshgrid(x, y)
            xv = xv.reshape(-1)
            yv = yv.reshape(-1)

            boxes = np.vstack((yv - anchor_size_y_2, xv - anchor_size_x_2,
                               yv + anchor_size_y_2, xv + anchor_size_x_2))
            boxes = np.swapaxes(boxes, 0, 1)
            boxes_level.append(np.expand_dims(boxes, axis=1))
        # concat anchors on the same level to the reshape NxAx4
        boxes_level = np.concatenate(boxes_level, axis=1)
        boxes_all.append(boxes_level.reshape([-1, 4]))

    anchor_boxes = np.vstack(boxes_all)
    return anchor_boxes


def generate_detections(
        cls_outputs, box_outputs, anchor_boxes, indices, classes, image_id, image_scale, num_classes):
    """Generates detections with RetinaNet model outputs and anchors.
    Args:
        cls_outputs: a numpy array with shape [N, 1], which has the highest class
            scores on all feature levels. The N is the number of selected
            top-K total anchors on all levels.  (k being MAX_DETECTION_POINTS)
        box_outputs: a numpy array with shape [N, 4], which stacks box regression
            outputs on all feature levels. The N is the number of selected top-k
            total anchors on all levels. (k being MAX_DETECTION_POINTS)
        anchor_boxes: a numpy array with shape [N, 4], which stacks anchors on all
            feature levels. The N is the number of selected top-k total anchors on all levels.
        indices: a numpy array with shape [N], which is the indices from top-k selection.
        classes: a numpy array with shape [N], which represents the class
            prediction on all selected anchors from top-k selection.
        image_id: an integer number to specify the image id.
        image_scale: a float tensor representing the scale between original image
            and input image for the detector. It is used to rescale detections for
            evaluating with the original groundtruth annotations.
        num_classes: a integer that indicates the number of classes.
    Returns:
        detections: detection results in a tensor with each row representing
            [image_id, x, y, width, height, score, class]
    """
    anchor_boxes = anchor_boxes[indices, :]
    scores = sigmoid(cls_outputs)

    # apply bounding box regression to anchors
    boxes = decode_box_outputs(box_outputs.swapaxes(0, 1), anchor_boxes.swapaxes(0, 1))
    boxes = boxes[:, [1, 0, 3, 2]]

    # run class-wise nms
    detections = []
    for c in range(num_classes):
        indices = np.where(classes == c)[0]
        if indices.shape[0] == 0:
            continue
        boxes_cls = boxes[indices, :]
        scores_cls = scores[indices]

        # Select top-scoring boxes in each class and apply non-maximum suppression
        # (nms) for boxes in the same class. The selected boxes from each class are
        # then concatenated for the final detection outputs.
        all_detections_cls = np.column_stack((boxes_cls, scores_cls))
        top_detection_idx = nms(all_detections_cls, 0.5)
        top_detections_cls = all_detections_cls[top_detection_idx]
        top_detections_cls[:, 2] -= top_detections_cls[:, 0]
        top_detections_cls[:, 3] -= top_detections_cls[:, 1]
        top_detections_cls = np.column_stack(
            (np.repeat(image_id, len(top_detection_idx)),
             top_detections_cls,
             np.repeat(c + 1, len(top_detection_idx)))
        )
        detections.append(top_detections_cls)

    def _generate_dummy_detections(number):
        _dummy = np.zeros((number, 7), dtype=np.float32)
        _dummy[:, 0] = image_id  #[0]
        _dummy[:, 5] = _DUMMY_DETECTION_SCORE
        return _dummy

    if detections:
        detections = np.vstack(detections)

        # take final 100 detections
        indices = np.argsort(-detections[:, -2])
        detections = np.array(detections[indices[0:MAX_DETECTIONS_PER_IMAGE]], dtype=np.float32)

        # Add dummy detections to fill up to 100 detections
        n = max(MAX_DETECTIONS_PER_IMAGE - len(detections), 0)
        detections_dummy = _generate_dummy_detections(n)
        detections = np.vstack([detections, detections_dummy])
        detections[:, 1:5] *= image_scale
    else:
        detections = _generate_dummy_detections(MAX_DETECTIONS_PER_IMAGE)
        detections[:, 1:5] *= image_scale

    return detections


class Anchors(object):
    """RetinaNet Anchors class."""

    def __init__(self, min_level, max_level, num_scales, aspect_ratios, anchor_scale, image_size):
        """Constructs multiscale RetinaNet anchors.
        Args:
            min_level: integer number of minimum level of the output feature pyramid.
            max_level: integer number of maximum level of the output feature pyramid.
            num_scales: integer number representing intermediate scales added
                on each level. For instances, num_scales=2 adds two additional
                anchor scales [2^0, 2^0.5] on each level.
            aspect_ratios: list of tuples representing the aspect ratio anchors added
                on each level. For instances, aspect_ratios =
                [(1, 1), (1.4, 0.7), (0.7, 1.4)] adds three anchors on each level.
            anchor_scale: float number representing the scale of size of the base
                anchor to the feature stride 2^level.
            image_size: integer number of input image size. The input image has the
                same dimension for width and height. The image_size should be divided by
                the largest feature stride 2^max_level.
        """
        self.min_level = min_level
        self.max_level = max_level
        self.num_scales = num_scales
        self.aspect_ratios = aspect_ratios
        self.anchor_scale = anchor_scale
        self.image_size = image_size
        self.config = self._generate_configs()
        self.boxes = self._generate_boxes()

    def _generate_configs(self):
        """Generate configurations of anchor boxes."""
        return _generate_anchor_configs(self.min_level, self.max_level, self.num_scales, self.aspect_ratios)

    def _generate_boxes(self):
        """Generates multiscale anchor boxes."""
        boxes = _generate_anchor_boxes(self.image_size, self.anchor_scale, self.config)
        boxes = torch.from_numpy(boxes).float()
        return boxes

    def get_anchors_per_location(self):
        return self.num_scales * len(self.aspect_ratios)