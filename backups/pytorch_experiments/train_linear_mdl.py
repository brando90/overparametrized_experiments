import numpy as np
from sklearn.preprocessing import PolynomialFeatures

import torch
from torch.autograd import Variable

import tensorflow as tf

from maps import NamedDict

from plotting_utils import *

import time

def get_batch(X,Y,M):
    N = len(Y)
    valid_indices = np.array( range(N) )
    batch_indices = np.random.choice(valid_indices,size=M,replace=False)
    batch_xs = X[batch_indices,:]
    batch_ys = Y[batch_indices]
    return batch_xs, batch_ys

def index_batch(X,batch_indices,dtype):
    '''
    returns the batch indexed/sliced batch
    '''
    if len(X.shape) == 1: # i.e. dimension (M,) just a vector
        batch_xs = torch.FloatTensor(X[batch_indices]).type(dtype)
    else:
        batch_xs = torch.FloatTensor(X[batch_indices,:]).type(dtype)
    return batch_xs

def get_batch2(X,Y,M,dtype):
    '''
    get batch for pytorch model
    '''
    # TODO fix and make it nicer, there is pytorch forum question
    X,Y = X.data.numpy(), Y.data.numpy()
    N = len(Y)
    valid_indices = np.array( range(N) )
    batch_indices = np.random.choice(valid_indices,size=M,replace=False)
    batch_xs = index_batch(X,batch_indices,dtype)
    batch_ys = index_batch(Y,batch_indices,dtype)
    return Variable(batch_xs, requires_grad=False), Variable(batch_ys, requires_grad=False)

def get_sequential_lifted_mdl(nb_monomials,D_out, bias=False):
    return torch.nn.Sequential(torch.nn.Linear(nb_monomials,D_out,bias=bias))

def train_SGD(mdl, M,eta,nb_iter,logging_freq ,dtype, X_train,Y_train, X_test,Y_test,c_pinv):
    ##
    grad_list = []
    train_errors = []
    ##
    N_train,_ = tuple( X_train.size() )
    for i in range(nb_iter):
        for W in mdl.parameters():
            W_before_update = np.copy( W.data.numpy() )
        # Forward pass: compute predicted Y using operations on Variables
        batch_xs, batch_ys = get_batch2(X_train,Y_train,M,dtype) # [M, D], [M, 1]
        ## FORWARD PASS
        y_pred = mdl.forward(batch_xs)
        ## LOSS + Regularization
        batch_loss = (1/M)*(y_pred - batch_ys).pow(2).sum()
        ## BACKARD PASS
        batch_loss.backward() # Use autograd to compute the backward pass. Now w will have gradients
        ## SGD update
        for W in mdl.parameters():
            delta = eta*W.grad.data
            #W.data.copy_(W.data - delta)
            W.data -= delta
        ## train stats
        current_train_loss = (1/N_train)*(mdl.forward(X_train) - Y_train).pow(2).sum().data.numpy()
        if i % (nb_iter/10) == 0 or i == 0:
        #if True:
            print('\n-------------')
            print(f'i = {i}, current_train_loss = {current_train_loss}')
            print(f'N_train = {N_train}')

            print('-W')
            print(f'W_before_update={W_before_update}')
            print(f'W.data = {W.data.numpy()}')

            print('--W.grad')
            print(f'W.grad.data.norm(2)={W.grad.data.norm(2)}')
            print(f'W.grad.data = {W.grad.data.numpy()}')
            diff = W_before_update - W.data.numpy()

            print(f' w_^(t) - w^(t-1) = {diff/eta}')
            diff_norm = np.linalg.norm(diff, 2)
            print(f'|| w_^(t) - w^(t-1) ||^2 = {diff_norm}')
            print(f'c_pinv = {c_pinv.T}')
            train_error_c_pinv = (1/N_train)*(np.linalg.norm(Y_train.data.numpy() - np.dot(X_train.data.numpy(),c_pinv) )**2)
            print(f'train_error_c_pinv = {train_error_c_pinv}')
        ##
        grad_list.append( W.grad.data.norm(2) )
        train_errors.append( current_train_loss )
        ## Manually zero the gradients after updating weights
        mdl.zero_grad()
    return grad_list,train_errors

