CUDA_VISIBLE_DEVICES=0,1 python new_main.py \
  --synthetic_train_data_dir ../text_recognition_datasets/CVPR2016 ../text_recognition_datasets/NIPS2014/NIPS2014  \
  --test_data_dir ../text_recognition_datasets/scene_text_benchmarks/IIIT5K_3000 \
  --batch_size 512 \
  --workers 4 \
  --height 32 \
  --width 128 \
  --arch 1D \
  --decode_type DAN \
  --with_lstm \
  --max_len 25 \
  --epochs 6 \
  --adamdelta \
  --lr 1 \
  --alphabets allcases \
  --iter_mode \
  --randomsequentialsampler \