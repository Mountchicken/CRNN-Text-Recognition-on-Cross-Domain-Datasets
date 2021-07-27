from __future__ import absolute_import
import sys

from torch.utils.data.sampler import SequentialSampler
sys.path.append('./')

import argparse
import os
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

import os.path as osp
import numpy as np
import math
import time

import torch
from torch import nn, optim
from torch.backends import cudnn
from torch.utils.data import DataLoader

from config import get_args

from lib.models.model_builder import ModelBuilder
from lib.datasets.dataset import lmdbDataset,randomSequentialSampler,alignCollate
from lib.datasets.concatdataset import ConcatDataset

from lib.trainers import Trainer
from lib.evaluators import Evaluator
from lib.utils.logging import Logger, TFLogger
from lib.utils.serialization import load_checkpoint
from lib.utils.labelmaps import CTCLabelConverter
def get_data(data_dir, height, width, batch_size, workers, is_train, keep_ratio):
  if isinstance(data_dir, list):
    dataset_list = []
    for data_dir_ in data_dir:
      dataset_list.append(lmdbDataset(data_dir_))
    dataset = ConcatDataset(dataset_list)
  else:
    dataset = lmdbDataset(data_dir)
  print('total image: ', len(dataset))

  if is_train:
    data_loader = DataLoader(dataset, batch_size=batch_size, num_workers=workers,
      shuffle=False, pin_memory=True, drop_last=False,sampler=randomSequentialSampler(dataset,batch_size=batch_size),
      collate_fn=alignCollate(imgH=height, imgW=width, keep_ratio=keep_ratio))
  else:
    data_loader = DataLoader(dataset, batch_size=batch_size, num_workers=workers,
      shuffle=False, pin_memory=True, drop_last=False,
      collate_fn=alignCollate(imgH=height, imgW=width, keep_ratio=keep_ratio))

  return dataset, data_loader

