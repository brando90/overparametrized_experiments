import numpy as np

import torch
from torch.autograd import Variable
import matplotlib.pyplot as plt

import pdb

def plot_1D_stuff(arg):
    N_train = arg.X_train.shape[0]
    ##
    x_horizontal = np.linspace(arg.data_lb,arg.data_ub,1000).reshape(1000,1)
    X_plot = arg.poly_feat.fit_transform(x_horizontal)
    X_plot_pytorch = Variable( torch.FloatTensor(X_plot), requires_grad=False)
    ##
    fig1 = plt.figure()
    #plots objs
    p_sgd, = plt.plot(x_horizontal, [ float(f_val) for f_val in arg.mdl_sgd.forward(X_plot_pytorch).data.numpy() ])
    p_pinv, = plt.plot(x_horizontal, np.dot(X_plot,arg.c_pinv))
    p_data, = plt.plot(arg.X_train,arg.data.Y_train.data.numpy(),'ro')
    ## legend
    nb_terms = arg.c_pinv.shape[0]
    plt.legend(
            [p_sgd,p_pinv,p_data],
            [arg.legend_mdl,f'min norm (pinv) number of monomials={nb_terms}',f'data points = {N_train}']
        )
    ##
    plt.xlabel('x'), plt.ylabel('f(x)')
    plt.title('SGD vs minimum norm solution curves')

def plot_iter_vs_error(arg):
    start = 1
    iterations_axis = np.arange(1,nb_iter,step=logging_freq)[start:]
    ##
    train_loss_list, test_loss_list, erm_lamdas = np.array(train_loss_list)[start:], np.array(test_loss_list)[start:], np.array(erm_lamdas)[start:]
    p_train_WP_legend = f'Train error reg_lambda = {reg_lambda}'
    p_test_WP_legend = f'Test error reg_lambda = {reg_lambda}'
    p_erm_reg_WP_legend = f'Error+Regularization, reg_lambda_WP = {reg_lambda}'
    ##
    fig1 = plt.figure()
    ##
    p_train_WP, = plt.plot(iterations_axis, train_loss_list_WP,color='m')
    p_test_WP, = plt.plot(iterations_axis, test_loss_list_WP,color='r')
    p_erm_reg_WP, = plt.plot(iterations_axis, erm_lamdas_WP,color='g')