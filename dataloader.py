import numpy as np
from PIL import Image
from pycocotools.coco import COCO
from torch.utils.data import DataLoader, Dataset

import config as cfg
from utils.transforms import *


class COCODataset(Dataset):
    """ MSCOCO Dataset. Following TF Implementation,
    annotation bbox format is yxyx """

    def __init__(self, path, annotations, transforms):
        super(COCODataset, self).__init__()
        self.path = path
        self.transforms = transforms
        self.coco = COCO(annotations)
        self.cat_ids = self.coco.getCatIds()
        self.img_ids = []
        self.img_infos = []
        self.invalid_img_ids = []
        self.invalid_img_infos = []

        for img_id in sorted(self.coco.imgs.keys()):
            annotation = self.coco.loadImgs([img_id])[0]
            if img_id in self.coco.imgToAnns and \
                    min(annotation['width'], annotation['height']) >= 32:
                self.img_ids.append(img_id)
                self.img_infos.append(annotation)
            else:
                self.invalid_img_ids.append(img_id)
                self.invalid_img_infos.append(annotation)

    def _get_img_ann(self, img_id):
        annotation_id = self.coco.getAnnIds(imgIds=[img_id])
        annotation = self.coco.loadAnns(annotation_id)
        bboxes = []
        cls = []

        for i, ann in enumerate(annotation):
            x1, y1, w, h = ann['bbox']
            if ann['area'] <= 0 or w < 1 or h < 1:
                continue
            bbox = [y1, x1, y1 + h, x1 + w]
            if ann['iscrowd'] == 1:
                # Skipping crowd bbox
                continue
            bboxes.append(bbox)
            cls.append(ann['category_id'])

        if bboxes:
            bboxes = np.array(bboxes, dtype=np.float32)
            cls = np.array(cls, dtype=np.int64)
        else:
            bboxes = np.zeros((0, 4), dtype=np.float32)
            cls = np.array([], dtype=np.int64)

        annotation = dict(img_id=img_id, bbox=bboxes, cls=cls)

        return annotation

    def __len__(self):
        return len(self.img_ids)

    def __getitem__(self, idx):
        img_id = self.img_ids[idx]
        img_info = self.img_infos[idx]

        image = Image.open(self.path / img_info['file_name']).convert('RGB')
        annotation = self._get_img_ann(img_id)

        if self.transforms is not None:
            image, annotation = self.transforms(image, annotation)

        return image, annotation


def get_loader(path, annotations):
    dataset = COCODataset(
        path=path, annotations=annotations,
        transforms=Compose([Resizer(cfg.MODEL.IMAGE_SIZE), ImageToNumpy(),
                            Normalizer(), NumpyToTensor()]))
    # TODO: Add Random Horizontal Flip and random crops augmentations
    loader = DataLoader(dataset=dataset, batch_size=cfg.BATCH_SIZE)
    return loader
