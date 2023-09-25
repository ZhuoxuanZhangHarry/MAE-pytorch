# -*- coding: utf-8 -*-
# @Time    : 2021/11/18 22:40
# @Author  : zhao pengfei
# @Email   : zsonghuan@gmail.com
# @File    : run_mae_vis.py
# --------------------------------------------------------
# Based on BEiT, timm, DINO and DeiT code bases
# https://github.com/microsoft/unilm/tree/master/beit
# https://github.com/rwightman/pytorch-image-models/tree/master/timm
# https://github.com/facebookresearch/deit
# https://github.com/facebookresearch/dino
# --------------------------------------------------------'

import argparse
import datetime
import numpy as np
import time
import torch
import torch.backends.cudnn as cudnn
import json
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from PIL import Image

from pathlib import Path

from timm.models import create_model

import utils
import modeling_pretrain
from datasets import DataAugmentationForMAE

from torchvision.transforms import ToPILImage
from einops import rearrange
from timm.data.constants import IMAGENET_DEFAULT_MEAN, IMAGENET_DEFAULT_STD

def get_args():
    parser = argparse.ArgumentParser('MAE visualization reconstruction script', add_help=False)
    parser.add_argument('img_path', type=str, help='input image path')
    parser.add_argument('save_path', type=str, help='save image path')
    parser.add_argument('model_path', type=str, help='checkpoint path of model')

    parser.add_argument('--input_size', default=224, type=int,
                        help='images input size for backbone')
    parser.add_argument('--device', default='cuda:0',
                        help='device to use for training / testing')
    parser.add_argument('--imagenet_default_mean_and_std', default=True, action='store_true')
    parser.add_argument('--mask_ratio', default=0.75, type=float,
                        help='ratio of the visual tokens/patches need be masked')
    # Model parameters
    parser.add_argument('--model', default='pretrain_mae_base_patch16_224', type=str, metavar='MODEL',
                        help='Name of model to vis')
    parser.add_argument('--drop_path', type=float, default=0.0, metavar='PCT',
                        help='Drop path rate (default: 0.1)')
    
    return parser.parse_args()


def get_model(args):
    print(f"Creating model: {args.model}")
    model = create_model(
        args.model,
        pretrained=False,
        drop_path_rate=args.drop_path,
        drop_block_rate=None,
    )

    return model

def compute_pixelwise_accuracy(original, reconstructed, threshold=0.05):
    abs_diff = torch.abs(original - reconstructed)

    correct_pixels = (abs_diff < threshold).float().sum()
    total_pixels = torch.numel(original)

    accuracy = correct_pixels / total_pixels
    
    return accuracy.item()