##
start_time = time.time()
##
logging_freq = 100
dtype = torch.FloatTensor
## SGD params
M = 13
eta = 0.01
nb_iter = 300*1000
##
lb,ub=0,1
f_name='sin'
f_name='cos'
if f_name == 'sin':
    freq_sin = 4
    f_target = lambda x: np.sin(2*np.pi*freq_sin*x).reshape(x.shape[0],1)
    func_properties = f'freq_sin={freq_sin}'
elif f_name == 'cos':
    freq_cos = 4
    f_target = lambda x: np.cos(2*np.pi*freq_cos*x).reshape(x.shape[0],1)
    func_properties = f'freq_cos={freq_cos}'
else:
    raise ValueError('Function does not exist')
N_train = 17
X_train = np.linspace(lb,ub,N_train).reshape(N_train,1)
Y_train = f_target(X_train)
N_test = 100
eps_test = 0.2
X_test = np.linspace(lb+eps_test,ub-eps_test,N_test).reshape(N_test,1)
Y_test = f_target(X_test)
## degree of mdl
Degree_mdl = 16
## pseudo-inverse solution
poly_feat = PolynomialFeatures(degree=Degree_mdl)
Kern_train = poly_feat.fit_transform(X_train)
Kern_train_pinv = np.linalg.pinv( Kern_train )
c_pinv = np.dot(Kern_train_pinv, Y_train)
train_error_c_pinv = (1/N_train)*(np.linalg.norm(Y_train - np.dot(Kern_train,c_pinv) )**2)
print(f'Kern_train={Kern_train}')
print(f'train_error_c_pinv={train_error_c_pinv}')
#_pinv = np.polyfit( X_train.reshape( (N_train,) ), Y_train , Degree_mdl )[::-1]
## linear mdl to train with SGD
nb_terms = c_pinv.shape[0]
mdl_sgd = get_sequential_lifted_mdl(nb_monomials=nb_terms,D_out=1, bias=False)
#mdl_sgd[0].weight.data.normal_(mean=0,std=0.0)
#mdl_sgd[0].weight.data.fill_(0)
print(f'mdl_sgd[0].weight.data={mdl_sgd[0].weight.data}')
## Make polynomial Kernel
poly_feat = PolynomialFeatures(degree=Degree_mdl)
Kern_train, Kern_test = poly_feat.fit_transform(X_train.reshape(N_train,1)), poly_feat.fit_transform(X_test.reshape(N_test,1))
Kern_train_pt, Y_train_pt = Variable(torch.FloatTensor(Kern_train).type(dtype), requires_grad=False), Variable(torch.FloatTensor(Y_train).type(dtype), requires_grad=False)
Kern_test_pt, Y_test_pt = Variable(torch.FloatTensor(Kern_test).type(dtype), requires_grad=False ), Variable(torch.FloatTensor(Y_test).type(dtype), requires_grad=False)

