import torch
import numpy as np
import torch.nn as nn
import torch.nn.functional as F

from model.module import DepthWiseSeparableConvModule as DWSConv


class HeadNet(nn.Module):
    """ Box Regression and Classification Nets """
    def __init__(self, n_features, out_channels, n_repeats):
        super(HeadNet, self).__init__()
        self.convs = nn.ModuleList()
        self.bns = nn.ModuleList()

        for _ in range(n_repeats):
            self.convs.append(DWSConv(n_features, n_features,
                                      bath_norm=False, relu=False))
            bn_levels = nn.ModuleList()
            for _ in range(5):
                bn = nn.BatchNorm2d(n_features, eps=1e-3, momentum=0.01)
                bn_levels.append(bn)
            self.bns.append(bn_levels)

        self.head = DWSConv(n_features, out_channels, bath_norm=False, relu=False, bias=True)

    def forward(self, inputs):
        outs = []

        for f_idx, f_map in enumerate(inputs):
            for conv, bn in zip(self.convs, self.bns):
                f_map = conv(f_map)
                f_map = bn[f_idx](f_map)
                f_map = F.relu(f_map)
            outs.append(self.head(f_map))

        return outs
