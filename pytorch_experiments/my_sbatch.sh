#!/bin/bash

for i in {0..2};
do
    export CUDA_VISIBLE_DEVICES=$i
    #nohup python flatness_expts.py -train_alg brando_chiyuan_radius_inter -epochs 20 -mdl radius_flatness -nb_dirs 1000 -net_name NL -exptlabel RadiusFlatnessNL_samples20_RLarge50 &
    nohup python flatness_expts.py  -train_alg brando_chiyuan_radius_inter -epochs 20 -mdl radius_flatness -nb_dirs 500 -net_name NL -r_large 12 -exptlabel RadiusFlatnessNL_samples20 &
    sleep 1
done

for i in {3..5};
do
    export CUDA_VISIBLE_DEVICES=$i
    #nohup python flatness_expts.py -train_alg brando_chiyuan_radius_inter -epochs 20 -mdl radius_flatness -nb_dirs 1000 -net_name RLNL -exptlabel RadiusFlatnessRLNL_samples20_RLarge50 &
    nohup python flatness_expts.py -train_alg brando_chiyuan_radius_inter -epochs 20 -mdl radius_flatness -nb_dirs 500 -net_name RLNL -r_large 12 -exptlabel RadiusFlatnessRLNL_samples20 &
    sleep 1
done

echo 'sbatch submission DONE'