train_error_c_pinv = (1/N_train)*(np.linalg.norm(Y_train.data.numpy() - np.dot(Kern_train_pt.data.numpy(),c_pinv) )**2)
print(f'train_error_c_pinv = {train_error_c_pinv}')
pdb.set_trace()
grad_list,train_errors = train_SGD(mdl_sgd, M,eta,nb_iter,logging_freq ,dtype, Kern_train_pt,Y_train_pt, Kern_test_pt,Y_test_pt,c_pinv)
#train_SGD_PTF(mdl_sgd, Kern_train_pt,Y_train_pt, M,eta,nb_iter,logging_freq, dtype)
##
# graph = tf.Graph()
# with graph.as_default():
#     X = tf.placeholder(tf.float32, [None, nb_terms])
#     Y = tf.placeholder(tf.float32, [None,1])
#     w = tf.Variable( tf.zeros([nb_terms,1]) )
#     #w = tf.Variable( tf.truncated_normal([Degree_mdl,1],mean=0.0,stddev=1.0) )
#     #w = tf.Variable( 1000*tf.ones([Degree_mdl,1]) )
#     ##
#     f = tf.matmul(X,w) # [N,1] = [N,D] x [D,1]
#     #loss = tf.reduce_sum(tf.square(Y - f))
#     loss = tf.reduce_sum( tf.reduce_mean(tf.square(Y-f), 0))
#     l2loss_tf = (1/N_train)*2*tf.nn.l2_loss(Y-f)
#     ##
#     learning_rate = eta
#     #global_step = tf.Variable(0, trainable=False)
#     #learning_rate = tf.train.exponential_decay(learning_rate=eta, global_step=global_step,decay_steps=nb_iter/2, decay_rate=1, staircase=True)
#     train_step = tf.train.GradientDescentOptimizer(learning_rate=learning_rate).minimize(loss)
#     with tf.Session(graph=graph) as sess:
#         Y_train = Y_train.reshape(N_train,1)
#         tf.global_variables_initializer().run()
#         # Train
#         for i in range(nb_iter):
#             #if i % (nb_iter/10) == 0:
#             if i % (nb_iter/10) == 0 or i == 0:
#                 current_loss = sess.run(fetches=loss, feed_dict={X: Kern_train, Y: Y_train})
#                 print(f'tf: i = {i}, current_loss = {current_loss}')
#             ## train
#             batch_xs, batch_ys = get_batch(Kern_train,Y_train,M)
#             sess.run(train_step, feed_dict={X: batch_xs, Y: batch_ys})
#         ## prepare tf plot point
#         x_horizontal = np.linspace(lb,ub,1000).reshape(1000,1)
#         Kern_plot = poly_feat.fit_transform(x_horizontal)
#         Y_tf = sess.run(f,feed_dict={X:Kern_plot, Y:Y_train})
##
x_horizontal = np.linspace(lb,ub,1000).reshape(1000,1)
legend_mdl = f'SGD solution standard parametrization, number of monomials={nb_terms}, batch-size={M}, iterations={nb_iter}, step size={eta}'
#### PLOTS
X_plot = poly_feat.fit_transform(x_horizontal)
X_plot_pytorch = Variable( torch.FloatTensor(X_plot), requires_grad=False)
##
fig1 = plt.figure()
##
p_f_target, = plt.plot(x_horizontal, f_target(x_horizontal) )
#p_sgd_tf, = plt.plot(x_horizontal, Y_tf )
p_sgd_pt, = plt.plot(x_horizontal, [ float(f_val) for f_val in mdl_sgd.forward(X_plot_pytorch).data.numpy() ])
p_pinv, = plt.plot(x_horizontal, np.dot(X_plot,c_pinv))
p_data, = plt.plot(X_train,Y_train,'ro')
## legend
nb_terms = c_pinv.shape[0]
legend_mdl = f'SGD solution standard parametrization, number of monomials={nb_terms}, batch-size={M}, iterations={nb_iter}, step size={eta}'
# plt.legend(
#         [p_f_target,p_sgd_tf,p_sgd_pt,p_pinv,p_data],
#         ['target function f(x)','TF '+legend_mdl,'Pytorch '+legend_mdl,f'linear algebra soln, number of monomials={nb_terms}',f'data points = {N_train}']
#     )
plt.legend(
        [p_f_target,p_sgd_pt,p_pinv,p_data],
        ['target function f(x)','Pytorch '+legend_mdl,f'linear algebra soln, number of monomials={nb_terms}',f'data points = {N_train}']
    )
##
plt.xlabel('x'), plt.ylabel('f(x)')
plt.title(f'Approx func {f_name}, func properties (like freq) {func_properties}, N_train = {N_train}')
## PLOT GRADIENTS
fig = plt.figure()
iter_axis = np.linspace(1,nb_iter,nb_iter)
plt.plot(iter_axis,grad_list)
plt.title('Gradients')
## train & test errors
fig = plt.figure()
iter_axis = np.linspace(1,nb_iter,nb_iter)
plt.plot(iter_axis,train_errors)
plt.title('Train Errors')
## REPORT TIMES
seconds = (time.time() - start_time)
minutes = seconds/ 60
hours = minutes/ 60
print("\a--- {} seconds --- \n --- {} minutes --- \n --- {} hours ---".format(seconds, minutes, hours) )
##
print('\a')
plt.show()
print('\a')
