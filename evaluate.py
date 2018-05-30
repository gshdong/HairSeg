import argparse
import os
import sys
import time

import warnings
warnings.simplefilter("ignore", UserWarning)
import numpy as np
import torch
import torch.backends.cudnn as cudnn
import torch.nn as nn
import torch.nn.parallel
import torchvision.models as models
import matplotlib.pyplot as plt

from hair_data import GeneralDataset, get_helen_test_data
from HairNet import DFN
from component.metrics import Acc_score
from tool_func import *

global args, device, save_dir

parser = argparse.ArgumentParser(
    description='Pytorch Hair Segmentation Evaluate')
parser.add_argument(
    'evaluate_name', type=str, help='evaluate name | that is save dir')
parser.add_argument(
    '--model_name', required=True, default='', type=str, metavar='model name')
parser.add_argument('--batch_size', required=True, type=int, help='batch_size')
parser.add_argument('--save', type=bool, help='save or visualize')
parser.add_argument('--gpu_ids', type=int, nargs='*')
args = parser.parse_args()


def main():
    # use the gpu or cpu as specificed
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    device_ids = None
    if args.gpu_ids is None:
        if torch.cuda.is_available():
            device_ids = list(range(torch.cuda.device_count()))
    else:
        device_ids = args.gpu_ids
        device = torch.device("cuda:{}".format(device_ids[0]))

    # set save dir
    ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
    save_dir = os.path.join(ROOT_DIR, 'evaluate_' + args.evaluate_name)
    os.makedirs(save_dir, exist_ok=True)

    # check model path
    model_path = os.path.join('logs', args.model_name, 'checkpoint.pth')
    if not os.path.exists(model_path):
        print('model path {} is not exists.'.format(model_path))
        sys.exit(1)

    # build the model
    model = DFN()
    model = nn.DataParallel(model, device_ids=device_ids)

    # loading checkpoint
    print("=> loading checkpoint '{}'".format(model_path))
    checkpoint = torch.load(model_path, map_location='cpu')
    model.load_state_dict(checkpoint['state_dict'])
    print("=> loaded checkpoint '{}' (epoch {})".format(
        model_path, checkpoint['epoch']))

    test_ds = get_helen_test_data(
        ['hair'], aug_setting_name='aug_512_0.6_multi_person')

    # ------ begin evaluate

    batch_time = AverageMeter()
    acc_hist_all = Acc_score(['hair'])
    acc_hist_single = Acc_score(['hair'])

    mean = [0.485, 0.456, 0.406]
    std = [0.229, 0.224, 0.225]
    # switch to evaluate mode
    model.eval()
    with torch.no_grad():
        end = time.time()
        batch_index = 0
        batch = None
        labels = None
        image_names = []
        data_len = len(test_ds.image_ids)
        for idx, image_id in enumerate(test_ds.image_ids):
            if batch_index == 0:
                batch = np.zeros((args.batch_size, 512, 512, 3))
                labels = np.zeros((args.batch_size, 512, 512))
            image = test_ds.load_image(image_id)
            batch[batch_index] = (image / 255 - mean) / std
            labels[batch_index] = test_ds.load_labels(image_id)
            image_names.append(
                os.path.basename(test_ds[image_id]['image_path'])[:-4])
            batch_index = batch_index + 1
            if batch_index < args.batch_size and idx != data_len - 1:
                continue

            batch_index = 0
            input = batch.transpose((0, 3, 1, 2))
            input, target = torch.from_numpy(input).to(
                torch.float).to(device), torch.from_numpy(labels).to(
                    torch.long).to(device)
            output = model(input)
            target = target.cpu().detach().numpy()
            pred = torch.argmax(output, dim=1).cpu().detach().numpy()
            acc_hist_all.collect(target, pred)
            acc_hist_single.collect(target, pred)
            f1_result = acc_hist_single.get_f1_results()['hair']

            input_images = unmold_input(batch)

            for b in range(input_images.shape[0]):
                print(input_images[b].shape, target[b].shape)
                gt_blended = blend_labels(input_images[b], target[b])
                predict_blended = blend_labels(input_images[b], pred[b])

                fig, axes = plt.subplots(ncols=2)
                axes[0].imshow(predict_blended)
                axes[0].set(title=f'predict:%04f' % (f1_result))
                axes[1].imshow(gt_blended)
                axes[1].set(title='ground-truth')

                if args.save:
                    save_path = os.path.join(save_dir, f'%04f_%s.png' %
                                             (f1_result, image_names[b]))
                    plt.savefig(save_path)
                else:
                    plt.show()
                plt.close(fig)
                acc_hist_single.reset()

            batch_time.update(time.time() - end)
            end = time.time()

            image_names = []

        f1_result = acc_hist_all.get_f1_results()['hair']
        print('Valiation: [{0}]\t'
              'Time {batch_time.val:.3f} ({batch_time.avg:.3f})\t'
              'Acc of f-score [{1}]'.format(
                  len(test_ds), f1_result, batch_time=batch_time))


if __name__ == '__main__':
    main()