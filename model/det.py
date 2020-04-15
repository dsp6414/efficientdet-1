import torch
import numpy as np
import torch.nn as nn
from itertools import chain

import config as cfg
from model.backbone import EfficientNet
from model.bifpn import BiFPN
from model.head import HeadNet
from model.module import ChannelAdjuster
from utils.utils import check_model_name, download_model_weights


class EfficientDet(nn.Module):
    def __init__(self, name):
        super(EfficientDet, self).__init__()
        check_model_name(name)

        self.backbone = EfficientNet(cfg.BACKBONE)

        self.adjuster = ChannelAdjuster(self.backbone.get_channels_list(),
                                        cfg.W_BIFPN)
        self.bifpn = nn.Sequential(*[BiFPN(cfg.W_BIFPN)
                                     for _ in range(cfg.D_BIFPN)])

        self.regresser = HeadNet(n_features=cfg.W_BIFPN,
                                 out_channels=cfg.NUM_ANCHORS * 4,
                                 n_repeats=cfg.D_CLASS)

        self.classifier = HeadNet(n_features=cfg.W_BIFPN,
                                  out_channels=cfg.NUM_ANCHORS * cfg.NUM_CLASSES,
                                  n_repeats=cfg.D_CLASS)

    def forward(self, x):
        features = self.backbone(x)

        features = self.adjuster(features)
        features = self.bifpn(features)

        cls_outputs = self.classifier(features)
        box_outputs = self.regresser(features)

        return cls_outputs, box_outputs

    @staticmethod
    def from_name(name=cfg.MODEL_NAME):
        model_to_return = EfficientDet(name)
        # model_to_return._load_backbone()
        return model_to_return

    @staticmethod
    def from_pretrained(name=cfg.MODEL_NAME):
        model_to_return = EfficientDet(name)

        if not cfg.MODEL_WEIGHTS.exists():
            download_model_weights(name, cfg.MODEL_WEIGHTS)

        model_to_return._load_weights(cfg.MODEL_WEIGHTS)
        print('Loaded checkpoint {}'.format(cfg.MODEL_WEIGHTS))
        return model_to_return

    def _initialize_weights(self):
        """ Initialize Model Weights before training from scratch """
        for module in chain(self.adjuster.modules(),
                            self.bifpn.modules(),
                            self.regresser.modules(),
                            self.classifier.modules()):
            if isinstance(module, nn.Conv2d):
                nn.init.kaiming_normal_(module.weight, mode='fan_out', nonlinearity='relu')
            if isinstance(module, nn.BatchNorm2d):
                nn.init.ones_(module.weight)
                nn.init.zeros_(module.bias)

        nn.init.zeros_(self.regresser.head.conv_pw.bias)
        nn.init.constant_(self.classifier.head.conv_pw.bias, -np.log((1 - 0.01) / 0.01))

    def _load_backbone(self, path):
        self.backbone.model.load_state_dict(torch.load(path), strict=True)

    def _load_weights(self, path):
        self.load_state_dict(torch.load(path))


if __name__ == '__main__':
    """ Quick test on parameters number """
    true_params = ['3.9M', '6.6M', '8.1M', '12.0M', '20.7M', '34.3M', '51.9M']

    for phi in [0, 1, 2, 3, 4, 5, 6]:
        model_name = 'efficientdet-d' + str(phi)
        model = EfficientDet(model_name)

        model_parameters = filter(lambda p: p.requires_grad, model.parameters())
        params = sum([np.prod(p.size()) for p in model_parameters])

        print('Phi: {}, params: {}M, true params: {}'.format(phi, params / 1000000, true_params[phi]))
