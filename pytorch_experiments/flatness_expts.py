#!/usr/bin/env python
#SBATCH --mem=20000
#SBATCH --time=1-22:30
#SBATCH --mail-type=END
#SBATCH --mail-user=brando90@mit.edu
#SBATCH --array=1-1
#SBATCH --gres=gpu:1

"""
training an image classifier so that it overfits
----------------------------
"""
import time
from datetime import date
import calendar

import os
import sys
import subprocess

current_directory = os.getcwd() #The method getcwd() returns current working directory of a process.
sys.path.append(current_directory)

import numpy as np
from math import inf
import copy

import torch

from torch.autograd import Variable
import torch.optim as optim

import math

import data_classification as data_class

import nn_models as nn_mdls
import new_training_algorithms as tr_alg
import save_to_matlab_format as save2matlab
from stats_collector import StatsCollector
import metrics
import utils
import plot_utils
from good_minima_discriminator import get_errors_for_all_perturbations, perturb_model
from good_minima_discriminator import get_landscapes_stats_between_nets
from good_minima_discriminator import get_radius_errors_loss_list
from good_minima_discriminator import get_all_radius_errors_loss_list
from good_minima_discriminator import get_all_radius_errors_loss_list_interpolate
from good_minima_discriminator import RandLandscapeInspector
from good_minima_discriminator import get_norm
from good_minima_discriminator import divide_params_by
from good_minima_discriminator import print_evaluation_of_nets

from new_training_algorithms import evalaute_mdl_data_set
from new_training_algorithms import Trainer
from new_training_algorithms import dont_train
from new_training_algorithms import initialize_to_zero

from landscape_inspector_flatness_sharpness import LandscapeInspector

from pdb import set_trace as st

import argparse

from maps import NamedDict

import matplotlib as mpl
import matplotlib.pyplot as plt

import socket

parser = argparse.ArgumentParser(description='Flatness Submission Script')
''' setup params '''
#parser.add_argument('-cuda','--enable-cuda',action='store_true',help='Enable cuda/gpu')
parser.add_argument("-seed", "--seed", type=int, default=None,
                    help="The number of games to simulate")
parser.add_argument("-exptlabel", "--exptlabel", type=str, default='nolabel',
                    help="experiment label")
parser.add_argument('-dont_save_expt_results','--dont_save_expt_results',action='store_true',
                    help='If on it does not saves experiment results')
''' NN related arguments '''
parser.add_argument("-epochs", "--epochs", type=int, default=None,
                    help="The number of games to simulate")
parser.add_argument("-mdl", "--mdl", type=str, default='debug',
                    help="mdl") # options: debug, cifar_10_tutorial_net, BoixNet, LiaoNet
parser.add_argument('-use_bn','--use_bn',action='store_true',
                    help='turns on BN')
parser.add_argument('-dont_standardize_data','--dont_standardize_data',action='store_true',
                    help='uses x-u/s, standardize data')
parser.add_argument("-label_corrupt_prob", "--label_corrupt_prob", type=float, default=0.0,
                    help="The probability of a label getting corrupted")
''' training argument '''
parser.add_argument("-train_alg", "--train_alg", type=str, default='SGD',
                    help="Training algorithm to use")
parser.add_argument("-noise_level", "--noise_level", type=float, default=0.0001,
                    help="Noise level for perturbation")
parser.add_argument("-not_pert_w_norm2", "--not_pert_w_norm2",action='store_false',
                    help="Noise level for perturbation")
parser.add_argument("-epsilon", "--epsilon", type=float, default=0.05,
                    help="Epsilon error.")
parser.add_argument('-save_every_epoch','--save_every_epoch',action='store_true',
                    help='save model at the end of every epoch')
''' radius expt params '''
parser.add_argument("-net_name", "--net_name", type=str, default='NL',
                    help="Training algorithm to use")
parser.add_argument("-nb_dirs", "--nb_dirs", type=int, default=100,
                    help="# Random Directions")
parser.add_argument("-r_large", "--r_large", type=float, default=30,
                    help="How far to go on the radius to the end from center")
''' other '''
parser.add_argument('-email','--email',action='store_true',
                    help='Enable cuda/gpu')
parser.add_argument("-gpu_id", "--gpu_id", type=int, default=0,
                    help="Training algorithm to use")
''' process args '''
args = parser.parse_args()
sj, satid = 0, 0
if 'SLURM_ARRAY_TASK_ID' in os.environ and 'SLURM_JOBID' in os.environ:
    satid = int(os.environ['SLURM_ARRAY_TASK_ID'])
    sj = int(os.environ['SLURM_JOBID'])

print(f'storing results? = {not args.dont_save_expt_results}')