def main(args):
  """ set up random seeds """
  torch.manual_seed(args.seed)
  torch.cuda.manual_seed(args.seed)
  #torch.cuda.manual_seed_all(args.seed)
  cudnn.benchmark = True
  torch.backends.cudnn.deterministic = True
  args.cuda = args.cuda and torch.cuda.is_available()
  
  """ Set up tensorboard """
  if not args.evaluate:

    sys.stdout = Logger(osp.join(args.logs_dir, 'log.txt'))
    train_tfLogger = TFLogger(osp.join(args.logs_dir, 'train_tensorboard'))
    eval_tfLogger = TFLogger(osp.join(args.logs_dir, 'eval_tensorboard'))

  """ Set up dataloaders """
  if not args.evaluate:
    train_dataset, train_loader = \
      get_data(args.synthetic_train_data_dir,args.height, args.width, 
              args.batch_size, args.workers, True, args.keep_ratio)
    print(f'recognition nums: {len(args.alphabets)+1}')
    print(f'recogniton types:{args.alphabets}')
  test_dataset, test_loader = \
    get_data(args.test_data_dir, args.height, args.width, 
    args.batch_size, args.workers, False, args.keep_ratio)

  """ Set up model """
  model = ModelBuilder(arch=args.arch, rec_num_classes=len(args.alphabets)+1)

  """ Set up converter """
  converter = CTCLabelConverter(args.alphabets, args.max_len)

  """ Load from checkpoint """
  if args.evaluation_metric == 'accuracy':
    best_res = 0
  elif args.evaluation_metric == 'editdistance':
    best_res = math.inf
  else:
    raise ValueError("Unsupported evaluation metric:", args.evaluation_metric)
  start_epoch = 0
  start_iters = 0
  if args.resume:
    checkpoint = load_checkpoint(args.resume)
    model.load_state_dict(checkpoint['state_dict'])

    # compatibility with the epoch-wise evaluation version
    if 'epoch' in checkpoint.keys():
      start_epoch = checkpoint['epoch']
    else:
      start_iters = checkpoint['iters']
      start_epoch = int(start_iters // len(train_loader)) if not args.evaluate else 0
    best_res = checkpoint['best_res']
    print("=> Start iters {}  best res {:.1%}"
          .format(start_iters, best_res))
  
  if args.cuda:
    device = torch.device("cuda")
    model = model.to(device)
    #model = nn.DataParallel(model)

  """ Set up Evaluator """
  evaluator = Evaluator(model, converter, args.evaluation_metric, args.cuda)

  """ Only for evaluation """
  if args.evaluate:
    print('Test on {0}:'.format(args.test_data_dir))
    start = time.time()
    with torch.no_grad():
      evaluator.evaluate(test_loader)
    print('it took {0} s.'.format(time.time() - start))
    return

  """ Set up optimizer(default as adadelta with scheduler) """
  # Optimizer
  param_groups = model.parameters()
  param_groups = filter(lambda p: p.requires_grad, param_groups)
  optimizer = optim.Adadelta(param_groups, lr=args.lr, weight_decay=args.weight_decay)
  scheduler = optim.lr_scheduler.MultiStepLR(optimizer, milestones=[4,5], gamma=0.1)

  """ Set up Trainer"""
  # Trainer
  trainer = Trainer(model,converter, args.evaluation_metric, args.logs_dir,
                    iters=start_iters, best_res=best_res, grad_clip=args.grad_clip,
                    use_cuda=args.cuda)

  """ Start Training"""
  print('\n','-' * 40,'Start Training now','-' * 40)
  print('\n','-' * 40,'Evaluate for the first time','-' * 40)
  evaluator.evaluate(test_loader, step=0, tfLogger=eval_tfLogger)

  for epoch in range(start_epoch, args.epochs):
    current_lr = optimizer.param_groups[0]['lr']
    trainer.train(epoch, train_loader, optimizer, current_lr,
                  train_tfLogger=train_tfLogger,
                  evaluator=evaluator,
                  test_loader=test_loader,
                  eval_tfLogger=eval_tfLogger,
                  test_dataset=test_dataset)
    scheduler.step()
  # Final test
  print('Test with best model:')
  checkpoint = load_checkpoint(osp.join(args.logs_dir+'/weights/', 'model_best.pth.tar'))
  model.load_state_dict(checkpoint['state_dict'])
  evaluator.evaluate(test_loader, dataset=test_dataset)

  # Close the tensorboard logger
  train_tfLogger.close()
  eval_tfLogger.close()


if __name__ == '__main__':
  # parse the config
  args = get_args(sys.argv[1:])
  """ Creat file to save training result and training parameters """
  if not os.path.exists('./runs'):
    os.makedirs(f'./runs/train/', exist_ok=True)
    os.makedirs(f'./runs/test/', exist_ok=True)
  exp_name = 'exp' + str(len(os.listdir('./runs/train'))+1)
  # creat file
  os.makedirs(f'./runs/train/{exp_name}/', exist_ok=True)
  os.makedirs(f'./runs/train/{exp_name}/weights/', exist_ok=True)
  args.logs_dir = f'./runs/train/{exp_name}/'
  print('\n','-' * 40,'EXPERENCE Name','-' * 40)
  print('EXPERENCE Name: ', exp_name)

  # save training parameters
  args_dict = args.__dict__
  print('\n','-' * 40,'Training Configuration','-' * 40)
  print(args)
  with open(f'./runs/train/{exp_name}/train_config.txt', "w", encoding="utf-8") as f3:
      for eachArg, value in args_dict.items():
          f3.writelines(eachArg + ' : ' + str(value) + '\n')
  
  # print cuda
  print('\n','-' * 40,'GPU','-' * 40)
  print('device: ', torch.cuda.get_device_name())
  print('\n','-' * 40,'Training Begins Now','-' * 40)
  main(args)