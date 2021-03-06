import argparse
import json
import os
import time

import torch
from pycocotools.coco import COCO
from pycocotools.cocoeval import COCOeval
from tqdm import tqdm

import config as cfg
from log.logger import logger
from utils import DetectionWrapper


def validate(model, device, writer=None, save_filename=None, best_score=0.0):
    """ COCO VAL2017 """
    model.eval()
    wrapper = DetectionWrapper(model, device)

    coco_gt = COCO(cfg.VAL_ANNOTATIONS)
    image_ids = coco_gt.getImgIds()

    batch_paths = []
    batch_ids = []

    processed_img_ids = []
    results = []

    with torch.no_grad():
        for idx, image_id in tqdm(enumerate(image_ids)):
            image_info = coco_gt.loadImgs(image_id)[0]
            image_path = cfg.VAL_SET / image_info['file_name']

            batch_paths.append(image_path)
            batch_ids.append(image_id)

            if (idx + 1) % cfg.BATCH_SIZE == 0:
                output = wrapper(batch_paths, batch_ids)
                for batch_out in output:
                    for det in batch_out:
                        image_id = int(det[0])
                        score = float(det[5])
                        coco_det = {
                            'image_id': image_id,
                            'bbox': det[1:5].tolist(),
                            'score': score,
                            'category_id': int(det[6]),
                        }
                        processed_img_ids.append(image_id)
                        results.append(coco_det)

                batch_paths = []
                batch_ids = []

    json.dump(results, open(cfg.COCO_RESULTS, 'w'), indent=4)

    coco_pred = coco_gt.loadRes(str(cfg.COCO_RESULTS))

    coco_eval = COCOeval(coco_gt, coco_pred, 'bbox')
    coco_eval.params.imgIds = image_ids
    coco_eval.evaluate()
    coco_eval.accumulate()
    coco_eval.summarize()

    if save_filename is not None and best_score < coco_eval.stats[0]:
        logger('Saving model weights with score: {}'.format(coco_eval.stats[0]))
        torch.save(model.state_dict(), cfg.WEIGHTS_PATH / save_filename)
        best_score = coco_eval.stats[0]

    if writer is not None:
        writer.add_scalar("Eval/mAP", coco_eval.stats[0], writer.eval_step)
        writer.eval_step += 1

    return model, writer, best_score