def main(plot=True):
    hostname = utils.get_hostname()
    ''' cuda '''
    use_cuda = torch.cuda.is_available()
    device = torch.device("cuda" if use_cuda else "cpu")
    print(f'device = {device}')
    ''' '''
    store_net = True
    other_stats = dict({'sj':sj,'satid':satid,'hostname':hostname})
    ''' reproducibility setup/params'''
    #num_workers = 2 # how many subprocesses to use for data loading. 0 means that the data will be loaded in the main process.
    githash = subprocess.check_output(["git", "describe", "--always"]).strip()
    seed = args.seed
    if seed is None: # if seed is None it has not been set, so get a random seed, else use the seed that was set
        seed = int.from_bytes(os.urandom(7), byteorder="big")
    print(f'seed: {seed}')
    ## SET SEED/determinism
    num_workers = 3
    torch.manual_seed(seed)
    #torch.backends.cudnn.deterministic=True
    ''' date parameters setup'''
    today_obj = date.today() # contains datetime.date(year, month, day); accessible via .day etc
    day = today_obj.day
    month = calendar.month_name[today_obj.month]
    setup_time = time.time()
    ''' filenames '''
    results_root = './test_runs_flatness2'
    expt_folder = f'flatness_{month}_label_corrupt_prob_{args.label_corrupt_prob}_exptlabel_{args.exptlabel}'
    ## filenames
    matlab_file_name = f'flatness_{day}_{month}_sj_{sj}_staid_{satid}_seed_{seed}_{hostname}'
    net_file_name = f'net_{day}_{month}_sj_{sj}_staid_{satid}_seed_{seed}_{hostname}'
    ## experiment path
    expt_path = os.path.join(results_root,expt_folder)
    ''' experiment params '''
    suffle_test = False
    shuffle_train = True
    nb_epochs = 4 if args.epochs is None else args.epochs
    batch_size = 256
    #batch_size_train,batch_size_test = batch_size,batch_size
    batch_size_train = batch_size
    batch_size_test = 256
    data_path = './data'
    ''' get NN '''
    mdl = args.mdl
    do_bn = args.use_bn
    other_stats = dict({'mdl':mdl,'do_bn':do_bn},**other_stats)
    ##
    classes = ('plane', 'car', 'bird', 'cat', 'deer', 'dog', 'frog', 'horse', 'ship', 'truck')
    nets = []
    print(f'model = {mdl}')
    if mdl == 'cifar_10_tutorial_net':
        suffle_test = False
        net = nn_mdls.Net()
        nets.append(net)
    elif mdl == 'debug':
        suffle_test = False
        nb_conv_layers=1
        ## conv params
        Fs = [3]*nb_conv_layers
        Ks = [2]*nb_conv_layers
        ## fc params
        FC = len(classes)
        C,H,W = 3,32,32
        net = nn_mdls.LiaoNet(C,H,W,Fs,Ks,FC,do_bn)
        nets.append(net)
    elif mdl == 'BoixNet':
        batch_size_train = 256
        batch_size_test = 256
        ##
        batch_size = batch_size_train
        suffle_test = False
        ## conv params
        nb_filters1,nb_filters2 = 32, 32
        nb_filters1, nb_filters2 = 32, 32
        kernel_size1,kernel_size2 = 5,5
        ## fc params
        nb_units_fc1,nb_units_fc2,nb_units_fc3 = 512,256,len(classes)
        C,H,W = 3,32,32
        net = nn_mdls.BoixNet(C,H,W,nb_filters1,nb_filters2, kernel_size1,kernel_size2, nb_units_fc1,nb_units_fc2,nb_units_fc3,do_bn)
        nets.append(net)
    elif mdl == 'LiaoNet':
        suffle_test = False
        nb_conv_layers=5
        ## conv params
        Fs = [32]*nb_conv_layers
        Ks = [10]*nb_conv_layers
        ## fc params
        FC = len(classes)
        C,H,W = 3,32,32
        net = nn_mdls.LiaoNet(C,H,W,Fs,Ks,FC,do_bn)
        nets.append(net)
    elif mdl == 'GBoixNet':
        #batch_size_train = 16384 # 2**14
        #batch_size_test = 16384
        batch_size_train = 2**10
        batch_size_test = 2**10
        ##
        batch_size = batch_size_train
        suffle_test = False
        ## conv params
        nb_conv_layers=2
        Fs = [24]*nb_conv_layers
        Ks = [5]*nb_conv_layers
        ## fc params
        FCs = [len(classes)]
        ##
        CHW = (3,32,32)
        net = nn_mdls.GBoixNet(CHW,Fs,Ks,FCs,do_bn)
        nets.append(net)
    elif mdl == 'interpolate':
        suffle_test = True
        batch_size = 2**10
        batch_size_train, batch_size_test = batch_size, batch_size
        iterations = inf # controls how many epochs to stop before returning the data set error
        #iterations = 1 # controls how many epochs to stop before returning the data set error
        ''' '''
        path_nl = os.path.join(results_root,'flatness_27_April_label_corrupt_prob_0.0_exptlabel_GB_24_24_10_2C1FC_momentum_NL_polestar/net_27_April_sj_343_staid_1_seed_56134200848018679')
        path_rl_nl = os.path.join(results_root,'flatness_27_April_label_corrupt_prob_0.0_exptlabel_GB_24_24_10_2C1FC_momentum_RLNL_polestar/net_27_April_sj_345_staid_1_seed_57700439347820897')
        ''' restore nets'''
        net_nl = utils.restore_entire_mdl(path_nl)
        net_rlnl = utils.restore_entire_mdl(path_rl_nl)
        nets.append(net_nl)
        nets.append(net_rlnl)
    elif mdl == 'radius_flatness':
        suffle_test = True
        batch_size = 2**10
        batch_size_train, batch_size_test = batch_size, batch_size
        iterations = 11 # controls how many epochs to stop before returning the data set error
        #iterations = inf  # controls how many epochs to stop before returning the data set error
        other_stats = dict({'iterations':iterations},**other_stats)
        ''' load net '''
        if args.net_name == 'NL':
            #path = os.path.join(results_root,'flatness_28_March_label_corrupt_prob_0.0_exptlabel_BoixNet_polestar_300_stand_natural_labels/net_28_March_206')
            path = os.path.join(results_root,'flatness_27_April_label_corrupt_prob_0.0_exptlabel_GB_24_24_10_2C1FC_momentum_NL_polestar/net_27_April_sj_343_staid_1_seed_56134200848018679')
        else: # RLNL
            #path = os.path.join(results_root,'flatness_28_March_label_corrupt_prob_0.0_exptlabel_re_train_RLBoixNet_noBN_polestar_150/net_28_March_18')
            path = os.path.join(results_root,'flatness_27_April_label_corrupt_prob_0.0_exptlabel_GB_24_24_10_2C1FC_momentum_RLNL_polestar/net_27_April_sj_345_staid_1_seed_57700439347820897')
        ''' restore nets'''
        net = utils.restore_entire_mdl(path)
        nets.append(net)
        store_net = False
    elif mdl == 'sharpness':
        suffle_test=False #doesn't matter
        ''' load net '''
        if args.net_name == 'NL':
            #path = os.path.join(results_root,'flatness_28_March_label_corrupt_prob_0.0_exptlabel_BoixNet_polestar_300_stand_natural_labels/net_28_March_206')
            path = os.path.join(results_root,'flatness_27_April_label_corrupt_prob_0.0_exptlabel_GB_24_24_10_2C1FC_momentum_NL_polestar/net_27_April_sj_343_staid_1_seed_56134200848018679')
            path_adverserial_data = os.path.join('./data/sharpness_data_NL/','sdata_NL_net_27_April_sj_343_staid_1_seed_56134200848018679.npz')
        else: # RLNL
            #path = os.path.join(results_root,'flatness_28_March_label_corrupt_prob_0.0_exptlabel_re_train_RLBoixNet_noBN_polestar_150/net_28_March_18')
            path = os.path.join(results_root,'flatness_27_April_label_corrupt_prob_0.0_exptlabel_GB_24_24_10_2C1FC_momentum_RLNL_polestar/net_27_April_sj_345_staid_1_seed_57700439347820897')
            path_adverserial_data = os.path.join('./data/sharpness_data_RLNL/','sdata_RLNL_net_27_April_sj_345_staid_1_seed_57700439347820897.npz')
        ''' restore nets'''
        net = torch.load(path)
        nets.append(net)
        store_net = False
    elif mdl == 'divide_constant':
        ''' ''' # both false because we want low variation on the output of the error
        iterations = inf # controls how many epochs to stop before returning the data set error
        #iterations = 11 # controls how many epochs to stop before returning the data set error
        batch_size = 2**10
        batch_size_train, batch_size_test = batch_size, batch_size
        shuffle_train = True
        suffle_test = False
        ''' load net '''
        ## NL
        #path_nl = os.path.join(results_root,'flatness_27_April_label_corrupt_prob_0.0_exptlabel_GB_24_24_10_2C1FC_momentum_NL_polestar/net_27_April_sj_343_staid_1_seed_56134200848018679')
        #path_nl = os.path.join(results_root,'flatness_May_label_corrupt_prob_0.0_exptlabel_SGD_ManyRuns_Momentum0.9/net_17_May_sj_641_staid_5_seed_31866864409272026_polestar-old')
        path_nl = os.path.join(results_root,'flatness_May_label_corrupt_prob_0.0_exptlabel_MovieNL_lr_0.01_momentum_0.9/net_22_May_sj_1168_staid_1_seed_59937023958974481_polestar-old_epoch_173')
        ## RLNL
        #path_rlnl = os.path.join(results_root,'flatness_27_April_label_corrupt_prob_0.0_exptlabel_GB_24_24_10_2C1FC_momentum_RLNL_polestar/net_27_April_sj_345_staid_1_seed_57700439347820897')
        path_rlnl = os.path.join(results_root,'flatness_May_label_corrupt_prob_0.0_exptlabel_MovieRLNLmdls_label_corruption0.5_lr_0.01_momentum_0.9/net_22_May_sj_1172_staid_1_seed_38150714758131256_polestar-old_epoch_148')
        ##
        net_nl = torch.load(path_nl)
        net_rlnl = torch.load(path_rlnl)
        ''' modify nets '''
        #W_nl = 0.0102*get_norm(net_nl,l=2)
        #W_rlnl = 0.0102*get_norm(net_rlnl,l=2)
        W_nl = 1
        #W_rlnl = 1
        W_rlnl = get_norm(net_rlnl, l=2) / get_norm(net_nl, l=2)
        print(f'normalizer being used: W_nl={W_nl},W_rlnl={W_rlnl}')
        print(f'norm of weight BEFORE division: get_norm(net_nl,l=2)={get_norm(net_nl,l=2)}, get_norm(net_rlnl,l=2)={get_norm(net_rlnl,l=2)}')
        #st()
        #net_nl = divide_params_by(W_nl, net_nl)
        net_rlnl = divide_params_by(W_rlnl, net_rlnl)
        print(f'norm of weight AFTER division: get_norm(net_nl,l=2)={get_norm(net_nl,l=2)}, get_norm(net_rlnl,l=2)={get_norm(net_rlnl,l=2)}')
        nets.append(net_nl)
        nets.append(net_rlnl)
    elif mdl == 'load_nl_and_rlnl':
        ''' load net '''
        # NL
        #path = os.path.join(results_root,'flatness_27_April_label_corrupt_prob_0.0_exptlabel_GB_24_24_10_2C1FC_momentum_NL_polestar/net_27_April_sj_343_staid_1_seed_56134200848018679')
        path = os.path.join(results_root,'flatness_May_label_corrupt_prob_0.0_exptlabel_MovieNL_lr_0.01_momentum_0.9/net_22_May_sj_1168_staid_1_seed_59937023958974481_polestar-old_epoch_173')
        net = torch.load(path)
        nets.append(net)
        # RLNL
        #path_rlnl = os.path.join(results_root,'flatness_27_April_label_corrupt_prob_0.0_exptlabel_GB_24_24_10_2C1FC_momentum_RLNL_polestar/net_27_April_sj_345_staid_1_seed_57700439347820897')
        path_rlnl = os.path.join(results_root,'flatness_May_label_corrupt_prob_0.0_exptlabel_MovieRLNLmdls_label_corruption0.5_lr_0.01_momentum_0.9/net_22_May_sj_1172_staid_1_seed_38150714758131256_polestar-old_epoch_148')
        net_rlnl = torch.load(path_rlnl)
        nets.append(net_rlnl)
        other_stats = dict({'path': path, 'path_rlnl': path_rlnl}, **other_stats)
    elif mdl == 'load_one_net':
        ''' load net '''
        ## 1.0
        #path = os.path.join(results_root,'flatness_May_label_corrupt_prob_1.0_exptlabel_MoreRLInits_lr_0.01_momentum_0.9/net_18_May_sj_677_staid_5_seed_59829215980468561_polestar-old')
        #path = os.path.join(results_root,'flatness_May_label_corrupt_prob_1.0_exptlabel_MoreRLInits_lr_0.01_momentum_0.9/net_18_May_sj_674_staid_2_seed_41701220392276729_polestar-old')
        #path = os.path.join(results_root,'flatness_May_label_corrupt_prob_1.0_exptlabel_MoreRLInits_lr_0.01_momentum_0.9/net_18_May_sj_676_staid_4_seed_54684501513999395_polestar-old')
        #path = os.path.join(results_root,'flatness_May_label_corrupt_prob_1.0_exptlabel_MoreRLInits_lr_0.01_momentum_0.9/net_18_May_sj_673_staid_1_seed_57779243890869381_polestar-old')
        ## 0.8
        #path = os.path.join(results_root,'flatness_May_label_corrupt_prob_0.8_exptlabel_MoreRLInits_lr_0.01_momentum_0.9/net_18_May_sj_10950499_staid_2_seed_9006288257684036_node004.cm.cluster')
        ## 0.7
        #path = os.path.join(results_root, 'flatness_May_label_corrupt_prob_0.7_exptlabel_MoreRLInits_lr_0.01_momentum_0.9/net_18_May_sj_10950496_staid_4_seed_55005976886300675_node004.cm.cluster')
        ## 0.6
        #path = os.path.join(results_root,'flatness_May_label_corrupt_prob_0.6_exptlabel_MoreRLInits_lr_0.01_momentum_0.9/net_18_May_sj_780_staid_1_seed_2583642406948920_polestar-old')
        ## 0.5
        #path = os.path.join(results_root,'flatness_May_label_corrupt_prob_0.5_exptlabel_MoreRLInits_lr_0.01_momentum_0.9/net_18_May_sj_0_staid_0_seed_45042856912691161_polestar')
        ## 0.4
        #path = os.path.join(results_root,'flatness_May_label_corrupt_prob_0.4_exptlabel_MoreRLInits_lr_0.01_momentum_0.9/net_18_May_sj_781_staid_2_seed_8233191066269519_polestar-old')
        ## 0.3
        #path = os.path.join(results_root,'flatness_May_label_corrupt_prob_0.3_exptlabel_MoreRLInits_lr_0.01_momentum_0.9/net_18_May_sj_786_staid_1_seed_22981577159876369_polestar-old')
        ## 0.2
        #path = os.path.join(results_root,'flatness_May_label_corrupt_prob_0.2_exptlabel_MoreRLInits_lr_0.01_momentum_0.9/net_18_May_sj_683_staid_2_seed_62757268370691842_polestar-old')
        ## 0.1
        #path = os.path.join(results_root,'flatness_May_label_corrupt_prob_0.1_exptlabel_MoreRLInits_lr_0.01_momentum_0.9/net_18_May_sj_784_staid_1_seed_30006724853600989_polestar-old')
        ## 0.05
        #path = os.path.join(results_root, 'flatness_May_label_corrupt_prob_0.05_exptlabel_MoreRLInits_lr_0.01_momentum_0.9/net_18_May_sj_802_staid_3_seed_11347587066395527_polestar-old')
        ## 0.01
        #path = os.path.join(results_root,'flatness_May_label_corrupt_prob_0.01_exptlabel_MoreRLInits_lr_0.01_momentum_0.9/net_18_May_sj_811_staid_6_seed_41018024023337929_polestar-old')
        ## 0.005
        #path = os.path.join(results_root, 'flatness_May_label_corrupt_prob_0.005_exptlabel_MoreRLInits_lr_0.01_momentum_0.9/net_20_May_sj_842_staid_1_seed_36581971144286716_polestar-old')
        ## 0.001
        #path = os.path.join(results_root,'flatness_May_label_corrupt_prob_0.001_exptlabel_MoreRLInits_lr_0.01_momentum_0.9/net_18_May_sj_10951638_staid_4_seed_68150886325028224_node004.cm.cluster')
        ## 0.0005
        #path = os.path.join(results_root, 'flatness_May_label_corrupt_prob_0.0005_exptlabel_MoreRLInits_lr_0.01_momentum_0.9/net_20_May_sj_843_staid_2_seed_40516994826727806_polestar-old')
        ## 0.0001
        path = os.path.join(results_root,'flatness_May_label_corrupt_prob_0.0001_exptlabel_MoreRLInits_lr_0.01_momentum_0.9/net_18_May_sj_10951641_staid_2_seed_55373094418342903_node001.cm.cluster')
        ## 5e-5
        #path = os.path.join(results_root,'flatness_May_label_corrupt_prob_5e-05_exptlabel_MoreRLInits_lr_0.01_momentum_0.9/net_21_May_sj_936_staid_5_seed_29221402749608965_polestar-old')
        ## 5e-6
        #path = os.path.join(results_root,'flatness_May_label_corrupt_prob_5e-06_exptlabel_MoreRLInits_lr_0.01_momentum_0.9/net_21_May_sj_949_staid_5_seed_71926857789820853_polestar-old')
        net = torch.load(path)
        nets.append(net)
        other_stats = dict({'path': path}, **other_stats)
    else:
        print('RESTORED FROM PRE-TRAINED NET')
        suffle_test = False
        ''' RESTORED PRE-TRAINED NET '''
        # example name of file, os.path.join(results_root,expt_path,f'net_{day}_{month}_{seed}')
        # args.net_path = 'flatness_27_March_label_corrupt_prob_0_exptlabel_BoixNet_stand_600_OM/net_27_Match_64'
        path_to_mdl = args.mdl
        path = os.path.join(results_root,path_to_mdl)
        # net = utils.restore_entire_mdl(path)
        net = torch.load(path)
        nets.append(net)
    print(f'nets = {nets}')
    ''' cuda/gpu '''
    for net in nets:
        net.to(device)
    nb_params = nn_mdls.count_nb_params(net)
    ''' get data set '''
    #st()
    standardize = not args.dont_standardize_data # x - mu / std , [-1,+1]
    trainset,trainloader, testset,testloader, classes_data = data_class.get_cifer_data_processors(data_path,batch_size_train,batch_size_test,num_workers,args.label_corrupt_prob,shuffle_train=shuffle_train,suffle_test=suffle_test,standardize=standardize)
    #check_order_data(trainloader)
    #st()
    if classes_data != classes:
        raise ValueError(f'Pre specificed classes {classes} does not match data classes {classes_data}.')
    ''' Cross Entropy + Optmizer '''
    lr = 0.01
    momentum = 0.9
    expt_path = f'{expt_path}_lr_{lr}_momentum_{momentum}'
    ## Error/Loss criterions
    error_criterion = metrics.error_criterion
    criterion = torch.nn.CrossEntropyLoss()
    #criterion = torch.nn.MultiMarginLoss()
    #criterion = torch.nn.MSELoss(size_average=True)
    optimizer = optim.SGD(net.parameters(), lr=lr, momentum=momentum)
    other_stats = dict({'nb_epochs':nb_epochs,'batch_size':batch_size,'mdl':mdl,'lr':lr,'momentum':momentum, 'seed':seed,'githash':githash},**other_stats)
    ''' stats collector '''
    stats_collector = StatsCollector(net)
    ''' Verify model you got has the right error'''
    train_loss_epoch, train_error_epoch = evalaute_mdl_data_set(criterion, error_criterion, net, trainloader, device)
    test_loss_epoch, test_error_epoch = evalaute_mdl_data_set(criterion, error_criterion, net, testloader, device)
    print(f'train_loss_epoch, train_error_epoch  = {train_loss_epoch}, {train_error_epoch} \n test_loss_epoch, test_error_epoch  = {test_loss_epoch}, {test_error_epoch}')
    ''' Is it over parametrized?'''
    overparametrized = len(trainset)<nb_params # N < W ?
    print(f'Model overparametrized? N, W = {len(trainset)} vs {nb_params}')
    print(f'Model overparametrized? N < W = {overparametrized}')
    other_stats = dict({'overparametrized':overparametrized,'nb_params':nb_params}, **other_stats)
    ''' report time for setup'''
    seconds_setup,minutes_setup,hours_setup = utils.report_times(setup_time,'setup')
    other_stats = dict({'seconds_setup': seconds_setup, 'minutes_setup': minutes_setup, 'hours_setup': hours_setup}, **other_stats)
    ''' Start Training '''
    training_time = time.time()
    print(f'----\nSTART training: label_corrupt_prob={args.label_corrupt_prob},nb_epochs={nb_epochs},batch_size={batch_size},lr={lr},momentum={momentum},mdl={mdl},batch-norm={do_bn},nb_params={nb_params}')
    ## START TRAIN
    if args.train_alg == 'SGD':
        #iterations = 4 # the number of iterations to get a sense of test error, smaller faster larger more accurate. Grows as sqrt(n) though.
        iterations = inf
        ''' set up Trainer '''
        if args.save_every_epoch:
            save_every_epoch = args.save_every_epoch
            trainer = Trainer(trainloader, testloader, optimizer, criterion, error_criterion, stats_collector, device, expt_path,net_file_name,save_every_epoch)
        else:
            trainer = Trainer(trainloader,testloader, optimizer,criterion,error_criterion, stats_collector, device)
        last_errors = trainer.train_and_track_stats(net, nb_epochs,iterations)
        ''' Test the Network on the test data '''
        train_loss_epoch, train_error_epoch, test_loss_epoch, test_error_epoch = last_errors
        print(f'train_loss_epoch={train_loss_epoch} \ntrain_error_epoch={train_error_epoch} \ntest_loss_epoch={test_loss_epoch} \ntest_error_epoch={test_error_epoch}')
    elif args.train_alg == 'pert':
        ''' batch sizes '''
        batch_size_train, batch_size_test = 50*10**3, 10*10**3
        ''' number of repetitions '''
        nb_perturbation_trials = nb_epochs
        ''' noise level '''
        nb_layers = len(list(net.parameters()))
        noise_level = args.noise_level
        perturbation_magnitudes = nb_layers*[noise_level]
        print(f'noise_level={noise_level}')
        ''' locate where to save it '''
        folder_name_noise = f'noise_{perturbation_magnitudes[0]}'
        expt_path = os.path.join(expt_path,folder_name_noise)
        matlab_file_name = f'noise_{perturbation_magnitudes}_{matlab_file_name}'
        ## TODO collect by perburbing current model X number of times with current perturbation_magnitudes
        use_w_norm2 = args.not_pert_w_norm2
        train_loss,train_error,test_loss,test_error = get_errors_for_all_perturbations(net,perturbation_magnitudes,use_w_norm2,device,nb_perturbation_trials,stats_collector,criterion,error_criterion,trainloader,testloader)
        print(f'noise_level={noise_level},train_loss,train_error,test_loss,test_error={train_loss},{train_error},{test_loss},{test_error}')
        other_stats = dict({'perturbation_magnitudes':perturbation_magnitudes}, **other_stats)
    elif args.train_alg == 'interpolate':
        ''' prints stats before interpolation'''
        print_evaluation_of_nets(net_nl, net_rlnl, criterion, error_criterion, trainloader, testloader, device, iterations)
        ''' do interpolation of nets'''
        nb_interpolations = nb_epochs
        interpolations = np.linspace(0,1,nb_interpolations)
        get_landscapes_stats_between_nets(net_nl,net_rlnl,interpolations, device,stats_collector,criterion,error_criterion,trainloader,testloader,iterations)
        ''' print stats of the net '''
        other_stats = dict({'interpolations':interpolations},**other_stats)
        #print_evaluation_of_nets(net_nl, net_rlnl, criterion, error_criterion, trainloader, testloader, device, iterations)
    elif args.train_alg == 'brando_chiyuan_radius_inter':
        r_large = args.r_large ## check if this number is good
        nb_radius_samples = nb_epochs
        interpolations = np.linspace(0,1,nb_radius_samples)
        expt_path = os.path.join(expt_path+f'_RLarge_{r_large}')
        ''' '''
        nb_dirs = args.nb_dirs
        stats_collector = StatsCollector(net,nb_dirs,nb_epochs)
        get_all_radius_errors_loss_list_interpolate(nb_dirs,net,r_large,interpolations,device,stats_collector,criterion,error_criterion,trainloader,testloader,iterations)
        other_stats = dict({'nb_dirs':nb_dirs,'interpolations':interpolations,'nb_radius_samples':nb_radius_samples,'r_large':r_large},**other_stats)
    elif args.train_alg == 'sharpness':
        ''' load the data set '''
        print('About to load the data set')
        shuffle_train = True
        #batch_size = 2**10
        batch_size = 2**5
        batch_size_train, batch_size_test = batch_size, batch_size
        iterations = inf  # controls how many epochs to stop before returning the data set error
        #eps = 2500/50000
        eps = 1 / 50000
        other_stats = dict({'iterations':iterations,'eps':eps},**other_stats)
        trainset,trainloader = data_class.load_only_train(path_adverserial_data,eps,batch_size_train,shuffle_train,num_workers)
        ''' three musketeers '''
        print('Preparing the three musketeers')
        net_pert = copy.deepcopy(net)
        #nn_mdls.reset_parameters(net_pert)
        net_original = dont_train(net)
        #net_original = net
        initialize_to_zero(net_original)
        debug=False
        if debug:
            ## conv params
            nb_conv_layers=3
            Fs = [24]*nb_conv_layers
            Ks = [5]*nb_conv_layers
            ## fc params
            FCs = [len(classes)]
            CHW = (3,32,32)
            net_pert = nn_mdls.GBoixNet(CHW,Fs,Ks,FCs,do_bn).to(device)
        print('Musketeers are prepared')
        ''' optimizer + criterion stuff '''
        optimizer = optim.SGD(net_pert.parameters(), lr=lr, momentum=momentum)
        #optimizer = optim.Adam(net_pert.parameters(), lr=lr)
        error_criterion = metrics.error_criterion
        criterion = torch.nn.CrossEntropyLoss()
        #criterion = torch.nn.MultiMarginLoss()
        #criterion = torch.nn.MultiLabelMarginLoss()
        ''' Landscape Inspector '''
        save_all_learning_curves = True
        save_all_perts = False
        nb_lambdas = 1
        lambdas = np.linspace(1,10,nb_lambdas)
        print('Do Sharpness expt!')
        sharpness_inspector = LandscapeInspector(net_original,net_pert, nb_epochs,iterations, trainloader,testloader, optimizer,
            criterion,error_criterion, device, lambdas,save_all_learning_curves=save_all_learning_curves,save_all_perts=save_all_perts)
        sharpness_inspector.do_sharpness_experiment()
    elif args.train_alg == 'flatness_bs':
        ''' BS params '''
        r_initial = 50
        epsilon = args.epsilon ## check if this number is good
        # nb_radius_samples = nb_epochs could use this number as a cap of # iterations of BS
        expt_path = os.path.join(expt_path+f'_BS')
        ''' Do BS '''
        precision = 0.001
        nb_dirs = args.nb_dirs
        # stats_collector = StatsCollector(net,nb_dirs,nb_epochs) TODO
        rand_inspector = RandLandscapeInspector(epsilon,net,r_initial,device,criterion,error_criterion,trainloader,testloader,iterations)
        rand_inspector.get_faltness_radii_for_isotropic_directions(nb_dirs=nb_dirs,precision=precision)
        other_stats = dict({'nb_dirs':nb_dirs,'flatness_radii':rand_inspector.flatness_radii},**other_stats)
    elif args.train_alg == 'evaluate_nets':
        plot = False
        print('')
        iterations = inf
        print(f'W_nl = {W_nl}')
        print(f'W_rlnl = {W_rlnl}')
        ''' train errors '''
        loss_nl_train, error_nl_train = evalaute_mdl_data_set(criterion, error_criterion, net_nl, trainloader, device, iterations)
        loss_rlnl_train, error_rlnl_train = evalaute_mdl_data_set(criterion,error_criterion,net_rlnl,trainloader,device,iterations)
        print(f'loss_nl_train, error_nl_train = {loss_nl_train, error_nl_train}')
        print(f'loss_rlnl_train, error_rlnl_train = {loss_rlnl_train, error_rlnl_train}')
        ''' test errors '''
        loss_nl_test, error_nl_test = evalaute_mdl_data_set(criterion, error_criterion, net_nl, testloader, device, iterations)
        loss_rlnl_test, error_rlnl_test = evalaute_mdl_data_set(criterion,error_criterion,net_rlnl,testloader,device,iterations)
        print(f'loss_nl_test, error_nl_test = {loss_nl_test, error_nl_test}')
        print(f'loss_rlnl_test, error_rlnl_test = {loss_rlnl_test, error_rlnl_test}')
        ''' '''
        store_results = False
        store_net = False
    elif args.train_alg == 'reach_target_loss':
        iterations = inf
        precision = 0.00001
        ''' set target loss '''
        loss_rlnl_train, error_rlnl_train = evalaute_mdl_data_set(criterion, error_criterion, net_rlnl, trainloader,device, iterations)
        target_train_loss = loss_rlnl_train
        ''' do SGD '''
        trainer = Trainer(trainloader,testloader, optimizer,criterion,error_criterion, stats_collector, device)
        last_errors = trainer.train_and_track_stats(net,nb_epochs,iterations=iterations,target_train_loss=target_train_loss,precision=precision)
        ''' Test the Network on the test data '''
        train_loss_epoch, train_error_epoch, test_loss_epoch, test_error_epoch = last_errors
        print(f'train_loss_epoch={train_loss_epoch} train_error_epoch={train_error_epoch}')
        print(f'test_loss_epoch={test_loss_epoch} test_error_epoch={test_error_epoch}')
        st()
    elif args.train_alg == 'no_train':
        print('NO TRAIN BRANCH')
    print(f'expt_path={expt_path}')
    utils.make_and_check_dir(expt_path)
    ''' save times '''
    seconds_training, minutes_training, hours_training = utils.report_times(training_time,meta_str='training')
    other_stats = dict({'seconds_training': seconds_training, 'minutes_training': minutes_training, 'hours_training': hours_training}, **other_stats)
    seconds, minutes, hours = seconds_training+seconds_setup, minutes_training+minutes_setup, hours_training+hours_setup
    other_stats = dict({'seconds':seconds,'minutes':minutes,'hours':hours}, **other_stats)
    print(f'nb_epochs = {nb_epochs}')
    print(f'Finished Training, hours={hours}')
    print(f'seed = {seed}, githash = {githash}')
    ''' save results from experiment '''
    store_results = not args.dont_save_expt_results
    print(f'ALL other_stats={other_stats}')
    if store_results:
        print(f'storing results!')
        matlab_path_to_filename = os.path.join(expt_path,matlab_file_name)
        save2matlab.save2matlab_flatness_expt(matlab_path_to_filename, stats_collector,other_stats=other_stats)
    ''' save net model '''
    if store_net:
        print(f'saving final net mdl!')
        net_path_to_filename = os.path.join(expt_path,net_file_name)
        torch.save(net,net_path_to_filename)
    # restored_net = utils.restore_entire_mdl(path)
    # loss_restored,error_restored = tr_alg.evalaute_mdl_data_set(criterion,error_criterion,restored_net,testloader,device)
    #print(f'\nloss_restored={loss_restored},error_restored={error_restored}\a')
    ''' send e-mail '''
    if hostname == 'polestar' or args.email:
        message = f'SLURM Job_id=MANUAL Name=flatness_expts.py Ended, ' \
                  f'Total Run time hours:{hours},minutes:{minutes},seconds:{seconds} COMPLETED, ExitCode [0-0]'
        utils.send_email(message,destination='brando90@mit.edu')
    ''' plot '''
    if sj == 0 and plot:
        #TODO
        plot_utils.plot_loss_and_accuracies(stats_collector)
        plt.show()

def check_order_data(trainloader):
    for i,data_train in enumerate(trainloader):
        if i==0:
            print(i)
            st()
            #print(data_train)
    for i,data_train in enumerate(trainloader):
        if i==3:
            print(i)
            #print(data_train)

if __name__ == '__main__':
    main()
    print('\a\a')
