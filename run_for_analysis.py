import subprocess

# Original Image Details
ori_img_path = 'files/ILSVRC2012_val_00018075.JPEG'
ori_img_type = 'original'
ori_save_path = 'out/'
ori_model_path = 'paths/pretrain_mae_vit_base_mask_0.75_400e.pth'

# Attacked Image Details
attacked_img_path = 'files/attacked_ILSVRC2012_val_00018075.JPEG'
attacked_img_type = 'attacked'
attacked_save_path = 'out/'
attacked_model_path = 'paths/pretrain_mae_vit_base_mask_0.75_400e.pth'

# Call the script with original image details
subprocess.run(['python3', 'run_mae_vis.py', ori_img_path, ori_img_type, ori_save_path, ori_model_path])

# Call the script with attacked image details
subprocess.run(['python3', 'run_mae_vis.py', attacked_img_path, attacked_img_type, attacked_save_path, attacked_model_path])
