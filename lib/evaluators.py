from __future__ import print_function, absolute_import
import time
from datetime import datetime
import torch

import numpy as np
import sys

from . import evaluation_metrics
from .evaluation_metrics import Accuracy, EditDistance, RecPostProcess, word_Accuracy
from .utils.meters import AverageMeter
from .utils.visualization_utils import recognition_vis, stn_vis

metrics_factory = evaluation_metrics.factory()

from config import get_args
global_args = get_args(sys.argv[1:])

class BaseEvaluator(object):
  def __init__(self, model, converter, metric, use_cuda=True):
    super(BaseEvaluator, self).__init__()
    self.model = model
    self.metric = metric
    self.use_cuda = use_cuda
    self.device = torch.device("cuda" if use_cuda else "cpu")
    self.converter = converter

  def evaluate(self, data_loader, step=1, print_freq=1, tfLogger=None):
    self.model.eval()

    batch_time = AverageMeter()
    data_time  = AverageMeter()

    # forward the network
    images, rec_output, targets, losses = [], [], [], []
    file_names = []

    end = time.time()
    for i, inputs in enumerate(data_loader):
      data_time.update(time.time() - end)

      input_dict = self._parse_data(inputs, self.converter) # 解析batch，转为字典
      output_dict = self._forward(input_dict) # 前向传播

      batch_size = input_dict['images'].size(0)

      total_loss_batch = 0.
      total_loss_batch = output_dict['loss']['loss_rec'].item()*batch_size
      targets += inputs[1]
      losses.append(total_loss_batch)
      rec_output.append(output_dict['output']['pred_rec'])
      batch_time.update(time.time() - end)
      end = time.time()

      if (i + 1) % print_freq == 0:
        print('[{}]\t'
              'Evaluation: [{}/{}]\t'
              'Time {:.3f} ({:.3f})\t'
              'Data {:.3f} ({:.3f})\t'
              # .format(strftime("%Y-%m-%d %H:%M:%S", gmtime()),
              .format(datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                      i + 1, len(data_loader),
                      batch_time.val, batch_time.avg,
                      data_time.val, data_time.avg))

   

    losses = np.sum(losses) / (1.0 * (len(data_loader)-1)*batch_size)
    rec_output = torch.cat(rec_output)

    # evaluation with metric
    if global_args.evaluate_with_lexicon:
      eval_res = metrics_factory[self.metric+'_with_lexicon'](rec_output, targets, self.converter, file_names)
      print('lexicon0: {0}, {1:.3f}'.format(self.metric, eval_res[0]))
      print('lexicon50: {0}, {1:.3f}'.format(self.metric, eval_res[1]))
      print('lexicon1k: {0}, {1:.3f}'.format(self.metric, eval_res[2]))
      print('lexiconfull: {0}, {1:.3f}'.format(self.metric, eval_res[3]))
      eval_res = eval_res[0]
    else:
      pred_list, score_list, eval_res = metrics_factory[self.metric](rec_output, targets, self.converter) # accuracy
      print('lexicon0: {0}: {1:.3f}'.format(self.metric, eval_res))
     
    if tfLogger is not None:
      # (1) Log the scalar values
      info = {
        'loss': losses,
        self.metric: eval_res,
      }
      for tag, value in info.items():
        tfLogger.scalar_summary(tag, value, step)

    return eval_res, pred_list, score_list, targets


  def _parse_data(self, inputs):
    raise NotImplementedError

  def _forward(self, inputs):
    raise NotImplementedError
    

class Evaluator(BaseEvaluator):
  def _parse_data(self, inputs, converter):
    input_dict = {}
    imgs, label_encs = inputs
    images = imgs.to(self.device)
    labels, lengths = converter.encode(label_encs)
    input_dict['images'] = images
    input_dict['rec_targets'] = labels.to(self.device)
    input_dict['rec_lengths'] = lengths
    return input_dict

  def _forward(self, input_dict):
    self.model.eval()
    with torch.no_grad():
      output_dict = self.model(input_dict)
    return output_dict