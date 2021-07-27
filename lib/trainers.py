from __future__ import print_function, absolute_import
import time
import os.path as osp
import sys
from tqdm import tqdm
import torch
from . import evaluation_metrics
from .utils.meters import AverageMeter
from .utils.serialization import  save_checkpoint
metrics_factory = evaluation_metrics.factory()

from config import get_args
global_args = get_args(sys.argv[1:])

class BaseTrainer(object):
  def __init__(self, model, converter, metric, logs_dir, iters=0, best_res=-1, grad_clip=-1, use_cuda=True):
    super(BaseTrainer, self).__init__()
    self.model = model
    self.metric = metric
    self.logs_dir = logs_dir
    self.iters = iters
    self.best_res = best_res
    self.grad_clip = grad_clip
    self.use_cuda = use_cuda
    self.converter = converter

    self.device = torch.device("cuda" if use_cuda else "cpu")

  def train(self, epoch, data_loader, optimizer, current_lr=0.0,
             train_tfLogger=None,evaluator=None, test_loader=None, eval_tfLogger=None,
            test_dataset=None):

    

    batch_time = AverageMeter()
    data_time = AverageMeter()
    losses = AverageMeter()

    end = time.time()
    loop = tqdm(enumerate(data_loader),total=len(data_loader),leave=False)
    for i, inputs in loop:
      self.iters += 1
      self.model.train()
      data_time.update(time.time() - end)
      input_dict = self._parse_data(inputs,self.converter)
      output_dict = self._forward(input_dict)
      batch_size = input_dict['images'].size(0)
      total_loss = 0
      loss_dict = {}
      total_loss = output_dict['loss']['loss_rec']
      losses.update(total_loss.item(), batch_size)
      optimizer.zero_grad()
      total_loss.backward()
      if self.grad_clip > 0:
        torch.nn.utils.clip_grad_norm_(self.model.parameters(), self.grad_clip)
      optimizer.step()
      loop.set_postfix(loss=total_loss.item())
      batch_time.update(time.time() - end)
      end = time.time()
      #====== TensorBoard logging ======#
      if self.iters % global_args.tensorboard_log_freq == 0:
        if train_tfLogger is not None:
          step = epoch * len(data_loader) + (i + 1)
          info = {
            'lr': current_lr,
            'loss': total_loss.item(), # this is total loss
          }
          ## add each loss
          for k, loss in loss_dict.items():
            info[k] = loss
          for tag, value in info.items():
            train_tfLogger.scalar_summary(tag, value, step)

      #====== evaluation ======#
      if self.iters % global_args.evaluation_freq == 0:

        if 'loss_rec' not in output_dict['loss']:
          is_best = True
          # self.best_res is alwarys equal to 1.0
          self.best_res = evaluator.evaluate(test_loader, step=self.iters, tfLogger=eval_tfLogger, dataset=test_dataset)
        else:
          res,pred_list, score_list, targ_list = evaluator.evaluate(test_loader, step=self.iters, tfLogger=eval_tfLogger)

          if self.metric == 'accuracy':
            is_best = res >= self.best_res
            self.best_res = max(res, self.best_res)
          elif self.metric == 'editdistance':
            is_best = res < self.best_res
            self.best_res = min(res, self.best_res)
          else:
            raise ValueError("Unsupported evaluation metric:", self.metric)
          loss_log = f'[Epoch {epoch}/{global_args.epochs}] Iteration {self.iters}//{len(data_loader)} \
                                Train loss: {total_loss.item():0.5f},'
          acc_log = f'{"Current_accuracy":17s}: {res:0.3f},\
                                {"Best_accuracy":17s}: {self.best_res:0.2f}'
          print(loss_log)
          print(acc_log)
          # show some result and log information
          with open(f'{self.logs_dir}/log_train.txt','a') as log:
            log.write(loss_log + '\n')
            log.write(acc_log + '\n')
            print('\n','-' * 40,f'Predicting results','-' * 40)
            dashed_line = '-' * 80
            head = f'{"Ground Truth":25s} | {"Prediction":25s} | Confidence Score & T/F'
            predicted_result_log = f'{dashed_line}\n{head}\n{dashed_line}\n'
            for label_string, pred_stirng, confidence in zip(targ_list[:30], pred_list[:30], score_list[:30]):
                predicted_result_log += f'{label_string:25s} | {pred_stirng:25s} | {confidence:0.4f}\t{str(pred_stirng == label_string)}\n'

            predicted_result_log += f'{dashed_line}'
            print(predicted_result_log)
            log.write(predicted_result_log + '\n')

        save_checkpoint({
          'state_dict': self.model.state_dict(),
          'iters': self.iters,
          'best_res': self.best_res,
        }, is_best, fpath=osp.join(self.logs_dir+'/weights', 'checkpoint.pth.tar'))

  def _parse_data(self, inputs):
    raise NotImplementedError

  def _forward(self, inputs, targets):
    raise NotImplementedError


class Trainer(BaseTrainer):
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
    self.model.train()
    output_dict = self.model(input_dict)
    return output_dict