def compute_mse_for_masked_patches(ori_img, compare_img, bool_masked_pos, patch_size):
    mse_losses = []
    
    masked_indices = torch.where(bool_masked_pos == True)
    
    for idx in zip(masked_indices[0], masked_indices[1]):
        i = (idx[1] // (ori_img.shape[3] // patch_size[1])) * patch_size[0]
        j = (idx[1] % (ori_img.shape[3] // patch_size[1])) * patch_size[1]

        patch_ori = ori_img[0, :, i:i+patch_size[0], j:j+patch_size[1]]
        patch_compare = compare_img[0, :, i:i+patch_size[0], j:j+patch_size[1]]

        mse = ((patch_ori - patch_compare) ** 2).mean().item()
        mse_losses.append(mse)

    return mse_losses

def main(args):
    print(args)

    device = torch.device(args.device)
    cudnn.benchmark = True

    model = get_model(args)
    patch_size = model.encoder.patch_embed.patch_size
    print("Patch size = %s" % str(patch_size))
    args.window_size = (args.input_size // patch_size[0], args.input_size // patch_size[1])
    args.patch_size = patch_size

    model.to(device)
    checkpoint = torch.load(args.model_path, map_location='cpu')
    model.load_state_dict(checkpoint['model'])
    model.eval()

    with open(args.img_path, 'rb') as f:
        img = Image.open(f)
        img.convert('RGB')
        print("img path:", args.img_path)

    transforms = DataAugmentationForMAE(args)
    img, bool_masked_pos = transforms(img)
    bool_masked_pos = torch.from_numpy(bool_masked_pos)

    with torch.no_grad():
        img = img[None, :]
        bool_masked_pos = bool_masked_pos[None, :]
        img = img.to(device, non_blocking=True)
        bool_masked_pos = bool_masked_pos.to(device, non_blocking=True).flatten(1).to(torch.bool)
        outputs = model(img, bool_masked_pos)

        #save original img
        mean = torch.as_tensor(IMAGENET_DEFAULT_MEAN).to(device)[None, :, None, None]
        std = torch.as_tensor(IMAGENET_DEFAULT_STD).to(device)[None, :, None, None]
        ori_img = img * std + mean  # in [0, 1]
        img = ToPILImage()(ori_img[0, :])
        img.save(f"{args.save_path}/ori_img.jpg")

        img_squeeze = rearrange(ori_img, 'b c (h p1) (w p2) -> b (h w) (p1 p2) c', p1=patch_size[0], p2=patch_size[0])
        img_norm = (img_squeeze - img_squeeze.mean(dim=-2, keepdim=True)) / (img_squeeze.var(dim=-2, unbiased=True, keepdim=True).sqrt() + 1e-6)
        img_patch = rearrange(img_norm, 'b n p c -> b n (p c)')
        #updating the masked patches in img_patch with the reconstructed patches from the model's outputs.
        # if 
        img_patch[bool_masked_pos] = outputs

        #make mask
        mask = torch.ones_like(img_patch)
        mask[bool_masked_pos] = 0
        mask = rearrange(mask, 'b n (p c) -> b n p c', c=3)
        mask = rearrange(mask, 'b (h w) (p1 p2) c -> b c (h p1) (w p2)', p1=patch_size[0], p2=patch_size[1], h=14, w=14)

        #save reconstruction img
        rec_img = rearrange(img_patch, 'b n (p c) -> b n p c', c=3)
        # Notice: To visualize the reconstruction image, we add the predict and the original mean and var of each patch. Issue #40
        rec_img = rec_img * (img_squeeze.var(dim=-2, unbiased=True, keepdim=True).sqrt() + 1e-6) + img_squeeze.mean(dim=-2, keepdim=True)
        rec_img = rearrange(rec_img, 'b (h w) (p1 p2) c -> b c (h p1) (w p2)', p1=patch_size[0], p2=patch_size[1], h=14, w=14)
        img = ToPILImage()(rec_img[0, :].clip(0,0.996))
        img.save(f"{args.save_path}/rec_img.jpg")

         #save random mask img
        mask_img = rec_img * mask
        img = ToPILImage()(mask_img[0, :])
        img.save(f"{args.save_path}/mask_img.jpg")

        #calculate accuracy
        print("Accuracy: ", compute_pixelwise_accuracy(ori_img, rec_img))

        # calculate MSE for each patch: mask_img vs ori_img
        mse_losses = []
        for i in range(0, mask_img.shape[2], patch_size[0]):
            for j in range(0, mask_img.shape[3], patch_size[1]):
                patch_ori = ori_img[:, :, i:i+patch_size[0], j:j+patch_size[1]]
                patch_mask = mask_img[:, :, i:i+patch_size[0], j:j+patch_size[1]]
                
                mse = ((patch_ori - patch_mask) ** 2).mean().item()
                mse_losses.append(mse)

        # plot the MSE for each patch
        plt.figure(figsize=(10, 6))
        plt.plot(mse_losses, marker='o')
        plt.title('Mean Squared Error for Each Patch: mask_img vs ori_img')
        plt.xlabel('Patch Index')
        plt.ylabel('MSE')
        plt.grid(True)
        plt.savefig("out/mse_plot_mask.png", bbox_inches='tight', dpi=300)

        # calculate MSE for each patch: rec_img vs ori_img
        mse_losses = []
        for i in range(0, rec_img.shape[2], patch_size[0]):
            for j in range(0, rec_img.shape[3], patch_size[1]):
                patch_ori = ori_img[:, :, i:i+patch_size[0], j:j+patch_size[1]]
                patch_rec = rec_img[:, :, i:i+patch_size[0], j:j+patch_size[1]]
                
                mse = ((patch_ori - patch_rec) ** 2).mean().item()
                mse_losses.append(mse)

        # plot the MSE for each patch
        plt.figure(figsize=(10, 6))
        plt.plot(mse_losses, marker='o')
        plt.title('Mean Squared Error for Each Patch: rec_img vs ori_img')
        plt.xlabel('Patch Index')
        plt.ylabel('MSE')
        plt.grid(True)
        plt.savefig("out/mse_plot_rec.png", bbox_inches='tight', dpi=300)

        # Calculate MSE for masked patches: mask_img vs ori_img
        mse_masked_losses = compute_mse_for_masked_patches(ori_img, mask_img, bool_masked_pos, patch_size)

        # Plot the MSE for masked patches
        plt.figure(figsize=(10, 6))
        plt.plot(mse_masked_losses, marker='o')
        plt.title('MSE for Masked Patches: mask_img vs ori_img')
        plt.xlabel('Masked Patch Index')
        plt.ylabel('MSE')
        plt.grid(True)
        plt.savefig(f"{args.save_path}/mse_plot_masked_patches.png", bbox_inches='tight', dpi=300)

        # Calculate MSE for masked patches: rec_img vs ori_img
        mse_reconstructed_losses = compute_mse_for_masked_patches(ori_img, rec_img, bool_masked_pos, patch_size)

        # Plot the MSE for masked patches
        plt.figure(figsize=(10, 6))
        plt.plot(mse_reconstructed_losses, marker='o')
        plt.title('MSE for Masked Patches: rec_img vs ori_img')
        plt.xlabel('Masked Patch Index')
        plt.ylabel('MSE')
        plt.grid(True)
        plt.savefig(f"{args.save_path}/mse_plot_reconstructed_patches.png", bbox_inches='tight', dpi=300)


if __name__ == '__main__':
    opts = get_args()
    main(opts)
